"""WhatsApp and Telegram bots connected by a business, and everything they send and receive.

A bot has exactly one audience:
  * "team": the business's own members, who link their WhatsApp number or Telegram account to
    their BizAssist login and then use the assistant (calendar, sheets, documents...) from chat,
    limited to the tools the admin allowed for this bot and by their own role.
  * "customer": anyone. It gets a small, fixed set of business capabilities (answer questions,
    book in free slots, save an enquiry, hand over to a person), never the general tools.

Every inbound and outbound message is stored with a trace of what happened in between, so the
Bots page can show why a bot answered the way it did, or why it didn't.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

BOT_PLATFORMS = ("whatsapp", "telegram")
BOT_AUDIENCES = ("team", "customer")


def _uuid() -> str:
    return str(uuid.uuid4())


class Bot(Base, TimestampMixin):
    __tablename__ = "bots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    # The admin who connected it. Customer bots use this person's AI key, calendar and sheets.
    created_by_user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    platform: Mapped[str] = mapped_column(String, nullable=False)  # whatsapp | telegram
    audience: Mapped[str] = mapped_column(String, nullable=False)  # team | customer
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")  # active | paused
    # Fernet-encrypted JSON: Telegram {"token"}; WhatsApp {"access_token", "app_secret"}.
    credentials: Mapped[str] = mapped_column(Text, nullable=False)
    # Random secret: Telegram's secret_token header, and WhatsApp's webhook verify token.
    webhook_secret: Mapped[str] = mapped_column(String, nullable=False)
    # Telegram bot id / WhatsApp phone_number_id: how the platform names this bot.
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    # What people see: "@sharma_orders_bot" or "+91 98200 11223".
    handle: Mapped[str | None] = mapped_column(String, nullable=True)
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # e.g. WhatsApp business account id
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_bots_platform_external_id"),)


class BotIdentity(Base, TimestampMixin):
    """A team member's WhatsApp number or Telegram account, linked to their BizAssist login."""
    __tablename__ = "bot_identities"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    bot_id: Mapped[str] = mapped_column(String, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("bot_id", "external_user_id", name="uq_bot_identities_bot_external"),
        UniqueConstraint("bot_id", "user_id", name="uq_bot_identities_bot_user"),
    )


class BotLinkCode(Base):
    """One-time code a member sends to a team bot ("/link 482913") to link their account."""
    __tablename__ = "bot_link_codes"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    bot_id: Mapped[str] = mapped_column(String, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BotConversation(Base, TimestampMixin):
    """One chat on WhatsApp/Telegram (one person talking to the bot)."""
    __tablename__ = "bot_conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    bot_id: Mapped[str] = mapped_column(String, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=False)
    external_chat_id: Mapped[str] = mapped_column(String, nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String, nullable=True)
    contact_handle: Mapped[str | None] = mapped_column(String, nullable=True)  # phone number or @username
    # Team bots: the linked member, and the BizAssist chat that holds this conversation.
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    chat_id: Mapped[str | None] = mapped_column(String, ForeignKey("chats.id", ondelete="SET NULL"), nullable=True)
    # "bot": the bot answers. "human": handed over; the bot stays quiet until someone resumes it.
    mode: Mapped[str] = mapped_column(String, nullable=False, default="bot")
    # A pending approval/question from the assistant waiting on this person's answer (team bots).
    pending_interrupt: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("bot_id", "external_chat_id", name="uq_bot_conversations_bot_chat"),
        Index("ix_bot_conversations_bot_last", "bot_id", "last_message_at"),
    )


class BotMessage(Base):
    """A message in or out, with what happened in between (the trace)."""
    __tablename__ = "bot_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    bot_id: Mapped[str] = mapped_column(String, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("bot_conversations.id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String, nullable=False)  # in | out
    # Who wrote an outbound message: the bot, or a person replying from the inbox.
    author: Mapped[str] = mapped_column(String, nullable=False, default="bot")  # contact | bot | staff | system
    external_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="text")  # text | button | media | command
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # in:  received | processing | answered | blocked | ignored | failed
    # out: sending | sent | delivered | read | failed
    status: Mapped[str] = mapped_column(String, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    # For outbound messages: the inbound message this answers.
    reply_to_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Steps between receiving and replying: guardrail verdict, tools used, timings.
    trace: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_bot_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_bot_messages_bot_created", "bot_id", "created_at"),
        Index(
            "uq_bot_messages_external", "bot_id", "direction", "external_message_id", unique=True,
            postgresql_where="external_message_id IS NOT NULL",
        ),
    )


class Job(Base):
    """Durable background work (see services/jobs.py). Survives restarts and retries on failure."""
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    # Jobs with the same key run one at a time, oldest first (e.g. messages in one conversation).
    key: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")  # queued | running | done | failed
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"), Index("ix_jobs_key_status", "key", "status"))
