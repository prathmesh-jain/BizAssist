"""Long-term memory: what BizAssist remembers across conversations.

Three ways a memory is created:
  * the user asks ("remember that…") → the remember tool, saved immediately;
  * automatically after a reply → `extract_memories` asks a fast model what lasting facts the
    *user* stated and adds/updates/deletes accordingly (never blocks the reply);
  * activity → successful actions (meeting booked, rows added, document uploaded) are logged
    deterministically by `record_activity`, with no model involved.

Each turn, `build_memory_context` adds a compact [Memory] block to the agents' prompts.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import can
from app.db.models.memory import MEMORY_KINDS, Memory
from app.db.models.user_ai_settings import UserAISettings
from app.repositories.memory_repository import MemoryRepository
from app.services import memory_index
from app.services.memory_index import IndexedMemory

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 500
CONTEXT_CHAR_BUDGET = 3000
EDITABLE_KINDS = ("fact", "preference", "decision", "contact")


class MemoryChangeError(Exception):
    """A memory change was refused; the message is safe to show to the user."""


@dataclass(frozen=True)
class MemoryActor:
    organization_id: str
    user_id: str
    role: str | None


# ---------- validation ----------

_SECRET_PATTERNS = [
    re.compile(r"\b(sk|rk|pk)-[A-Za-z0-9_\-]{16,}"),                    # API keys (OpenAI-style)
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),                            # Google API keys
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),                               # card-like numbers
    re.compile(r"\b(password|passcode|passwd|pin|otp|cvv|secret key|api key)\b\s*(is|:|=)", re.I),
]


def looks_secret(text: str) -> bool:
    return any(p.search(text or "") for p in _SECRET_PATTERNS)


def normalize_topic(topic: str | None) -> str | None:
    t = re.sub(r"[^a-z0-9.]+", "_", (topic or "").strip().lower()).strip("_.")
    return t[:80] or None


def _clean_content(content: str) -> str:
    text = re.sub(r"\s+", " ", (content or "")).strip()
    if not text:
        raise MemoryChangeError("A memory can't be empty.")
    if len(text) > MAX_CONTENT_CHARS:
        raise MemoryChangeError(f"Keep a memory under {MAX_CONTENT_CHARS} characters.")
    if looks_secret(text):
        raise MemoryChangeError("That looks like a password, key or card number, so it wasn't saved. BizAssist doesn't store secrets.")
    return text


def can_write_shared(role: str | None) -> bool:
    return can(role, "memory.write_shared")


def can_edit(memory: Memory, actor: MemoryActor) -> bool:
    if memory.organization_id != actor.organization_id:
        return False
    if memory.scope == "personal":
        return memory.user_id == actor.user_id
    if can(actor.role, "memory.manage_shared"):
        return True
    return memory.created_by_user_id == actor.user_id and can_write_shared(actor.role)


def serialize(memory: Memory, actor: MemoryActor, created_by_name: str | None = None) -> dict:
    return {
        "id": memory.id,
        "content": memory.content,
        "kind": memory.kind,
        "scope": memory.scope,
        "topic": memory.topic,
        "source": memory.source,
        "source_chat_id": memory.source_chat_id,
        "pinned": memory.pinned,
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
        "created_by": {"id": memory.created_by_user_id, "name": created_by_name} if memory.created_by_user_id else None,
        "can_edit": can_edit(memory, actor),
        "replaced": bool(memory.supersedes_id),
    }


# ---------- search index sync ----------

def _indexed(memory: Memory) -> IndexedMemory:
    return IndexedMemory(memory.id, memory.organization_id, memory.scope, memory.user_id, memory.kind, memory.content)


async def embedding_key(session: AsyncSession, user_id: str) -> str | None:
    """The user's OpenAI key, used only for the shared embedding model (meaning-based search)."""
    from app.services.user_settings_service import get_user_openai_api_key

    try:
        return await get_user_openai_api_key(user_id, session) or None
    except Exception:
        logger.warning("memory.embedding_key_unavailable user=%s", user_id, exc_info=True)
        return None


async def _index(session: AsyncSession, actor: MemoryActor, memory: Memory) -> None:
    key = await embedding_key(session, actor.user_id)
    await memory_index.upsert([_indexed(memory)], api_key=key)
    if key:  # someone with a key is here: give meaning vectors to memories saved without one
        await memory_index.backfill_dense(actor.organization_id, key)


