import uuid
from sqlalchemy import String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class UserIdentity(Base, TimestampMixin):
    """User identity mappings for external auth providers (e.g., Firebase)."""
    __tablename__ = "user_identities"

    id: Mapped[uuid.UUID] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)  # e.g., "firebase"
    provider_user_id: Mapped[str] = mapped_column(String, nullable=False)  # e.g., Firebase UID

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_provider_provider_user_id"),
    )
