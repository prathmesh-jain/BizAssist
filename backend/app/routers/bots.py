"""Bots page API: connect WhatsApp/Telegram bots, configure them, watch their conversations."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.base import get_db_session
from app.db.models.bot import Bot
from app.dependencies import BotManager, BotViewer, ChatUser
from app.services import bot_service
from app.services.bot_service import BotError

router = APIRouter(prefix="/api/bots", tags=["bots"])


class BotCreate(BaseModel):
    platform: Literal["whatsapp", "telegram"]
    audience: Literal["team", "customer"]
    name: str = Field(default="", max_length=80)
    credentials: dict
    settings: dict | None = None


class BotUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    status: Literal["active", "paused"] | None = None
    settings: dict | None = None
    credentials: dict | None = None


class TestMessage(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class StaffReply(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ConversationMode(BaseModel):
    mode: Literal["bot", "human"]


def _error(exc: BotError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


async def _get(session, user, bot_id: str) -> Bot:
    bot = await bot_service.get_bot(session, user.organization.id, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot


@router.get("/options")
async def bot_options(user: ChatUser):
    return bot_service.options_for_settings()


@router.get("")
async def list_bots(user: ChatUser, session = Depends(get_db_session, scope="function")):
    """Everyone sees team bots (to link their account); customer bots need bots.view."""
    from app.authz import can

    rows = (await session.execute(select(Bot).where(Bot.organization_id == user.organization.id)
                                  .order_by(Bot.created_at))).scalars().all()
    viewer = can(user.role, "bots.view")
    bots = []
    for bot in rows:
        if not viewer and bot.audience != "team":
            continue
        data = await bot_service.serialize_bot(session, bot, user_id=user.user.id)
        if not viewer:
            data = {k: data[k] for k in ("id", "name", "platform", "audience", "status", "handle", "chat_link", "linked")}
        bots.append(data)
    return {"bots": bots, "can_view": viewer, "can_manage": can(user.role, "bots.manage")}


@router.post("")
async def create_bot(body: BotCreate, user: BotManager, session = Depends(get_db_session, scope="function")):
    try:
        bot, setup = await bot_service.connect_bot(
            session, organization_id=user.organization.id, user_id=user.user.id, platform=body.platform,
            audience=body.audience, name=body.name, credentials=body.credentials, settings=body.settings,
        )
    except BotError as exc:
        raise _error(exc) from exc
    return {"bot": await bot_service.serialize_bot(session, bot, user_id=user.user.id), "setup": setup}


@router.get("/{bot_id}")
async def get_bot(bot_id: str, user: BotViewer, session = Depends(get_db_session, scope="function")):
    return await bot_service.serialize_bot(session, await _get(session, user, bot_id), user_id=user.user.id)


@router.patch("/{bot_id}")
async def update_bot(bot_id: str, body: BotUpdate, user: BotManager, session = Depends(get_db_session, scope="function")):
    bot = await _get(session, user, bot_id)
    try:
        result = await bot_service.update_bot(session, bot, name=body.name, status=body.status,
                                              settings=body.settings, credentials=body.credentials)
    except BotError as exc:
        raise _error(exc) from exc
    return {"bot": await bot_service.serialize_bot(session, bot, user_id=user.user.id), "setup": result}


@router.post("/{bot_id}/reconnect")
async def reconnect_bot(bot_id: str, user: BotManager, session = Depends(get_db_session, scope="function")):
    """Register the webhook / app subscription again with the saved credentials."""
    bot = await _get(session, user, bot_id)
    try:
        result = await bot_service._register_webhook(bot, bot_service.credentials_of(bot))
    except BotError as exc:
        raise _error(exc) from exc
    bot.extra = {**(bot.extra or {}), "setup": result}
    return {"setup": {**bot_service.setup_info(bot), **result}}


@router.delete("/{bot_id}")
async def delete_bot(bot_id: str, user: BotManager, session = Depends(get_db_session, scope="function")):
    await bot_service.delete_bot(session, await _get(session, user, bot_id))
    return {"ok": True}


@router.get("/{bot_id}/health")
async def bot_health(bot_id: str, user: BotViewer, session = Depends(get_db_session, scope="function")):
    return {"checks": await bot_service.health(session, await _get(session, user, bot_id))}


@router.post("/{bot_id}/test")
async def test_bot(bot_id: str, body: TestMessage, user: BotViewer, session = Depends(get_db_session, scope="function")):
    """Run a message through the bot (guardrail, tools, AI) without sending anything."""
    bot = await _get(session, user, bot_id)
    await session.commit()
    name = user.user.full_name or user.user.email or "you"
    return await bot_service.simulate(bot.id, user_id=user.user.id, user_name=name, text=body.text)


@router.post("/{bot_id}/link-code")
async def link_code(bot_id: str, user: ChatUser, session = Depends(get_db_session, scope="function")):
    """Any member can link their own WhatsApp/Telegram to a team bot."""
    bot = await bot_service.get_bot(session, user.organization.id, bot_id)
    if bot is None or bot.audience != "team":
        raise HTTPException(status_code=404, detail="Bot not found")
    try:
        return await bot_service.create_link_code(session, bot, user.user.id)
    except BotError as exc:
        raise _error(exc) from exc


@router.delete("/{bot_id}/link")
async def unlink(bot_id: str, user: ChatUser, session = Depends(get_db_session, scope="function")):
    bot = await bot_service.get_bot(session, user.organization.id, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    await bot_service.unlink(session, bot, user.user.id)
    return {"ok": True}


@router.get("/{bot_id}/conversations")
async def conversations(
    bot_id: str, user: BotViewer, q: str | None = Query(default=None, max_length=100), problems: bool = False,
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
    session = Depends(get_db_session, scope="function"),
):
    bot = await _get(session, user, bot_id)
    return {"conversations": await bot_service.list_conversations(session, bot, q=q, problems=problems,
                                                                  limit=limit, offset=offset)}


@router.get("/{bot_id}/conversations/{conversation_id}")
async def conversation(bot_id: str, conversation_id: str, user: BotViewer,
                       session = Depends(get_db_session, scope="function")):
    data = await bot_service.conversation_messages(session, await _get(session, user, bot_id), conversation_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return data


@router.post("/{bot_id}/conversations/{conversation_id}/reply")
async def reply(bot_id: str, conversation_id: str, body: StaffReply, user: BotViewer,
                session = Depends(get_db_session, scope="function")):
    bot = await _get(session, user, bot_id)
    if bot.audience != "customer":
        raise HTTPException(status_code=400, detail="Replying from the inbox is for customer bots.")
    try:
        return await bot_service.staff_reply(session, bot, conversation_id, body.text, user_id=user.user.id)
    except BotError as exc:
        raise _error(exc) from exc


@router.patch("/{bot_id}/conversations/{conversation_id}")
async def set_mode(bot_id: str, conversation_id: str, body: ConversationMode, user: BotViewer,
                   session = Depends(get_db_session, scope="function")):
    try:
        await bot_service.set_conversation_mode(session, await _get(session, user, bot_id), conversation_id, body.mode)
    except BotError as exc:
        raise _error(exc) from exc
    return {"ok": True, "mode": body.mode}
