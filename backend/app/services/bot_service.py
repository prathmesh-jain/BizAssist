"""WhatsApp and Telegram bots: connect, receive, answer, and keep a trace of every step.

Flow for every incoming message:

    webhook (routers/webhooks.py)
      -> verify the platform's signature/secret, save the message once (duplicates are ignored),
         queue a "bot.inbound" job, answer 200 straight away
    job (process_inbound)
      -> checks: bot paused, handed to a person, rate limit, daily cap, unsupported media
      -> team bot:     linked member? -> the regular assistant, limited to the bot's tools
         customer bot: business-only check -> customer_agent with the bot's capabilities
      -> send the reply, store it with its trace; delivery statuses arrive later by webhook

Everything that goes wrong is stored on the message (status, error code, plain explanation),
so the Bots page can show what happened.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from cryptography.fernet import InvalidToken
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import customer_agent
from app.agents.tool_policy import DEFAULT_TEAM_GROUPS, GROUP_LABELS, TOOL_GROUPS, tool_names_for
from app.channels import errors as channel_errors
from app.channels import telegram, whatsapp
from app.channels.base import Button, ChannelError, Inbound, Parsed, StatusUpdate
from app.config import get_settings
from app.db.base import session_scope
from app.db.models.bot import Bot, BotConversation, BotIdentity, BotLinkCode, BotMessage
from app.services import jobs

logger = logging.getLogger(__name__)

LINK_CODE_TTL = timedelta(minutes=15)
WHATSAPP_WINDOW = timedelta(hours=24)
PLATFORM_LABEL = {"whatsapp": "WhatsApp", "telegram": "Telegram"}
_LINK_RE = re.compile(r"^/?(?:start\s+)?link[\s_:-]*(\d{6})\s*$", re.I)
_YES = {"yes", "y", "ok", "okay", "approve", "approved", "accept", "confirm", "sure", "go ahead", "haan", "ha"}
_NO = {"no", "n", "decline", "cancel", "reject", "stop", "nahi", "nope"}


class BotError(Exception):
    """A setup problem to show the person connecting the bot (bad token, missing setting...)."""

    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- credentials ----------

def _fernet():
    from app.services.user_settings_service import _fernet as fernet

    return fernet()


def encrypt_credentials(values: dict) -> str:
    return _fernet().encrypt(json.dumps(values).encode()).decode()


def credentials_of(bot: Bot) -> dict:
    try:
        return json.loads(_fernet().decrypt(bot.credentials.encode()).decode())
    except (InvalidToken, ValueError) as exc:
        raise BotError("This bot's saved credentials can't be read. Paste them again in its settings.") from exc


# ---------- settings ----------

def default_settings(audience: str) -> dict:
    common = {"daily_cap": get_settings().bot_daily_message_cap}
    if audience == "team":
        return {**common, "tools": list(DEFAULT_TEAM_GROUPS)}
    return {**common, "capabilities": list(customer_agent.DEFAULT_CAPABILITIES), "about": "",
            "booking": dict(customer_agent.DEFAULT_BOOKING), "leads": {"tab": "Leads"}, "documents": [],
            "greeting": ""}


def clean_settings(audience: str, raw: dict | None, current: dict | None = None) -> dict:
    """Merge a settings update, keeping only keys that belong to this kind of bot."""
    merged = {**default_settings(audience), **(current or {})}
    raw = raw or {}
    if "daily_cap" in raw:
        merged["daily_cap"] = max(1, min(int(raw["daily_cap"] or 1), 10000))
    if audience == "team":
        if "tools" in raw:
            merged["tools"] = [g for g in raw["tools"] or [] if g in TOOL_GROUPS]
        return {k: merged[k] for k in ("daily_cap", "tools")}
    if "capabilities" in raw:
        merged["capabilities"] = [c for c in raw["capabilities"] or [] if c in customer_agent.CAPABILITIES]
    if "about" in raw:
        merged["about"] = str(raw["about"] or "")[:6000]
    if "greeting" in raw:
        merged["greeting"] = str(raw["greeting"] or "")[:1000]
    if "documents" in raw:
        merged["documents"] = [str(d)[:300] for d in raw["documents"] or []][:3]
    if "booking" in raw:
        booking = {**customer_agent.DEFAULT_BOOKING, **(merged.get("booking") or {})}
        incoming = raw["booking"] or {}
        for key in ("start", "end"):
            if key in incoming and re.fullmatch(r"\d{1,2}:\d{2}", str(incoming[key])):
                booking[key] = str(incoming[key])
        for key, low, high in (("duration_minutes", 10, 240), ("days_ahead", 1, 60), ("max_per_contact", 0, 10)):
            if key in incoming:
                booking[key] = max(low, min(int(incoming[key]), high))
        for key in ("weekdays_only", "add_meet"):
            if key in incoming:
                booking[key] = bool(incoming[key])
        merged["booking"] = booking
    if "leads" in raw:
        leads = raw["leads"] or {}
        merged["leads"] = {"tab": str(leads.get("tab") or "Leads")[:60],
                           "spreadsheet_id": (str(leads["spreadsheet_id"])[:200] if leads.get("spreadsheet_id") else None)}
    return {k: merged[k] for k in ("daily_cap", "capabilities", "about", "greeting", "documents", "booking", "leads")}


# ---------- setup ----------

def webhook_url(bot: Bot) -> str:
    base = get_settings().public_api_url.rstrip("/")
    return f"{base}/api/webhooks/{bot.platform}/{bot.id}" if base else ""


def setup_info(bot: Bot) -> dict:
    info: dict = {"webhook_url": webhook_url(bot)}
    if bot.platform == "whatsapp":
        info.update(verify_token=bot.webhook_secret, webhook_fields=["messages"])
    return info


async def _verify_platform(platform: str, credentials: dict) -> tuple[str, str, dict]:
    """(external_id, handle, extra) after checking the credentials with the platform."""
    try:
        if platform == "telegram":
            token = (credentials.get("token") or "").strip()
            if not re.fullmatch(r"\d+:[\w-]{20,}", token):
                raise BotError("That doesn't look like a Telegram bot token. It looks like 123456789:AAH... and comes from @BotFather.")
            me = await telegram.get_me(token)
            return str(me["id"]), f"@{me.get('username')}", {"username": me.get("username"), "first_name": me.get("first_name")}
        token = (credentials.get("access_token") or "").strip()
        phone_id = (credentials.get("phone_number_id") or "").strip()
        if not token or not phone_id.isdigit():
            raise BotError("Paste the access token and the phone number ID (digits only) from Meta's API Setup page.")
        if not (credentials.get("app_secret") or "").strip():
            raise BotError("Paste the app secret (App settings > Basic). It's needed to check that messages really come from Meta.")
        number = await whatsapp.get_phone_number(token, phone_id)
        return phone_id, number.get("display_phone_number") or phone_id, {
            "verified_name": number.get("verified_name"), "quality_rating": number.get("quality_rating"),
            "waba_id": (credentials.get("waba_id") or "").strip() or None,
        }
    except ChannelError as exc:
        explained = channel_errors.explain(platform, exc.code)
        raise BotError(f"{PLATFORM_LABEL[platform]} said: {exc}" + (f" {explained['fix']}" if explained else "")) from exc


async def _register_webhook(bot: Bot, credentials: dict) -> dict:
    """Tell the platform where to send messages. Returns what happened, for the setup screen."""
    url = webhook_url(bot)
    if bot.platform == "telegram":
        if not url:
            return {"webhook": "missing_public_url"}
        try:
            await telegram.set_webhook(credentials["token"], url, bot.webhook_secret)
            return {"webhook": "registered"}
        except ChannelError as exc:
            return {"webhook": "failed", "error": str(exc)}
    waba_id = (bot.extra or {}).get("waba_id")
    if not waba_id:
        return {"subscribed": "skipped"}
    try:
        await whatsapp.subscribe_app(credentials["access_token"], waba_id)
        return {"subscribed": "ok"}
    except ChannelError as exc:
        return {"subscribed": "failed", "error": str(exc)}


def _creds_for(platform: str, raw: dict) -> dict:
    keys = ("token",) if platform == "telegram" else ("access_token", "app_secret", "phone_number_id", "waba_id")
    return {k: str(raw.get(k) or "").strip() for k in keys}


async def connect_bot(session: AsyncSession, *, organization_id: str, user_id: str, platform: str, audience: str,
                      name: str, credentials: dict, settings: dict | None = None) -> tuple[Bot, dict]:
    if platform not in ("whatsapp", "telegram") or audience not in ("team", "customer"):
        raise BotError("Choose WhatsApp or Telegram, and who the bot is for.")
    creds = _creds_for(platform, credentials)
    external_id, handle, extra = await _verify_platform(platform, creds)
    existing = (await session.execute(
        select(Bot).where(Bot.platform == platform, Bot.external_id == external_id))).scalar_one_or_none()
    if existing:
        same_org = existing.organization_id == organization_id
        raise BotError(f"This {PLATFORM_LABEL[platform]} {'number' if platform == 'whatsapp' else 'bot'} is already "
                       f"connected{' as “' + existing.name + '”' if same_org else ' to another BizAssist workspace'}.",
                       status=409)
    bot = Bot(organization_id=organization_id, created_by_user_id=user_id, platform=platform, audience=audience,
              name=(name or "").strip()[:80] or (handle or PLATFORM_LABEL[platform]), status="active",
              credentials=encrypt_credentials(creds), webhook_secret=secrets.token_urlsafe(24),
              external_id=external_id, handle=handle, extra=extra, settings=clean_settings(audience, settings))
    session.add(bot)
    await session.flush()
    result = await _register_webhook(bot, creds)
    bot.extra = {**bot.extra, "setup": result}
    return bot, {**setup_info(bot), **result}


async def update_bot(session: AsyncSession, bot: Bot, *, name: str | None = None, status: str | None = None,
                     settings: dict | None = None, credentials: dict | None = None) -> dict:
    result: dict = {}
    if name is not None and name.strip():
        bot.name = name.strip()[:80]
    if status in ("active", "paused"):
        bot.status = status
    if settings is not None:
        bot.settings = clean_settings(bot.audience, settings, bot.settings)
    if credentials:
        merged = {**credentials_of(bot), **{k: v for k, v in _creds_for(bot.platform, credentials).items() if v}}
        external_id, handle, extra = await _verify_platform(bot.platform, merged)
        if external_id != bot.external_id:
            raise BotError("These credentials belong to a different bot or number. Connect it as a new bot instead.")
        bot.credentials, bot.handle = encrypt_credentials(merged), handle
        bot.extra = {**(bot.extra or {}), **extra}
        result = await _register_webhook(bot, merged)
        bot.extra = {**bot.extra, "setup": result}
        bot.last_error = None
    bot.updated_at = _now()
    return result


async def delete_bot(session: AsyncSession, bot: Bot) -> None:
    if bot.platform == "telegram":
        try:
            await telegram.delete_webhook(credentials_of(bot)["token"])
        except (ChannelError, BotError, KeyError):
            pass  # the bot is going away either way
    await session.delete(bot)


async def get_bot(session: AsyncSession, organization_id: str, bot_id: str) -> Bot | None:
    bot = await session.get(Bot, bot_id)
    return bot if bot and bot.organization_id == organization_id else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def serialize_bot(session: AsyncSession, bot: Bot, *, user_id: str | None = None) -> dict:
    today = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    replies_today = await session.scalar(select(func.count()).select_from(BotMessage).where(
        BotMessage.bot_id == bot.id, BotMessage.direction == "out", BotMessage.author == "bot",
        BotMessage.created_at >= today))
    failed_today = await session.scalar(select(func.count()).select_from(BotMessage).where(
        BotMessage.bot_id == bot.id, BotMessage.status == "failed", BotMessage.created_at >= today))
    conversations = await session.scalar(select(func.count()).select_from(BotConversation).where(
        BotConversation.bot_id == bot.id, ~BotConversation.external_chat_id.startswith("test:")))
    linked = None
    if user_id and bot.audience == "team":
        linked = bool(await session.scalar(select(func.count()).select_from(BotIdentity).where(
            BotIdentity.bot_id == bot.id, BotIdentity.user_id == user_id)))
    last_error_code = (bot.extra or {}).get("last_error_code")
    return {
        "id": bot.id, "name": bot.name, "platform": bot.platform, "audience": bot.audience, "status": bot.status,
        "handle": bot.handle, "settings": bot.settings, "created_at": _iso(bot.created_at),
        "last_inbound_at": _iso(bot.last_inbound_at), "last_reply_at": _iso(bot.last_reply_at),
        "last_error": bot.last_error, "last_error_at": _iso(bot.last_error_at),
        "last_error_explained": channel_errors.explain(bot.platform, last_error_code),
        "stats": {"replies_today": replies_today or 0, "failed_today": failed_today or 0, "conversations": conversations or 0},
        "setup": setup_info(bot), "chat_link": chat_link(bot), "linked": linked,
        "verified_name": (bot.extra or {}).get("verified_name"),
    }


def chat_link(bot: Bot, text: str | None = None) -> str | None:
    from urllib.parse import quote

    if bot.platform == "telegram":
        username = (bot.extra or {}).get("username")
        if not username:
            return None
        return f"https://t.me/{username}" + (f"?start={quote(text.replace(' ', '_'))}" if text else "")
    digits = re.sub(r"\D", "", bot.handle or "")
    return f"https://wa.me/{digits}" + (f"?text={quote(text)}" if text else "") if digits else None


def options_for_settings() -> dict:
    return {
        "team_tools": [{"id": g, "label": GROUP_LABELS[g]} for g in TOOL_GROUPS],
        "customer_capabilities": [{"id": c, "label": customer_agent.CAPABILITY_LABELS[c]} for c in customer_agent.CAPABILITIES],
        "public_api_url_set": bool(get_settings().public_api_url),
    }


# ---------- linking team members ----------

async def create_link_code(session: AsyncSession, bot: Bot, user_id: str) -> dict:
    if bot.audience != "team":
        raise BotError("Only team bots link member accounts.")
    await session.execute(delete(BotLinkCode).where(
        (BotLinkCode.expires_at < _now()) | ((BotLinkCode.bot_id == bot.id) & (BotLinkCode.user_id == user_id))))
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = _now() + LINK_CODE_TTL
    session.add(BotLinkCode(code=f"{bot.id}:{code}", bot_id=bot.id, user_id=user_id, expires_at=expires))
    message = f"link {code}"
    return {"code": code, "message": message, "expires_at": expires.isoformat(), "chat_link": chat_link(bot, message)}


async def unlink(session: AsyncSession, bot: Bot, user_id: str) -> None:
    await session.execute(delete(BotIdentity).where(BotIdentity.bot_id == bot.id, BotIdentity.user_id == user_id))


# ---------- receiving ----------

async def _conversation(session: AsyncSession, bot: Bot, msg: Inbound) -> BotConversation:
    stmt = pg_insert(BotConversation).values(
        id=str(uuid.uuid4()), bot_id=bot.id, organization_id=bot.organization_id,
        external_chat_id=msg.chat_id, contact_name=msg.name, contact_handle=msg.handle, mode="bot",
        created_at=_now(), updated_at=_now(),
    ).on_conflict_do_nothing(index_elements=["bot_id", "external_chat_id"])
    await session.execute(stmt)
    conv = (await session.execute(select(BotConversation).where(
        BotConversation.bot_id == bot.id, BotConversation.external_chat_id == msg.chat_id))).scalar_one()
    if msg.name and msg.name != conv.contact_name:
        conv.contact_name = msg.name
    if msg.handle and msg.handle != conv.contact_handle:
        conv.contact_handle = msg.handle
    return conv


async def receive(session: AsyncSession, bot: Bot, parsed: Parsed) -> int:
    """Store new messages (each only once) and queue them. Returns how many were new."""
    new = 0
    for msg in parsed.messages:
        conv = await _conversation(session, bot, msg)
        now = _now()
        stmt = pg_insert(BotMessage).values(
            id=str(uuid.uuid4()), bot_id=bot.id, conversation_id=conv.id, direction="in",
            author="contact", external_message_id=msg.external_message_id, kind=msg.kind, text=msg.text[:8000],
            status="received", trace=[{"step": "received", "button_id": msg.button_id} if msg.button_id else {"step": "received"}],
            created_at=now, updated_at=now,
        ).on_conflict_do_nothing(
            index_elements=["bot_id", "direction", "external_message_id"],
            index_where=BotMessage.external_message_id.isnot(None),
        ).returning(BotMessage.id)
        message_id = (await session.execute(stmt)).scalar_one_or_none()
        if message_id is None:
            continue  # a retry of a message we already have
        new += 1
        conv.last_inbound_at = conv.last_message_at = now
        bot.last_inbound_at = now
        await jobs.enqueue(session, "bot.inbound", {"message_id": message_id, "button_id": msg.button_id,
                                                    "callback_id": msg.callback_id}, key=f"conv:{conv.id}")
    return new


async def apply_statuses(session: AsyncSession, bot: Bot, statuses: list[StatusUpdate]) -> None:
    order = {"sending": 0, "sent": 1, "delivered": 2, "read": 3, "failed": 4}
    for update in statuses:
        message = (await session.execute(select(BotMessage).where(
            BotMessage.bot_id == bot.id, BotMessage.direction == "out",
            BotMessage.external_message_id == update.external_message_id))).scalar_one_or_none()
        if message is None or order.get(update.status, -1) <= order.get(message.status, -1):
            continue  # statuses can arrive out of order; never go backwards
        message.status, message.updated_at = update.status, _now()
        if update.status == "failed":
            message.error, message.error_code = update.error, update.error_code
            _record_bot_error(bot, update.error or "Delivery failed", update.error_code)


def _record_bot_error(bot: Bot, error: str, code: str | None) -> None:
    bot.last_error, bot.last_error_at = error[:1000], _now()
    bot.extra = {**(bot.extra or {}), "last_error_code": code}


# ---------- answering ----------

@dataclass
class Outcome:
    text: str = ""
    buttons: list[Button] = field(default_factory=list)
    status: str = "answered"  # answered | blocked | ignored | failed
    error_code: str | None = None
    error: str | None = None
    trace: list[dict] = field(default_factory=list)
    handoff: bool = False


def _sse_events(chunk: str):
    for line in chunk.splitlines():
        if line.startswith("data: "):
            try:
                yield json.loads(line[6:])
            except ValueError:
                continue


def _interrupt_text(payload: dict) -> tuple[str, list[Button]]:
    question = str(payload.get("question") or "Please confirm.")
    lines = [question]
    for key, value in (payload.get("data") or {}).items():
        if value in (None, "", []):
            continue
        label = key.replace("_", " ").capitalize()
        lines.append(f"• {label}: {', '.join(map(str, value)) if isinstance(value, list) else value}")
    if (payload.get("interrupt_type") or "accept_decline") == "accept_decline":
        return "\n".join(lines), [Button("approve", "Approve"), Button("decline", "Decline")]
    options = [str(o) for o in payload.get("options") or []]
    if options and len(options) <= 3:
        return "\n".join(lines), [Button(f"opt:{i}", o[:20]) for i, o in enumerate(options)]
    if options:
        lines += [f"{i + 1}. {o}" for i, o in enumerate(options)]
    return "\n".join(lines), []


def _resume_value(pending: dict, text: str, button_id: str | None) -> tuple[bool, object]:
    """(understood, value) for an answer to a pending approval or question."""
    if (pending.get("interrupt_type") or "accept_decline") == "accept_decline":
        answer = (button_id or text or "").strip().lower()
        if answer in _YES or answer == "approve":
            return True, True
        if answer in _NO or answer == "decline":
            return True, False
        return False, None
    options = [str(o) for o in pending.get("options") or []]
    if button_id and button_id.startswith("opt:"):
        try:
            return True, options[int(button_id[4:])]
        except (ValueError, IndexError):
            pass
    if text.strip().isdigit() and options and 1 <= int(text.strip()) <= len(options):
        return True, options[int(text.strip()) - 1]
    return bool(text.strip()), text.strip()


def _team_channel(bot: Bot) -> dict:
    groups = (bot.settings or {}).get("tools") or []
    allowed = [GROUP_LABELS[g].lower() for g in groups if g in GROUP_LABELS]
    note = (
        f"You are replying on {PLATFORM_LABEL[bot.platform]} to a team member of this business. Keep replies short "
        "and chat-friendly: plain sentences and simple lists, no tables or headings. "
        "Approvals appear as buttons. "
        + (f"On this bot you can: {'; '.join(allowed)}. " if allowed else "On this bot you can only chat; no tools are enabled. ")
        + "If asked for something else, say it isn't enabled for this bot and can be done in the BizAssist web app."
    )
    return {"tool_policy": tool_names_for(groups), "channel_note": note, "strict_guardrail": True}


async def _team_outcome(bot: Bot, conv_id: str, msg: BotMessage, button_id: str | None, *,
                        as_user_id: str | None = None) -> Outcome:
    from app.repositories import ChatRepository, MessageRepository
    from app.repositories.membership_repository import MembershipRepository
    from app.services.chat_service import stream_agent_response

    out = Outcome()
    text = (msg.text or "").strip()
    platform = PLATFORM_LABEL[bot.platform]
    async with session_scope() as session:
        conv = await session.get(BotConversation, conv_id)
        external_user = conv.external_chat_id
        link = _LINK_RE.match(text)
        if link and not as_user_id:
            row = await session.get(BotLinkCode, f"{bot.id}:{link.group(1)}")
            if row is None or row.expires_at < _now():
                out.text = "That code isn't valid any more. Get a new one in BizAssist > Bots > Link my account."
                out.trace.append({"step": "link", "ok": False})
                return out
            await session.execute(delete(BotIdentity).where(BotIdentity.bot_id == bot.id, (
                (BotIdentity.user_id == row.user_id) | (BotIdentity.external_user_id == external_user))))
            session.add(BotIdentity(bot_id=bot.id, user_id=row.user_id, external_user_id=external_user,
                                    display_name=conv.contact_name or conv.contact_handle))
            await session.delete(row)
            conv.user_id, conv.chat_id, conv.pending_interrupt = row.user_id, None, None
            out.text = (f"You're linked. Ask me anything about the business here, like \"what's on my calendar "
                        f"tomorrow?\". Send /new to start a fresh conversation.")
            out.trace.append({"step": "link", "ok": True})
            return out

        user_id = as_user_id or await session.scalar(select(BotIdentity.user_id).where(
            BotIdentity.bot_id == bot.id, BotIdentity.external_user_id == external_user))
        member = await MembershipRepository.get_member(session, bot.organization_id, user_id) if user_id else None
        if member is None:
            if user_id:  # they left the organization
                await session.execute(delete(BotIdentity).where(BotIdentity.bot_id == bot.id, BotIdentity.user_id == user_id))
            out.status, out.error_code = "ignored", "not_linked"
            out.text = (f"This is a private assistant for the team. If you work here, open BizAssist > Bots > "
                        f"{bot.name} > Link my account, and send the code it shows here.")
            out.trace.append({"step": "identity", "linked": False})
            return out
        out.trace.append({"step": "identity", "linked": True, "user_id": user_id, "role": member.role})

        lowered = text.lower()
        if lowered in ("/start", "/help", "help"):
            out.text = (f"Hi! I'm your BizAssist assistant on {platform}. Ask about your calendar, sheets or "
                        f"documents. /new starts a fresh conversation.")
            return out
        if lowered == "/new":
            conv.chat_id, conv.pending_interrupt = None, None
            out.text = "Started a new conversation."
            return out
        if lowered == "/unlink":
            await session.execute(delete(BotIdentity).where(BotIdentity.bot_id == bot.id, BotIdentity.user_id == user_id))
            conv.user_id, conv.chat_id, conv.pending_interrupt = None, None, None
            out.text = "Unlinked. This chat no longer has access to BizAssist."
            return out

        if conv.user_id != user_id:
            conv.user_id, conv.chat_id, conv.pending_interrupt = user_id, None, None
        if conv.chat_id and not await ChatRepository.get_by_id(session, conv.chat_id, bot.organization_id, user_id):
            conv.chat_id = None
        if not conv.chat_id:
            chat = await ChatRepository.create(session, bot.organization_id, user_id, title=f"{platform}: {bot.name}")
            conv.chat_id = chat.id
        chat_id, role, pending = conv.chat_id, member.role, conv.pending_interrupt

        is_resume, resume_value = False, None
        if pending:
            understood, resume_value = _resume_value(pending, text, button_id)
            if not understood:
                out.text, out.buttons = _interrupt_text(pending)
                out.text = "Please answer this first:\n" + out.text
                out.trace.append({"step": "awaiting_answer"})
                return out
            is_resume = True
            conv.pending_interrupt = None
            await MessageRepository.mark_interrupts_resolved(session, chat_id, "accept" if resume_value is not False else "reject")
            out.trace.append({"step": "answer", "value": resume_value})
        if not is_resume or isinstance(resume_value, str):
            await MessageRepository.create(session, chat_id=chat_id, user_id=user_id, role="user",
                                           content=text if not is_resume else str(resume_value))
            await ChatRepository.update_timestamp(session, chat_id)

    reply, interrupt_payload, error = "", None, None
    started = time.monotonic()
    async for chunk in stream_agent_response(
        None if is_resume else text, chat_id, user_id, bot.organization_id, role=role,
        is_resume=is_resume, resume_value=resume_value, channel=_team_channel(bot),
    ):
        for event in _sse_events(chunk):
            kind = event.get("type")
            ms = int((time.monotonic() - started) * 1000)
            if kind == "token":
                reply += event.get("content") or ""
            elif kind == "tool_start":
                out.trace.append({"step": "tool", "tool": event.get("name"), "ms": ms})
            elif kind == "tool_end":
                out.trace.append({"step": "tool_done", "tool": event.get("name"), "ms": ms})
            elif kind == "calendar_change":
                out.trace.append({"step": "calendar_change", "action": event.get("action"), "title": event.get("title")})
            elif kind == "memory_updated":
                out.trace.append({"step": "memory", "changes": len(event.get("changes") or [])})
            elif kind == "interrupt":
                interrupt_payload = event.get("content") or {}
            elif kind == "error":
                error = event.get("content")
    out.trace.append({"step": "assistant", "ms": int((time.monotonic() - started) * 1000)})

    from app.agents.guardrail import _REFUSALS

    if interrupt_payload:
        question, out.buttons = _interrupt_text(interrupt_payload)
        out.text = (reply.strip() + "\n\n" if reply.strip() else "") + question
        out.trace.append({"step": "approval_requested", "question": interrupt_payload.get("question")})
        async with session_scope() as session:
            conv = await session.get(BotConversation, conv_id)
            conv.pending_interrupt = {k: interrupt_payload.get(k) for k in ("id", "question", "interrupt_type", "options", "data")}
    elif error and not reply.strip():
        out.status, out.error = "failed", error
        out.error_code = "ai_key" if "key" in error.lower() or "authentication" in error.lower() else "agent_error"
        out.text = "Sorry, something went wrong on my side. Please try again in a moment."
    else:
        out.text = reply.strip() or "Done."
        if out.text in _REFUSALS.values():
            out.status = "blocked"
            out.trace.append({"step": "guardrail", "verdict": "OFF_TOPIC"})
    return out


async def _customer_outcome(bot: Bot, conv_id: str, msg: BotMessage) -> Outcome:
    from app.services.business_profile_service import get_profile

    async with session_scope() as session:
        conv = await session.get(BotConversation, conv_id)
        profile = await get_profile(session, bot.organization_id)
        name, info = customer_agent.public_business_info(profile, (bot.settings or {}).get("about") or "")
        history_rows = (await session.execute(
            select(BotMessage).where(BotMessage.conversation_id == conv_id, BotMessage.id != msg.id,
                                     BotMessage.created_at <= msg.created_at, BotMessage.text != "")
            .order_by(BotMessage.created_at.desc()).limit(customer_agent.HISTORY_MESSAGES))).scalars().all()
        history = [("user" if m.direction == "in" else "assistant", m.text) for m in reversed(history_rows)
                   if m.status not in ("ignored",)]
        ctx = customer_agent.CustomerContext(
            organization_id=bot.organization_id, owner_user_id=bot.created_by_user_id or "", platform=bot.platform,
            business_name=name, business_info=info, settings=bot.settings or {}, contact_name=conv.contact_name,
            contact_handle=conv.contact_handle, conversation_id=conv_id,
        )
    if not ctx.owner_user_id:
        return Outcome(status="failed", error_code="ai_key", error="The person who connected this bot left the workspace.",
                       text="Sorry, this chat isn't available right now.")
    text = (msg.text or "").strip()
    greeting = (bot.settings or {}).get("greeting")
    if text.lower() == "/start" or (not history and greeting and text.lower() in ("hi", "hello", "hey", "hii")):
        return Outcome(text=greeting or f"Hi! You're chatting with {name}. How can we help?",
                       trace=[{"step": "greeting"}])
    try:
        result = await customer_agent.respond(ctx, text, history)
    except Exception as exc:  # noqa: BLE001 - shown on the Bots page
        logger.warning("bot.customer.failed bot=%s", bot.id, exc_info=True)
        message = f"{exc.__class__.__name__}: {exc}"[:500]
        code = "ai_key" if any(w in message.lower() for w in ("api key", "api_key", "authentication", "no ai provider")) else "agent_error"
        return Outcome(status="failed", error_code=code, error=message,
                       text="Sorry, I can't answer right now. Someone from the team will get back to you.")
    return Outcome(text=result.text, status=result.status, error_code=result.error_code, error=result.error,
                   trace=result.trace, handoff=result.handoff)


async def _send(bot: Bot, conv: BotConversation, text: str, buttons: list[Button]) -> list[str]:
    creds = credentials_of(bot)
    if bot.platform == "telegram":
        return await telegram.send_text(creds["token"], conv.external_chat_id, text, buttons or None)
    return await whatsapp.send_text(creds["access_token"], bot.external_id, conv.external_chat_id, text, buttons or None)


async def _typing(bot: Bot, conv: BotConversation, msg: BotMessage, callback_id: str | None) -> None:
    try:
        creds = credentials_of(bot)
        if bot.platform == "telegram":
            if callback_id:
                await telegram.answer_callback(creds["token"], callback_id)
            await telegram.typing(creds["token"], conv.external_chat_id)
        elif msg.external_message_id:
            await whatsapp.mark_read_and_typing(creds["access_token"], bot.external_id, msg.external_message_id)
    except BotError:
        pass


async def _limits(session: AsyncSession, bot: Bot, conv: BotConversation, msg: BotMessage) -> str | None:
    minute_ago = _now() - timedelta(minutes=1)
    recent = await session.scalar(select(func.count()).select_from(BotMessage).where(
        BotMessage.conversation_id == conv.id, BotMessage.direction == "in", BotMessage.created_at >= minute_ago))
    if (recent or 0) > get_settings().bot_messages_per_minute:
        return "rate_limited"
    today = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    replies = await session.scalar(select(func.count()).select_from(BotMessage).where(
        BotMessage.bot_id == bot.id, BotMessage.direction == "out", BotMessage.author == "bot",
        BotMessage.created_at >= today))
    if (replies or 0) >= int((bot.settings or {}).get("daily_cap") or get_settings().bot_daily_message_cap):
        return "daily_cap"
    return None


async def _store_reply(bot_id: str, conv_id: str, msg_id: str, outcome: Outcome, started: float, *, send: bool) -> None:
    """Send the reply (unless this is a test), store it, and finish the inbound message."""
    async with session_scope() as session:
        bot, conv, msg = await session.get(Bot, bot_id), await session.get(BotConversation, conv_id), await session.get(BotMessage, msg_id)
        now = _now()
        out_row = None
        if outcome.text:
            out_row = BotMessage(bot_id=bot.id, conversation_id=conv.id, direction="out", author="bot", kind="text",
                                 text=outcome.text, status="sending", reply_to_id=msg.id, trace=[],
                                 created_at=now, updated_at=now)
            if outcome.buttons:
                out_row.trace = [{"step": "buttons", "buttons": [b.title for b in outcome.buttons]}]
            session.add(out_row)
            await session.flush()
        if outcome.handoff:
            conv.mode = "human"
        await session.commit()

        if out_row is not None:
            if not send:
                out_row.status = "sent"
            else:
                try:
                    ids = await _send(bot, conv, outcome.text, outcome.buttons)
                    out_row.external_message_id, out_row.status = (ids[-1] if ids else None), "sent"
                    bot.last_reply_at = _now()
                    if bot.extra and bot.extra.get("last_error_code") in ("190", "401"):
                        bot.last_error = None  # a token problem that has since been fixed
                except (ChannelError, BotError) as exc:
                    code = getattr(exc, "code", None)
                    out_row.status, out_row.error, out_row.error_code = "failed", str(exc)[:1000], code
                    _record_bot_error(bot, str(exc), code)
                    logger.warning("bot.send.failed bot=%s code=%s %s", bot.id, code, exc)
            out_row.updated_at = _now()
            conv.last_message_at = _now()
        msg.status = outcome.status
        msg.trace = [*(msg.trace or []), *outcome.trace]
        msg.error, msg.error_code = outcome.error, outcome.error_code
        msg.latency_ms = int((time.monotonic() - started) * 1000)
        msg.updated_at = _now()
        if outcome.error_code in ("ai_key", "agent_error", "daily_cap"):
            _record_bot_error(bot, outcome.error or channel_errors.explain(bot.platform, outcome.error_code)["what"],
                              outcome.error_code)


async def handle_message(message_id: str, *, button_id: str | None = None, callback_id: str | None = None,
                         send: bool = True, as_user_id: str | None = None) -> None:
    started = time.monotonic()
    async with session_scope() as session:
        msg = await session.get(BotMessage, message_id)
        if msg is None or msg.status not in ("received", "processing"):
            return  # already handled (a retried job after a crash mid-way)
        bot = await session.get(Bot, msg.bot_id)
        conv = await session.get(BotConversation, msg.conversation_id)
        msg.status = "processing"
        outcome: Outcome | None = None
        if bot.status != "active":
            outcome = Outcome(status="ignored", trace=[{"step": "skipped", "reason": "bot paused"}])
        elif conv.mode == "human":
            outcome = Outcome(status="ignored", trace=[{"step": "skipped", "reason": "handed to a person"}])
        elif msg.kind in ("media", "unsupported") and not msg.text.strip():
            outcome = Outcome(text="I can only read text messages for now. Please type your message.",
                              trace=[{"step": "skipped", "reason": f"{msg.kind} message"}])
        elif send and (limit := await _limits(session, bot, conv, msg)):
            outcome = Outcome(status="ignored", error_code=limit, trace=[{"step": "skipped", "reason": limit}])
        if outcome is None and send:
            await _typing(bot, conv, msg, callback_id)
        bot_id, conv_id = bot.id, conv.id
    # Objects stay readable after the session closes (expire_on_commit=False); the run opens its own.
    if outcome is None:
        try:
            if bot.audience == "team":
                outcome = await _team_outcome(bot, conv_id, msg, button_id, as_user_id=as_user_id)
            else:
                outcome = await _customer_outcome(bot, conv_id, msg)
        except Exception as exc:  # noqa: BLE001 - stored and shown; the person gets a short apology
            logger.exception("bot.handle.failed bot=%s message=%s", bot_id, message_id)
            outcome = Outcome(status="failed", error_code="agent_error", error=f"{exc.__class__.__name__}: {exc}"[:1000],
                              text="Sorry, something went wrong on my side. Please try again in a moment.")
    await _store_reply(bot_id, conv_id, message_id, outcome, started, send=send)


@jobs.handler("bot.inbound")
async def _job_inbound(payload: dict) -> None:
    await handle_message(payload["message_id"], button_id=payload.get("button_id"), callback_id=payload.get("callback_id"))


# ---------- the inbox ----------

def _message_view(m: BotMessage, platform: str) -> dict:
    return {
        "id": m.id, "direction": m.direction, "author": m.author, "kind": m.kind, "text": m.text, "status": m.status,
        "error": m.error, "error_code": m.error_code, "explained": channel_errors.explain(platform, m.error_code),
        "trace": m.trace or [], "latency_ms": m.latency_ms, "reply_to_id": m.reply_to_id,
        "created_at": _iso(m.created_at), "updated_at": _iso(m.updated_at),
    }


async def list_conversations(session: AsyncSession, bot: Bot, *, q: str | None = None, problems: bool = False,
                             limit: int = 50, offset: int = 0) -> list[dict]:
    stmt = select(BotConversation).where(BotConversation.bot_id == bot.id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(BotConversation.contact_name.ilike(like) | BotConversation.contact_handle.ilike(like))
    if problems:
        stmt = stmt.where(BotConversation.id.in_(select(BotMessage.conversation_id).where(
            BotMessage.bot_id == bot.id, BotMessage.status.in_(("failed", "blocked")))))
    rows = (await session.execute(stmt.order_by(BotConversation.last_message_at.desc().nulls_last())
                                  .limit(limit).offset(offset))).scalars().all()
    out = []
    for conv in rows:
        last = (await session.execute(select(BotMessage).where(BotMessage.conversation_id == conv.id)
                                      .order_by(BotMessage.created_at.desc()).limit(1))).scalar_one_or_none()
        problems_count = await session.scalar(select(func.count()).select_from(BotMessage).where(
            BotMessage.conversation_id == conv.id, BotMessage.status.in_(("failed", "blocked"))))
        out.append({
            "id": conv.id, "contact_name": conv.contact_name, "contact_handle": conv.contact_handle, "mode": conv.mode,
            "is_test": conv.external_chat_id.startswith("test:"), "linked_user_id": conv.user_id,
            "last_message_at": _iso(conv.last_message_at), "last_inbound_at": _iso(conv.last_inbound_at),
            "can_reply": can_staff_reply(bot, conv)[0], "problems": problems_count or 0,
            "awaiting_approval": bool(conv.pending_interrupt),
            "last_message": {"text": last.text[:160], "direction": last.direction, "status": last.status} if last else None,
        })
    return out


async def conversation_messages(session: AsyncSession, bot: Bot, conv_id: str, *, limit: int = 200) -> dict | None:
    conv = await session.get(BotConversation, conv_id)
    if conv is None or conv.bot_id != bot.id:
        return None
    rows = (await session.execute(select(BotMessage).where(BotMessage.conversation_id == conv_id)
                                  .order_by(BotMessage.created_at.desc()).limit(limit))).scalars().all()
    ok, why = can_staff_reply(bot, conv)
    return {
        "conversation": {"id": conv.id, "contact_name": conv.contact_name, "contact_handle": conv.contact_handle,
                         "mode": conv.mode, "is_test": conv.external_chat_id.startswith("test:"),
                         "can_reply": ok, "reply_blocked_reason": why, "pending_interrupt": conv.pending_interrupt,
                         "chat_id": conv.chat_id},
        "messages": [_message_view(m, bot.platform) for m in reversed(rows)],
    }


def can_staff_reply(bot: Bot, conv: BotConversation) -> tuple[bool, str | None]:
    if conv.external_chat_id.startswith("test:"):
        return False, "This is a test conversation."
    if bot.platform == "whatsapp":
        if not conv.last_inbound_at or _now() - conv.last_inbound_at > WHATSAPP_WINDOW:
            return False, "WhatsApp allows free replies only within 24 hours of the customer's last message."
    return True, None


async def staff_reply(session: AsyncSession, bot: Bot, conv_id: str, text: str, *, user_id: str) -> dict:
    conv = await session.get(BotConversation, conv_id)
    if conv is None or conv.bot_id != bot.id:
        raise BotError("Conversation not found.", status=404)
    ok, why = can_staff_reply(bot, conv)
    if not ok:
        raise BotError(why or "Can't reply to this conversation.")
    now = _now()
    row = BotMessage(bot_id=bot.id, conversation_id=conv.id, direction="out", author="staff", kind="text",
                     text=text.strip()[:4000], status="sending", trace=[{"step": "staff", "user_id": user_id}],
                     created_at=now, updated_at=now)
    session.add(row)
    await session.flush()
    try:
        ids = await _send(bot, conv, row.text, [])
        row.external_message_id, row.status = (ids[-1] if ids else None), "sent"
    except ChannelError as exc:
        row.status, row.error, row.error_code = "failed", str(exc)[:1000], exc.code
    conv.last_message_at = row.updated_at = _now()
    return _message_view(row, bot.platform)


async def set_conversation_mode(session: AsyncSession, bot: Bot, conv_id: str, mode: str) -> None:
    conv = await session.get(BotConversation, conv_id)
    if conv is None or conv.bot_id != bot.id or mode not in ("bot", "human"):
        raise BotError("Conversation not found.", status=404)
    conv.mode = mode


async def simulate(bot_id: str, *, user_id: str, user_name: str, text: str) -> dict:
    """Run a message through the bot without sending anything, to test it from the Bots page."""
    async with session_scope() as session:
        bot = await session.get(Bot, bot_id)
        fake = Inbound(external_message_id=f"test:{secrets.token_hex(8)}", chat_id=f"test:{user_id}", user_id=user_id,
                       text=text, at=_now(), name=f"Test by {user_name}", handle=None)
        conv = await _conversation(session, bot, fake)
        now = _now()
        msg = BotMessage(bot_id=bot.id, conversation_id=conv.id, direction="in", author="contact", kind="text",
                         text=text[:4000], status="received", trace=[{"step": "received", "test": True}],
                         created_at=now, updated_at=now)
        conv.mode = "bot"
        session.add(msg)
        await session.flush()
        msg_id, conv_id = msg.id, conv.id
    await handle_message(msg_id, send=False, as_user_id=user_id if bot.audience == "team" else None)
    async with session_scope() as session:
        bot = await session.get(Bot, bot_id)
        return await conversation_messages(session, bot, conv_id, limit=2)


# ---------- health ----------

async def health(session: AsyncSession, bot: Bot) -> list[dict]:
    checks: list[dict] = []

    def add(check_id: str, label: str, ok: bool | None, detail: str = "", fix: str = "") -> None:
        checks.append({"id": check_id, "label": label, "ok": ok, "detail": detail, "fix": fix})

    settings = get_settings()
    add("public_url", "Server address for webhooks", bool(settings.public_api_url),
        webhook_url(bot) or "Not set", "" if settings.public_api_url else "Set PUBLIC_API_URL on the server to its public https address.")
    try:
        creds = credentials_of(bot)
    except BotError as exc:
        add("credentials", "Credentials", False, str(exc), "Paste the credentials again in Settings.")
        return checks
    try:
        if bot.platform == "telegram":
            await telegram.get_me(creds["token"])
            add("credentials", "Bot token", True, bot.handle or "")
            info = await telegram.webhook_info(creds["token"])
            registered = bool(info["url"]) and info["url"] == webhook_url(bot)
            add("webhook", "Telegram sends messages here", registered,
                f"Telegram is sending to {info['url'] or 'nowhere'}",
                "" if registered else "Press Reconnect to register the webhook again.")
            if info["last_error"]:
                add("delivery", "Telegram can reach the server", False,
                    f"{info['last_error']} ({info['last_error_at']})", "Check the server is running and reachable over https.")
            elif registered:
                add("delivery", "Telegram can reach the server", True, f"{info['pending_updates']} waiting")
        else:
            number = await whatsapp.get_phone_number(creds["access_token"], bot.external_id)
            add("credentials", "Access token and phone number", True,
                f"{number.get('display_phone_number')} · {number.get('verified_name') or ''}".strip(" ·"))
            verified = (bot.extra or {}).get("webhook_verified_at")
            add("webhook", "Webhook verified by Meta", bool(verified),
                f"Verified {verified}" if verified else "Meta hasn't checked the callback URL yet.",
                "" if verified else "In your Meta app: WhatsApp > Configuration > Webhook, paste the callback URL and "
                                    "verify token shown here, press Verify and save, then subscribe to 'messages'.")
            waba_id = (bot.extra or {}).get("waba_id")
            if waba_id:
                apps = await whatsapp.subscribed_apps(creds["access_token"], waba_id)
                add("subscribed", "App receives this number's messages", bool(apps),
                    f"{len(apps)} app(s) subscribed", "" if apps else "Press Reconnect, or check the WhatsApp Business Account ID.")
            else:
                add("subscribed", "App receives this number's messages", None, "Add the WhatsApp Business Account ID to check this.")
    except ChannelError as exc:
        explained = channel_errors.explain(bot.platform, exc.code)
        add("credentials", "Credentials", False, str(exc), explained["fix"] if explained else "Check the credentials in Settings.")

    if bot.last_inbound_at:
        add("inbound", "Messages arriving", True, f"Last message {bot.last_inbound_at.isoformat()}")
    else:
        add("inbound", "Messages arriving", None, "No message received yet. Send one to the bot to test.")
    if bot.last_error:
        explained = channel_errors.explain(bot.platform, (bot.extra or {}).get("last_error_code"))
        add("last_error", "Last problem", False,
            f"{explained['what'] if explained else bot.last_error} ({_iso(bot.last_error_at)})",
            explained["fix"] if explained else "")
    return checks


async def purge_old_messages() -> int:
    cutoff = _now() - timedelta(days=get_settings().bot_message_retention_days)
    async with session_scope() as session:
        result = await session.execute(delete(BotMessage).where(BotMessage.created_at < cutoff))
        await session.execute(delete(BotLinkCode).where(BotLinkCode.expires_at < _now()))
        return result.rowcount or 0


async def mark_webhook_verified(session: AsyncSession, bot: Bot) -> None:
    bot.extra = {**(bot.extra or {}), "webhook_verified_at": _now().isoformat()}


async def receive_telegram(session: AsyncSession, bot: Bot, update: dict) -> int:
    return await receive(session, bot, telegram.parse(update))


async def receive_whatsapp(session: AsyncSession, bot: Bot, payload: dict) -> int:
    parsed = whatsapp.parse(payload).get(bot.external_id)
    if not parsed:
        return 0
    await apply_statuses(session, bot, parsed.statuses)
    return await receive(session, bot, parsed)
