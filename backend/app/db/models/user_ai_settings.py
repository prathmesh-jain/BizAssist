import uuid
from sqlalchemy import String, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class UserAISettings(Base, TimestampMixin):
    """User AI settings including encrypted API keys."""
    __tablename__ = "user_ai_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), unique=True, nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String, nullable=False, default="openai")
    openai_api_key_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    guardrail_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    primary_model: Mapped[str] = mapped_column(String, nullable=False, default="gpt-4.1-mini")
    fast_model: Mapped[str] = mapped_column(String, nullable=False, default="gpt-4.1-mini")
    nano_model: Mapped[str] = mapped_column(String, nullable=False, default="gpt-4.1-nano")
