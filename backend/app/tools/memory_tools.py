"""Agent tools for long-term memory: remember, forget, and recall across conversations."""
from typing import Literal

from langchain_core.tools import tool

from app.db.base import session_scope
from app.repositories.memory_repository import MemoryRepository
from app.services import memory_service
from app.services.memory_service import MemoryActor, MemoryChangeError


def get_memory_tools(*, organization_id: str, user_id: str, role: str | None, chat_id: str | None) -> list:
    actor = MemoryActor(organization_id, user_id, role)

    @tool("remember")
    async def remember(
        content: str,
        kind: Literal["fact", "preference", "decision", "contact"] = "fact",
        scope: Literal["business", "personal"] = "business",
        topic: str = "",
    ) -> dict:
        """Save something to long-term memory so it's known in future conversations.

        Use when the user asks you to remember something, or states a lasting fact about the
        business, a contact, a decision, or their own preference. Write `content` as one
        self-contained sentence. `topic` is a short snake_case subject (e.g. supplier_packaging);
        a new memory with the same topic replaces the old one. Preferences are personal;
        business facts, contacts and decisions are shared with the team. Never store passwords,
        API keys or card numbers.
        """
        try:
            async with session_scope() as session:
                if not await memory_service.is_memory_enabled(session, user_id):
                    return {"ok": False, "error": "Memory is turned off in Settings, so nothing was saved."}
                memory, action = await memory_service.remember(
                    session, actor, content=content, kind=kind,
                    scope="personal" if scope == "personal" else "shared",
                    topic=topic or None, source="chat", chat_id=chat_id,
                )
                return {
                    "ok": True,
                    "action": action,
                    "memory": {"id": memory.id, "content": memory.content, "kind": memory.kind, "scope": memory.scope},
                }
        except MemoryChangeError as exc:
            return {"ok": False, "error": str(exc)}

    @tool("forget_memory")
    async def forget_memory(query: str = "", memory_id: str = "") -> dict:
        """Delete something from long-term memory when the user asks you to forget it or it is no
        longer true. Pass the memory id (from the [memory:…] tag or recall_memory) or a short query.
        If the query matches several memories, show them and ask which one."""
        try:
            async with session_scope() as session:
                target_id = memory_id.strip()
                if target_id and len(target_id) < 36:  # short id from a [memory:abcd1234] tag
                    matches, _ = await MemoryRepository.list_visible(session, organization_id, user_id, limit=500)
                    full = [m for m, _ in matches if m.id.startswith(target_id)]
                    target_id = full[0].id if len(full) == 1 else ""
                if not target_id:
                    found = await MemoryRepository.search(session, organization_id, user_id, query or "", limit=5)
                    if not found:
                        return {"ok": False, "error": "No matching memory found."}
                    if len(found) > 1:
                        return {
                            "ok": False,
                            "needs_choice": True,
                            "matches": [{"id": m.id, "content": m.content} for m in found],
                            "message": "Several memories match. Ask the user which one to forget, then call again with memory_id.",
                        }
                    target_id = found[0].id
                memory = await memory_service.forget(session, actor, target_id)
                return {"ok": True, "action": "deleted", "memory": {"id": memory.id, "content": memory.content, "scope": memory.scope}}
        except MemoryChangeError as exc:
            return {"ok": False, "error": str(exc)}

    @tool("recall_memory")
    async def recall_memory(query: str, limit: int = 8) -> dict:
        """Search long-term memory (business facts, contacts, decisions, preferences) beyond what is
        already in the [Memory] section, e.g. "what did we decide about freight?"."""
        async with session_scope() as session:
            found = await MemoryRepository.search(session, organization_id, user_id, query, limit=max(1, min(int(limit or 8), 20)))
            activity = await MemoryRepository.recent_activity(session, organization_id, user_id, days=60, limit=10)
            terms = set(query.lower().split())
            related_activity = [
                {"when": m.created_at.date().isoformat(), "by": name, "what": m.content}
                for m, name in activity if terms & set(m.content.lower().split())
            ]
            return {
                "ok": True,
                "memories": [
                    {"id": m.id, "content": m.content, "kind": m.kind, "scope": m.scope,
                     "saved": m.updated_at.date().isoformat() if m.updated_at else None}
                    for m in found
                ],
                "activity": related_activity,
            }

    return [remember, forget_memory, recall_memory]
