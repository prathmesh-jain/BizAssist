import uuid
from sqlalchemy import String, ForeignKey, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Message(Base, TimestampMixin):
    """Chat messages."""
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    chat_id: Mapped[str] = mapped_column(
        String, ForeignKey("chats.id"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)  # user, assistant, system, tool
    content: Mapped[str] = mapped_column(String, nullable=False, default="")
    tool_calls: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attachments: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    interrupt: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_messages_chat_created", "chat_id", "created_at"),
    )