async def find_relevant(
    session: AsyncSession, actor: MemoryActor, text: str, *, limit: int = 8,
    kinds: tuple[str, ...] | None = None, exclude_kinds: tuple[str, ...] | None = ("activity",),
    scope: str | None = None,
) -> list[tuple[Memory, str | None]]:
    """Hybrid search (meaning + keywords with a key, keywords only without), loaded from Postgres in rank order."""
    if not (text or "").strip():
        return []
    ranked = await memory_index.search(
        text, organization_id=actor.organization_id, user_id=actor.user_id,
        api_key=await embedding_key(session, actor.user_id),
        limit=limit, kinds=kinds, exclude_kinds=exclude_kinds, scope=scope,
    )
    return await MemoryRepository.get_many_visible(session, actor.organization_id, actor.user_id, [i for i, _ in ranked])


# ---------- settings ----------

async def is_memory_enabled(session: AsyncSession, user_id: str) -> bool:
    value = await session.scalar(select(UserAISettings.memory_enabled).where(UserAISettings.user_id == user_id))
    return True if value is None else bool(value)


async def set_memory_enabled(session: AsyncSession, user_id: str, enabled: bool) -> bool:
    settings = await session.scalar(select(UserAISettings).where(UserAISettings.user_id == user_id))
    if settings is None:
        raise MemoryChangeError("Settings not found for this user.")
    settings.memory_enabled = bool(enabled)
    await session.flush()
    return settings.memory_enabled


# ---------- writes ----------

async def remember(
    session: AsyncSession,
    actor: MemoryActor,
    *,
    content: str,
    kind: str = "fact",
    scope: str = "shared",
    topic: str | None = None,
    source: str = "manual",
    chat_id: str | None = None,
) -> tuple[Memory, str]:
    """Save a memory. Returns (memory, action) where action is "added", "updated" or "unchanged".

    Viewers can't write shared memories; theirs are saved as personal instead. A memory on the
    same topic replaces the previous one (kept as "superseded" so it can be restored).
    """
    if kind not in EDITABLE_KINDS:
        raise MemoryChangeError(f"Unknown kind of memory: {kind}.")
    text = _clean_content(content)
    if kind == "preference":
        scope = "personal"
    if scope not in ("shared", "personal"):
        raise MemoryChangeError("Scope must be shared or personal.")
    if scope == "shared" and not can_write_shared(actor.role):
        scope = "personal"
    owner = actor.user_id if scope == "personal" else None
    topic = normalize_topic(topic)

    duplicate = await MemoryRepository.find_active_duplicate(
        session, actor.organization_id, scope=scope, user_id=owner, content=text
    )
    if duplicate:
        return duplicate, "unchanged"

    previous = (
        await MemoryRepository.find_active_by_topic(session, actor.organization_id, scope=scope, user_id=owner, topic=topic)
        if topic else None
    )
    memory = await MemoryRepository.create(
        session,
        organization_id=actor.organization_id,
        user_id=owner,
        created_by_user_id=actor.user_id,
        scope=scope,
        kind=kind,
        content=text,
        topic=topic,
        source=source,
        source_chat_id=chat_id,
        supersedes_id=previous.id if previous else None,
        pinned=bool(previous.pinned) if previous else False,
    )
    if previous:
        previous.status = "superseded"
        await session.flush()
        await memory_index.delete([previous.id])
        await _index(session, actor, memory)
        return memory, "updated"
    await _index(session, actor, memory)
    return memory, "added"


