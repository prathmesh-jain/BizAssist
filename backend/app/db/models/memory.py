import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

MEMORY_SCOPES = ("shared", "personal")
MEMORY_KINDS = ("fact", "preference", "decision", "contact", "activity")


class Memory(Base, TimestampMixin):
    """Something BizAssist remembers across conversations.

    scope "shared": business knowledge every member of the organization benefits from
    (user_id is NULL). scope "personal": about one member (their preferences, their
    calendar activity); only that member's conversations see it.

    A newer memory on the same topic replaces an older one: the old row is marked
    "superseded" and the new row points at it, so a change can be undone.

    Search runs in Qdrant (services/memory_index.py), which mirrors active memories with
    meaning (dense) and keyword (BM25) vectors.
    """
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=False)
    # Owner of a personal memory; NULL for shared memories.
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)

    scope: Mapped[str] = mapped_column(String, nullable=False)  # shared | personal
    kind: Mapped[str] = mapped_column(String, nullable=False)  # fact | preference | decision | contact | activity
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Short normalized subject (e.g. "supplier.packaging") so new facts replace old ones on the same topic.
    topic: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")  # chat | auto | activity | manual
    source_chat_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("chats.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(String, nullable=False, default="active")  # active | superseded
    supersedes_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_memories_org_scope_status", "organization_id", "scope", "status"),
        Index("ix_memories_org_user", "organization_id", "user_id"),
        Index("ix_memories_org_kind_created", "organization_id", "kind", "created_at"),
    )
