from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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
        primary_model: Optional[str] = None,
        fast_model: Optional[str] = None,
        nano_model: Optional[str] = None,
        guardrail_enabled: bool = False,
    ) -> UserAISettings:
        """Create AI settings for a user; models default to the server's configured ones."""
        defaults = get_settings()
        settings = UserAISettings(
            user_id=user_id,
            provider=provider,
            primary_model=primary_model or defaults.primary_model,
            fast_model=fast_model or defaults.fast_model,
            nano_model=nano_model or defaults.nano_model,
            guardrail_enabled=guardrail_enabled,
        )
        session.add(settings)
        await session.flush()
        return settings

    @staticmethod
    async def _get_or_create(session: AsyncSession, user_id: str) -> UserAISettings:
        settings = await SettingsRepository.get_by_user_id(session, user_id)
        return settings or await SettingsRepository.create(session, user_id)

    @staticmethod
    async def update_api_keys(
        session: AsyncSession,
        user_id: str,
        updates: dict[str, Optional[str]],
    ) -> UserAISettings:
        """Set encrypted keys by provider; None removes that provider's key."""
        settings = await SettingsRepository._get_or_create(session, user_id)
        keys = dict(settings.api_keys_encrypted or {})
        for provider, cipher in updates.items():
            if cipher is None:
                keys.pop(provider, None)
            else:
                keys[provider] = cipher
        settings.api_keys_encrypted = keys  # reassign: JSON columns don't track in-place changes
        await session.flush()
        return settings

    @staticmethod
    async def update_provider(
        session: AsyncSession,
        user_id: str,
        *,
        provider: str,
        base_url: Optional[str],
    ) -> UserAISettings:
        settings = await SettingsRepository._get_or_create(session, user_id)
        settings.provider = provider
        settings.base_url = base_url
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
