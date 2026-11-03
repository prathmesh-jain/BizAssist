import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, JSON, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OAuthConnection(Base, TimestampMixin):
    """OAuth connection tokens for external integrations."""
    __tablename__ = "oauth_connections"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)  # "google" (Sheets), "google_calendar"
    # "organization": one shared connection per org (Sheets); "user": one per member (Calendar).
    owner_scope: Mapped[str] = mapped_column(String, nullable=False, default="organization", server_default="organization")
    provider_account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    access_token_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    connection_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_oauth_connections_organization_provider", "organization_id", "provider"),
        Index(
            "uq_oauth_connections_org_shared", "organization_id", "provider",
            unique=True, postgresql_where=text("owner_scope = 'organization'"),
        ),
        Index(
            "uq_oauth_connections_user", "organization_id", "user_id", "provider",
            unique=True, postgresql_where=text("owner_scope = 'user'"),
        ),
    )