async def update_memory(
    session: AsyncSession, actor: MemoryActor, memory_id: str, *, content: str | None = None,
    kind: str | None = None, pinned: bool | None = None,
) -> Memory:
    memory = await MemoryRepository.get_visible(session, actor.organization_id, actor.user_id, memory_id)
    if memory is None or memory.status != "active":
        raise MemoryChangeError("That memory no longer exists.")
    if not can_edit(memory, actor):
        raise MemoryChangeError("You can't change this memory. Ask an admin of your organization.")
    if memory.kind == "activity" and (content is not None or kind is not None):
        raise MemoryChangeError("Activity entries can't be edited.")
    if kind is not None and kind not in EDITABLE_KINDS:
        raise MemoryChangeError("That kind of memory isn't supported.")

    new_text = _clean_content(content) if content is not None else None
    if new_text is not None and new_text != memory.content:
        # Edits are versioned like automatic updates: a new memory replaces this one (undo restores it).
        replacement = await MemoryRepository.create(
            session,
            organization_id=memory.organization_id, user_id=memory.user_id, created_by_user_id=actor.user_id,
            scope=memory.scope, kind=kind or memory.kind, content=new_text,
            topic=memory.topic, source="manual", source_chat_id=memory.source_chat_id,
            supersedes_id=memory.id, pinned=memory.pinned if pinned is None else bool(pinned),
        )
        memory.status = "superseded"
        await session.flush()
        await memory_index.delete([memory.id])
        await _index(session, actor, replacement)
        return replacement

    reindex = kind is not None and kind != memory.kind
    if kind is not None:
        memory.kind = kind
    if pinned is not None:
        memory.pinned = bool(pinned)
    memory.updated_at = datetime.now(timezone.utc)
    await session.flush()
    if reindex:
        await _index(session, actor, memory)
    return memory


async def forget(session: AsyncSession, actor: MemoryActor, memory_id: str) -> Memory:
    memory = await MemoryRepository.get_visible(session, actor.organization_id, actor.user_id, memory_id)
    if memory is None:
        raise MemoryChangeError("That memory no longer exists.")
    if not can_edit(memory, actor):
        raise MemoryChangeError("You can't delete this memory. Ask an admin of your organization.")
    await MemoryRepository.delete(session, memory)
    await memory_index.delete([memory.id])
    return memory


async def undo(session: AsyncSession, actor: MemoryActor, memory_id: str) -> Memory | None:
    """Undo a save: delete the memory and bring back the one it replaced, if any."""
    memory = await MemoryRepository.get_visible(session, actor.organization_id, actor.user_id, memory_id)
    if memory is None:
        return None
    if not can_edit(memory, actor):
        raise MemoryChangeError("You can't undo this memory change.")
    restored = None
    if memory.supersedes_id:
        restored = await MemoryRepository.get_by_id(session, actor.organization_id, memory.supersedes_id)
        if restored is not None:
            restored.status = "active"
    await MemoryRepository.delete(session, memory)
    await memory_index.delete([memory.id])
    if restored is not None:
        await _index(session, actor, restored)
    return restored


# ---------- activity ----------

async def record_activity(
    *, organization_id: str, user_id: str, content: str, scope: str = "shared", chat_id: str | None = None
) -> None:
    """Log something that was done. Runs in its own transaction and never raises."""
    from app.db.base import session_scope

    try:
        async with session_scope() as session:
            if not await is_memory_enabled(session, user_id):
                return
            memory = await MemoryRepository.create(
                session,
                organization_id=organization_id,
                user_id=user_id if scope == "personal" else None,
                created_by_user_id=user_id,
                scope=scope,
                kind="activity",
                content=re.sub(r"\s+", " ", content).strip()[:MAX_CONTENT_CHARS],
                source="activity",
                source_chat_id=chat_id,
            )
            # Indexed so "what did we do with Sharma?" can find it (recall_memory searches activity).
            await memory_index.upsert([_indexed(memory)], api_key=await embedding_key(session, user_id))
    except Exception:
        logger.warning("memory.activity.record_failed org=%s user=%s", organization_id, user_id, exc_info=True)


def _short_when(value: str | None) -> str:
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return moment.strftime("%a %d %b %Y, %H:%M")
    except ValueError:
        return str(value)


