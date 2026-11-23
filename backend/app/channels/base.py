"""What every messaging channel (WhatsApp, Telegram) turns its webhooks into, and can send."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Inbound:
    """One message someone sent to a bot, in platform-neutral form."""
    external_message_id: str
    chat_id: str  # where to reply
    user_id: str  # who sent it (stable per person)
    text: str
    at: datetime
    kind: str = "text"  # text | button | media | unsupported
    name: str | None = None
    handle: str | None = None  # phone number or @username
    button_id: str | None = None  # for a tapped button
    callback_id: str | None = None  # Telegram: must be acknowledged


@dataclass
class StatusUpdate:
    """Delivery news about a message the bot sent (WhatsApp only)."""
    external_message_id: str
    status: str  # sent | delivered | read | failed
    error_code: str | None = None
    error: str | None = None


@dataclass
class Button:
    id: str
    title: str


@dataclass
class Parsed:
    messages: list[Inbound] = field(default_factory=list)
    statuses: list[StatusUpdate] = field(default_factory=list)


class ChannelError(Exception):
    """A platform API refused or failed. `code` is the platform's error code when there is one."""

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
