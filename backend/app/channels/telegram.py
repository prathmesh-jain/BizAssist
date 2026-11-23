"""Telegram Bot API: a business pastes the token from @BotFather and we do the rest.

https://core.telegram.org/bots/api
"""
from __future__ import annotations

import hmac
from datetime import datetime, timezone

import httpx

from app.channels.base import Button, ChannelError, Inbound, Parsed
from app.channels.formatting import TELEGRAM_LIMIT, split_message, to_telegram_html

API = "https://api.telegram.org"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

# Tests replace this with a client on a mock transport.
http_client: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    return http_client or httpx.AsyncClient(timeout=20)


async def _call(token: str, method: str, payload: dict | None = None) -> dict:
    client = _client()
    try:
        resp = await client.post(f"{API}/bot{token}/{method}", json=payload or {})
    except httpx.HTTPError as exc:
        raise ChannelError(f"Could not reach Telegram ({exc.__class__.__name__}).") from exc
    finally:
        if client is not http_client:
            await client.aclose()
    try:
        data = resp.json()
    except ValueError:
        raise ChannelError(f"Telegram returned an unexpected response ({resp.status_code}).", status=resp.status_code)
    if not data.get("ok"):
        code = str(data.get("error_code") or resp.status_code)
        raise ChannelError(data.get("description") or "Telegram refused the request.", code=code, status=resp.status_code)
    return data.get("result")


def check_secret(header_value: str | None, expected: str) -> bool:
    return bool(header_value) and hmac.compare_digest(header_value, expected)


async def get_me(token: str) -> dict:
    """{"id", "username", "first_name"}; raises ChannelError for a bad token."""
    return await _call(token, "getMe")


async def set_webhook(token: str, url: str, secret: str) -> None:
    await _call(token, "setWebhook", {
        "url": url, "secret_token": secret, "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": False,
    })


async def delete_webhook(token: str) -> None:
    await _call(token, "deleteWebhook", {"drop_pending_updates": False})


async def webhook_info(token: str) -> dict:
    """Telegram's own view of delivery: pending updates and the last delivery error."""
    info = await _call(token, "getWebhookInfo")
    last_error_at = info.get("last_error_date")
    return {
        "url": info.get("url"),
        "pending_updates": info.get("pending_update_count", 0),
        "last_error": info.get("last_error_message"),
        "last_error_at": datetime.fromtimestamp(last_error_at, timezone.utc).isoformat() if last_error_at else None,
    }


def _name(user: dict) -> str | None:
    name = " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p).strip()
    return name or None


def parse(update: dict) -> Parsed:
    """Private-chat messages and button taps. Groups and channels are ignored."""
    parsed = Parsed()
    if "callback_query" in update:
        cq = update["callback_query"]
        message = cq.get("message") or {}
        chat = message.get("chat") or {}
        if chat.get("type") != "private":
            return parsed
        user = cq.get("from") or {}
        parsed.messages.append(Inbound(
            external_message_id=f"cb:{cq['id']}", chat_id=str(chat["id"]), user_id=str(user.get("id")),
            text=str(cq.get("data") or ""), kind="button", button_id=str(cq.get("data") or ""),
            callback_id=cq["id"], name=_name(user),
            handle=f"@{user['username']}" if user.get("username") else None, at=datetime.now(timezone.utc),
        ))
        return parsed
    message = update.get("message")
    if not message:
        return parsed
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return parsed
    user = message.get("from") or {}
    text = message.get("text")
    kind = "text"
    if text is None:
        kind = "media" if any(k in message for k in ("photo", "voice", "audio", "document", "video", "sticker")) else "unsupported"
        text = message.get("caption") or ""
    parsed.messages.append(Inbound(
        external_message_id=str(message["message_id"]), chat_id=str(chat["id"]), user_id=str(user.get("id")),
        text=text, kind=kind, name=_name(user), handle=f"@{user['username']}" if user.get("username") else None,
        at=datetime.fromtimestamp(message.get("date") or 0, timezone.utc) if message.get("date") else datetime.now(timezone.utc),
    ))
    return parsed


async def send_text(token: str, chat_id: str, markdown: str, buttons: list[Button] | None = None) -> list[str]:
    """Send a reply (split if long); buttons go on the last part. Returns Telegram message ids."""
    ids: list[str] = []
    parts = split_message(markdown, TELEGRAM_LIMIT) or [""]
    for i, part in enumerate(parts):
        payload: dict = {"chat_id": chat_id, "text": to_telegram_html(part) or "…", "parse_mode": "HTML",
                         "link_preview_options": {"is_disabled": True}}
        if buttons and i == len(parts) - 1:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": b.title[:64], "callback_data": b.id[:64]}] for b in buttons]}
        try:
            result = await _call(token, "sendMessage", payload)
        except ChannelError as exc:
            if exc.code != "400" or "parse" not in str(exc).lower():
                raise
            payload.pop("parse_mode")  # our HTML was rejected: send as plain text rather than not at all
            payload["text"] = part
            result = await _call(token, "sendMessage", payload)
        ids.append(str(result.get("message_id")))
    return ids


async def answer_callback(token: str, callback_id: str) -> None:
    try:
        await _call(token, "answerCallbackQuery", {"callback_query_id": callback_id})
    except ChannelError:
        pass  # only stops the button's loading spinner


async def remove_buttons(token: str, chat_id: str, message_id: str) -> None:
    try:
        await _call(token, "editMessageReplyMarkup", {"chat_id": chat_id, "message_id": int(message_id),
                                                       "reply_markup": {"inline_keyboard": []}})
    except (ChannelError, ValueError):
        pass


async def typing(token: str, chat_id: str) -> None:
    try:
        await _call(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
    except ChannelError:
        pass
