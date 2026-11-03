import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OAuthState(Base, TimestampMixin):
    """OAuth state management for OAuth flows."""
    __tablename__ = "oauth_states"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    organization_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=True, index=True
    )
    state_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    chat_id: Mapped[str | None] = mapped_column(String, ForeignKey("chats.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Which integration started the flow, so one callback can route it ("google_sheets", "google_calendar").
    integration: Mapped[str] = mapped_column(String, nullable=False, default="google_sheets", server_default="google_sheets")

    __table_args__ = (
        Index("ix_oauth_states_user_state_used_expires", "user_id", "state_hash", "used", "expires_at"),
    )
