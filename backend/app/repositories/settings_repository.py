from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserAISettings


class SettingsRepository:
    """Repository for AI settings operations."""

    @staticmethod
    async def get_by_user_id(
        session: AsyncSession,
        user_id: str,
    ) -> Optional[UserAISettings]:
        """Get AI settings by user ID."""
        result = await session.execute(
            select(UserAISettings).where(UserAISettings.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession,
        user_id: str,
        provider: str = "openai",
        primary_model: str = "gpt-4.1-mini",
        fast_model: str = "gpt-4.1-mini",
        nano_model: str = "gpt-4.1-nano",
        guardrail_enabled: bool = False,
    ) -> UserAISettings:
        """Create AI settings for a user."""
        settings = UserAISettings(
            user_id=user_id,
            provider=provider,
            primary_model=primary_model,
            fast_model=fast_model,
            nano_model=nano_model,
            guardrail_enabled=guardrail_enabled,
        )
        session.add(settings)
        await session.flush()
        return settings

    @staticmethod
    async def update_api_key(
        session: AsyncSession,
        user_id: str,
        encrypted_key: str,
    ) -> UserAISettings:
        """Update or set the encrypted API key."""
        result = await session.execute(
            select(UserAISettings).where(UserAISettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()

        if settings:
            settings.openai_api_key_encrypted = encrypted_key
        else:
            settings = await SettingsRepository.create(session, user_id)
            settings.openai_api_key_encrypted = encrypted_key

        await session.flush()
        return settings

    @staticmethod
    async def clear_api_key(
        session: AsyncSession,
        user_id: str,
    ) -> Optional[UserAISettings]:
        """Clear the encrypted API key."""
        result = await session.execute(
            select(UserAISettings).where(UserAISettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        if settings:
            settings.openai_api_key_encrypted = None
            await session.flush()
        return settings

    @staticmethod
    async def update_models(
        session: AsyncSession,
        user_id: str,
        primary_model: Optional[str] = None,
        fast_model: Optional[str] = None,
        nano_model: Optional[str] = None,
        guardrail_enabled: Optional[bool] = None,
    ) -> UserAISettings:
        """Update model preferences and guardrail setting."""
        result = await session.execute(
            select(UserAISettings).where(UserAISettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()

        if not settings:
            settings = await SettingsRepository.create(session, user_id)

        if primary_model is not None:
            settings.primary_model = primary_model
        if fast_model is not None:
            settings.fast_model = fast_model
        if nano_model is not None:
            settings.nano_model = nano_model
        if guardrail_enabled is not None:
            settings.guardrail_enabled = guardrail_enabled

        await session.flush()
        return settings
