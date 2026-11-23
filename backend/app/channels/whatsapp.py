"""WhatsApp Business Cloud API, with the business's own Meta app and token.

The business creates a Meta app with the WhatsApp product, and gives us: a permanent (System
User) access token, the phone number ID, the WhatsApp Business Account ID, and the app secret.
They paste our callback URL and verify token into the app's webhook settings; we subscribe the
app to their WhatsApp account so messages actually arrive.

https://developers.facebook.com/docs/whatsapp/cloud-api
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

import httpx

from app.channels.base import Button, ChannelError, Inbound, Parsed, StatusUpdate
from app.channels.formatting import WHATSAPP_LIMIT, split_message, to_whatsapp
from app.config import get_settings

SIGNATURE_HEADER = "X-Hub-Signature-256"

http_client: httpx.AsyncClient | None = None


def _base() -> str:
    return f"https://graph.facebook.com/{get_settings().whatsapp_graph_version}"


def _client() -> httpx.AsyncClient:
    return http_client or httpx.AsyncClient(timeout=20)


async def _request(method: str, path: str, token: str, *, json: dict | None = None, params: dict | None = None) -> dict:
    client = _client()
    try:
        resp = await client.request(method, f"{_base()}/{path.lstrip('/')}", json=json, params=params,
                                    headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise ChannelError(f"Could not reach WhatsApp ({exc.__class__.__name__}).") from exc
    finally:
        if client is not http_client:
            await client.aclose()
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400 or "error" in data:
        error = data.get("error") or {}
        details = (error.get("error_data") or {}).get("details")
        message = details or error.get("message") or f"WhatsApp returned {resp.status_code}."
        raise ChannelError(message, code=str(error.get("code") or resp.status_code), status=resp.status_code)
    return data


def check_signature(raw_body: bytes, header_value: str | None, app_secret: str) -> bool:
    if not header_value or not header_value.startswith("sha256=") or not app_secret:
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header_value.removeprefix("sha256="), expected)


async def get_phone_number(token: str, phone_number_id: str) -> dict:
    """{"display_phone_number", "verified_name", ...}; raises ChannelError for a bad token or id."""
    return await _request("GET", phone_number_id, token,
                          params={"fields": "display_phone_number,verified_name,quality_rating"})


async def subscribe_app(token: str, waba_id: str) -> None:
    """Without this, Meta doesn't send this WhatsApp account's messages to the app's webhook."""
    await _request("POST", f"{waba_id}/subscribed_apps", token)


async def subscribed_apps(token: str, waba_id: str) -> list[dict]:
    return (await _request("GET", f"{waba_id}/subscribed_apps", token)).get("data") or []


def _text_of(message: dict) -> tuple[str, str, str | None]:
    """(text, kind, button_id) for a WhatsApp message object."""
    kind = message.get("type")
    if kind == "text":
        return (message.get("text") or {}).get("body", ""), "text", None
    if kind == "interactive":
        interactive = message.get("interactive") or {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return reply.get("title", ""), "button", reply.get("id")
    if kind == "button":  # quick-reply button on a template
        button = message.get("button") or {}
        return button.get("text", ""), "button", button.get("payload")
    if kind in ("image", "audio", "video", "document", "sticker", "voice"):
        return (message.get(kind) or {}).get("caption", ""), "media", None
    return "", "unsupported", None


def parse(payload: dict) -> dict[str, Parsed]:
    """Messages and delivery statuses, grouped by the phone_number_id they were sent to."""
    out: dict[str, Parsed] = {}
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            phone_number_id = str((value.get("metadata") or {}).get("phone_number_id") or "")
            if not phone_number_id:
                continue
            parsed = out.setdefault(phone_number_id, Parsed())
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts") or []}
            for message in value.get("messages") or []:
                sender = str(message.get("from") or "")
                text, kind, button_id = _text_of(message)
                at = datetime.fromtimestamp(int(message.get("timestamp") or 0), timezone.utc) \
                    if message.get("timestamp") else datetime.now(timezone.utc)
                parsed.messages.append(Inbound(
                    external_message_id=str(message.get("id")), chat_id=sender, user_id=sender, text=text,
                    kind=kind, button_id=button_id, name=names.get(sender), handle=f"+{sender}" if sender else None, at=at,
                ))
            for status in value.get("statuses") or []:
                errors = status.get("errors") or []
                first = errors[0] if errors else {}
                parsed.statuses.append(StatusUpdate(
                    external_message_id=str(status.get("id")), status=str(status.get("status")),
                    error_code=str(first["code"]) if first.get("code") else None,
                    error=((first.get("error_data") or {}).get("details") or first.get("message") or first.get("title")),
                ))
    return out


async def send_text(token: str, phone_number_id: str, to: str, markdown: str,
                    buttons: list[Button] | None = None) -> list[str]:
    """Send a reply (split if long). Up to 3 reply buttons go on the last part. Returns message ids."""
    ids: list[str] = []
    parts = split_message(markdown, WHATSAPP_LIMIT if not buttons else 1024) or [""]
    for i, part in enumerate(parts):
        body = to_whatsapp(part) or "…"
        if buttons and i == len(parts) - 1:
            payload = {
                "messaging_product": "whatsapp", "to": to, "type": "interactive",
                "interactive": {
                    "type": "button", "body": {"text": body},
                    "action": {"buttons": [
                        {"type": "reply", "reply": {"id": b.id[:256], "title": b.title[:20]}} for b in buttons[:3]
                    ]},
                },
            }
        else:
            payload = {"messaging_product": "whatsapp", "to": to, "type": "text",
                       "text": {"body": body, "preview_url": False}}
        data = await _request("POST", f"{phone_number_id}/messages", token, json=payload)
        ids.extend(str(m.get("id")) for m in data.get("messages") or [])
    return ids


async def mark_read_and_typing(token: str, phone_number_id: str, message_id: str) -> None:
    """Blue ticks plus a typing indicator while the assistant works (it clears on reply, or after 25s)."""
    try:
        await _request("POST", f"{phone_number_id}/messages", token, json={
            "messaging_product": "whatsapp", "status": "read", "message_id": message_id,
            "typing_indicator": {"type": "text"},
        })
    except ChannelError:
        pass
