import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OrganizationInvitation(Base, TimestampMixin):
    """Invitation for an email address to join an organization with a role."""
    __tablename__ = "organization_invitations"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String, nullable=False)  # stored lowercased
    role: Mapped[str] = mapped_column(String, nullable=False)
    # Only a hash of the invite token is stored; the raw token is shown once to the inviter.
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")  # pending, accepted, revoked
    invited_by_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    accepted_by_user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # At most one open invitation per email per organization.
        Index(
            "uq_organization_invitations_pending_email",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )
