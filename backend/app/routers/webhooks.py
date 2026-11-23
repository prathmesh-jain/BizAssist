"""Public endpoints WhatsApp and Telegram call. No login: each request is checked against the
bot's own secret (Telegram) or Meta's signature (WhatsApp) instead.

They only store and queue messages, then answer 200 at once; the reply is sent by a job. A
platform that gets errors or slow answers retries, and eventually stops sending.
"""
import json
import logging

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse

from app.channels import telegram, whatsapp
from app.db.base import get_db_session
from app.db.models.bot import Bot
from app.services import bot_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


async def _bot(session, bot_id: str, platform: str) -> Bot | None:
    bot = await session.get(Bot, bot_id)
    return bot if bot and bot.platform == platform else None


@router.post("/telegram/{bot_id}")
async def telegram_webhook(bot_id: str, request: Request, session = Depends(get_db_session, scope="function")):
    bot = await _bot(session, bot_id, "telegram")
    if bot is None:
        return Response(status_code=404)
    if not telegram.check_secret(request.headers.get(telegram.SECRET_HEADER), bot.webhook_secret):
        logger.warning("webhook.telegram.bad_secret bot=%s", bot_id)
        return Response(status_code=401)
    try:
        update = await request.json()
    except ValueError:
        return Response(status_code=400)
    await bot_service.receive_telegram(session, bot, update)
    return {"ok": True}


@router.get("/whatsapp/{bot_id}")
async def whatsapp_verify(bot_id: str, request: Request, session = Depends(get_db_session, scope="function")):
    """Meta's one-time check when the callback URL is saved in the app's webhook settings."""
    params = request.query_params
    bot = await _bot(session, bot_id, "whatsapp")
    if bot is None or params.get("hub.mode") != "subscribe" or params.get("hub.verify_token") != bot.webhook_secret:
        return Response(status_code=403)
    await bot_service.mark_webhook_verified(session, bot)
    return PlainTextResponse(params.get("hub.challenge") or "")


@router.post("/whatsapp/{bot_id}")
async def whatsapp_webhook(bot_id: str, request: Request, session = Depends(get_db_session, scope="function")):
    bot = await _bot(session, bot_id, "whatsapp")
    if bot is None:
        return Response(status_code=404)
    raw = await request.body()
    try:
        app_secret = bot_service.credentials_of(bot).get("app_secret", "")
    except bot_service.BotError:
        app_secret = ""
    if not whatsapp.check_signature(raw, request.headers.get(whatsapp.SIGNATURE_HEADER), app_secret):
        logger.warning("webhook.whatsapp.bad_signature bot=%s", bot_id)
        bot_service._record_bot_error(bot, "A webhook arrived with a signature that doesn't match the app secret.", "signature")
        return Response(status_code=401)
    try:
        payload = json.loads(raw)
    except ValueError:
        return Response(status_code=400)
    await bot_service.receive_whatsapp(session, bot, payload)
    return {"ok": True}
