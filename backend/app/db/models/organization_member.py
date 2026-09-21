import uuid
from sqlalchemy import String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OrganizationMember(Base, TimestampMixin):
    """Relationship between users and organizations."""
    __tablename__ = "organization_members"

    id: Mapped[uuid.UUID] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False, default="member")  # owner, admin, member, viewer
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")  # active, invited, suspended

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_organization_user"),
    )