def describe_tool_activity(tool_name: str, args: dict, result: dict) -> tuple[str, str] | None:
    """(description, scope) for a successful action worth remembering, else None."""
    if not isinstance(result, dict) or result.get("ok") is not True:
        return None
    event = result.get("event") if isinstance(result.get("event"), dict) else {}
    title = event.get("title") or args.get("title") or "an event"
    if tool_name == "calendar_create_event":
        when = _short_when(event.get("start") or args.get("start"))
        meet = " with a Google Meet link" if event.get("meet_link") else ""
        guests = ", ".join(args.get("attendees") or [])
        with_guests = f" with {guests}" if guests else ""
        return f"Scheduled “{title}”{f' for {when}' if when else ''}{with_guests}{meet}.", "personal"
    if tool_name == "calendar_update_event":
        return f"Updated the calendar event “{title}”.", "personal"
    if tool_name == "calendar_delete_event":
        return "Cancelled a calendar event.", "personal"
    if tool_name == "sheets_append_values":
        rows = args.get("values") or []
        count = len(rows) if isinstance(rows, list) else 1
        return f"Added {count} row{'s' if count != 1 else ''} to the spreadsheet ({args.get('range_a1') or 'sheet'}).", "shared"
    if tool_name == "sheets_update_values":
        return f"Updated {args.get('range_a1') or 'cells'} in the spreadsheet.", "shared"
    if tool_name == "sheets_clear_values":
        return f"Cleared {args.get('range_a1') or 'cells'} in the spreadsheet.", "shared"
    if tool_name == "sheets_create_tab":
        return f"Created the spreadsheet tab “{args.get('title')}”.", "shared"
    if tool_name == "sheets_rename_tab":
        return f"Renamed the spreadsheet tab “{args.get('sheet_name')}” to “{args.get('new_title')}”.", "shared"
    if tool_name == "sheets_delete_tab":
        return f"Deleted the spreadsheet tab “{args.get('sheet_name')}”.", "shared"
    return None


# ---------- reading: the per-turn [Memory] block ----------

_KIND_LABEL = {"fact": "fact", "preference": "preference", "decision": "decision", "contact": "contact"}


async def build_memory_context(
    session: AsyncSession, *, organization_id: str, user_id: str, query: str | None
) -> str:
    """Compact memory block for this turn, within CONTEXT_CHAR_BUDGET:
    memories relevant to the message (hybrid search) first, then pinned and recently updated ones,
    then the last two weeks of activity."""
    try:
        if not await is_memory_enabled(session, user_id):
            return ""
        actor = MemoryActor(organization_id, user_id, None)
        core = await MemoryRepository.core(session, organization_id, user_id, limit=6)
        relevant = [m for m, _ in await find_relevant(session, actor, query or "", limit=8)]
        activity = await MemoryRepository.recent_activity(session, organization_id, user_id, days=14, limit=6)
    except Exception:
        logger.warning("memory.context.failed org=%s user=%s", organization_id, user_id, exc_info=True)
        return ""

    chosen: list[Memory] = []
    seen: set[str] = set()
    for memory in [*relevant, *core]:  # relevant first so they survive the budget
        if memory.id not in seen:
            seen.add(memory.id)
            chosen.append(memory)

    shared_lines, personal_lines, used_ids = [], [], []
    budget = CONTEXT_CHAR_BUDGET
    for memory in chosen:
        line = f"- ({_KIND_LABEL.get(memory.kind, memory.kind)}) {memory.content} [memory:{memory.id[:8]}]"
        if len(line) > budget:
            break
        budget -= len(line)
        used_ids.append(memory.id)
        (shared_lines if memory.scope == "shared" else personal_lines).append(line)

    activity_lines = []
    for memory, name in activity:
        line = f"- {memory.created_at.strftime('%d %b')}: {(name or 'Someone') + ' · ' if memory.scope == 'shared' else ''}{memory.content}"
        if len(line) > budget:
            break
        budget -= len(line)
        activity_lines.append(line)

    if not (shared_lines or personal_lines or activity_lines):
        return ""
    try:
        await MemoryRepository.mark_used(session, used_ids)
    except Exception:
        logger.warning("memory.mark_used.failed", exc_info=True)

    parts = [
        "Things BizAssist remembers from earlier conversations. Use them to personalize answers and avoid "
        "asking again. They can be out of date: documents, spreadsheets and calendar data win for numbers "
        "and live details. Don't recite this list unprompted."
    ]
    if shared_lines:
        parts.append("About the business:\n" + "\n".join(shared_lines))
    if personal_lines:
        parts.append("About this user:\n" + "\n".join(personal_lines))
    if activity_lines:
        parts.append("Recent activity:\n" + "\n".join(activity_lines))
    return "\n\n".join(parts)


# ---------- automatic extraction ----------

class _MemoryOp(BaseModel):
    action: Literal["add", "update", "delete"]
    kind: Literal["fact", "preference", "decision", "contact"] = "fact"
    scope: Literal["business", "personal"] = "business"
    topic: str = Field("", description="short snake_case subject, e.g. supplier_packaging or reply_style")
    content: str = Field("", description="one self-contained sentence, third person")
    target_id: str = Field("", description="for update/delete: the [id] of the existing memory")


class _MemoryOps(BaseModel):
    ops: list[_MemoryOp] = Field(default_factory=list)


_EXTRACT_SYSTEM = """You maintain BizAssist's long-term memory for a small business.
From the latest exchange, record only DURABLE information the USER stated or confirmed:
- business facts (suppliers, pricing, terms, staff and roles, customers, locations, policies, tools)
- contacts (people or companies and how they relate to the business)
- decisions the user made
- the user's personal preferences (formats, currency, tone, how they like reports)

Do NOT record: questions, one-off requests or tasks, small talk, anything only the assistant said,
data that lives in documents/spreadsheets/calendar, passwords/keys/card numbers, or guesses.

Compare with EXISTING memories: use "update" (with target_id) when the user changes something
already remembered, "delete" when they say it's no longer true, and nothing when it's already known.
Most exchanges need no change: return an empty list. At most 3 ops.
Write content as a self-contained sentence (e.g. "Sharma Packaging is the main packaging supplier; contact Meera.").
Preferences are always scope "personal"; business facts, contacts and decisions are "business"."""

_TRIVIAL = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|ok|okay|cool|great|yes|no|sure|bye)[\s!.]*$", re.I)


def worth_extracting(user_text: str) -> bool:
    text = (user_text or "").strip()
    return len(text) >= 15 and not _TRIVIAL.match(text)


async def extract_memories(
    *, organization_id: str, user_id: str, role: str | None, chat_id: str | None,
    user_text: str, assistant_text: str,
) -> list[dict]:
    """Learn from one exchange. Returns the changes made (for the "Memory updated" note). Never raises."""
    from app.db.base import session_scope
    from app.services.llm_providers import structured
    from app.services.llm_service import get_llm

    if not worth_extracting(user_text):
        return []
    actor = MemoryActor(organization_id, user_id, role)
    try:
        async with session_scope() as session:
            if not await is_memory_enabled(session, user_id):
                return []
            existing = [m for m, _ in await find_relevant(session, actor, user_text, limit=10)]
            existing_text = "\n".join(
                f"[{m.id}] ({m.scope}, {m.kind}{', topic ' + m.topic if m.topic else ''}) {m.content}" for m in existing
            ) or "(none)"
            llm = await get_llm(user_id=user_id, purpose="fast", temperature=0, session=session)

        result = await structured(llm, _MemoryOps).ainvoke([
            ("system", _EXTRACT_SYSTEM),
            ("human", f"EXISTING memories:\n{existing_text}\n\nUSER said:\n{user_text[:2000]}\n\n"
                      f"ASSISTANT replied:\n{(assistant_text or '')[:1500]}"),
        ])
        ops = (result.ops if isinstance(result, _MemoryOps) else _MemoryOps.model_validate(result).ops)[:3]
    except Exception:
        logger.warning("memory.extract.failed org=%s user=%s", organization_id, user_id, exc_info=True)
        return []

    changes: list[dict] = []
    known_ids = {m.id for m in existing}
    for op in ops:
        try:
            async with session_scope() as session:
                if op.action == "delete":
                    if op.target_id not in known_ids:
                        continue
                    memory = await forget(session, actor, op.target_id)
                    changes.append({"action": "deleted", "id": memory.id, "content": memory.content, "scope": memory.scope})
                    continue
                scope = "personal" if op.kind == "preference" or op.scope == "personal" else "shared"
                topic = op.topic
                if op.action == "update" and op.target_id in known_ids:
                    target = await MemoryRepository.get_visible(session, organization_id, user_id, op.target_id)
                    if target is not None and can_edit(target, actor):
                        topic = target.topic or normalize_topic(op.topic) or f"memory_{target.id[:8]}"
                        target.topic = topic  # so the new memory replaces this one
                        scope = target.scope
                        await session.flush()
                memory, action = await remember(
                    session, actor, content=op.content, kind=op.kind, scope=scope, topic=topic,
                    source="auto", chat_id=chat_id,
                )
                if action != "unchanged":
                    changes.append({"action": action, "id": memory.id, "content": memory.content, "scope": memory.scope})
        except MemoryChangeError as exc:
            logger.info("memory.extract.skipped: %s", exc)
        except Exception:
            logger.warning("memory.extract.apply_failed", exc_info=True)
    return changes
