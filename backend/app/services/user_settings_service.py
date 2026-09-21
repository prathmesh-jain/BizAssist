import logging
from typing import Literal

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.repositories import SettingsRepository

logger = logging.getLogger(__name__)
settings = get_settings()

LLMPurpose = Literal["primary", "fast", "nano"]


class UserSettingsError(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = (
        settings.user_secrets_encryption_key
        or settings.google_oauth_token_encryption_key
    )
    if not key:
        raise UserSettingsError(
            "No encryption key configured for user AI settings. "
            "Set USER_SECRETS_ENCRYPTION_KEY or GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY."
        )
    return Fernet(key)


def _default_models() -> dict[str, str]:
    return {
        "primary_model": settings.primary_model,
        "fast_model": settings.fast_model,
        "nano_model": settings.nano_model,
    }


async def get_user_ai_settings(user_id: str, session: AsyncSession) -> dict:
    """Get user AI settings from PostgreSQL."""
    ai_settings = await SettingsRepository.get_by_user_id(session, user_id)
    defaults = _default_models()

    if not ai_settings:
        return {
            "provider": "openai",
            "has_api_key": False,
            "chat_enabled": False,
            "guardrail_enabled": settings.use_guardrail,
            "primary_model": defaults["primary_model"].strip(),
            "fast_model": defaults["fast_model"].strip(),
            "nano_model": defaults["nano_model"].strip(),
        }

    return {
        "provider": ai_settings.provider,
        "has_api_key": bool(ai_settings.openai_api_key_encrypted),
        "chat_enabled": bool(ai_settings.openai_api_key_encrypted),
        "guardrail_enabled": ai_settings.guardrail_enabled,
        "primary_model": (ai_settings.primary_model or defaults["primary_model"]).strip(),
        "fast_model": (ai_settings.fast_model or defaults["fast_model"]).strip(),
        "nano_model": (ai_settings.nano_model or defaults["nano_model"]).strip(),
    }


async def update_user_ai_settings(
    user_id: str,
    session: AsyncSession,
    *,
    openai_api_key: str | None = None,
    clear_api_key: bool = False,
    guardrail_enabled: bool | None = None,
    primary_model: str | None = None,
    fast_model: str | None = None,
    nano_model: str | None = None,
) -> dict:
    """Update user AI settings in PostgreSQL."""
    if clear_api_key:
        await SettingsRepository.clear_api_key(session, user_id)

    if openai_api_key is not None:
        token = openai_api_key.strip()
        if token:
            encrypted = _fernet().encrypt(token.encode("utf-8")).decode("utf-8")
            await SettingsRepository.update_api_key(session, user_id, encrypted)

    if any(v is not None for v in (guardrail_enabled, primary_model, fast_model, nano_model)):
        await SettingsRepository.update_models(
            session,
            user_id,
            primary_model=primary_model,
            fast_model=fast_model,
            nano_model=nano_model,
            guardrail_enabled=guardrail_enabled,
        )

    return await get_user_ai_settings(user_id, session)


async def get_user_openai_api_key(user_id: str, session: AsyncSession) -> str:
    """Get and decrypt user's OpenAI API key."""
    ai_settings = await SettingsRepository.get_by_user_id(session, user_id)
    if not ai_settings or not ai_settings.openai_api_key_encrypted:
        return ""

    try:
        return _fernet().decrypt(
            ai_settings.openai_api_key_encrypted.encode("utf-8")
        ).decode("utf-8")
    except Exception as exc:
        logger.exception("Failed to decrypt user OpenAI API key")
        raise UserSettingsError("Stored OpenAI API key could not be decrypted.") from exc


async def require_user_openai_api_key(user_id: str, session: AsyncSession) -> str:
    """Require user to have an OpenAI API key configured."""
    api_key = await get_user_openai_api_key(user_id, session)
    if api_key:
        return api_key
    raise UserSettingsError(
        "OpenAI API key is required. Add it in Settings before using chat."
    )


async def get_user_model_for_purpose(user_id: str, purpose: LLMPurpose, session: AsyncSession) -> str:
    """Get the appropriate model for a given purpose."""
    ai_settings = await get_user_ai_settings(user_id, session)
    if purpose == "fast":
        return ai_settings["fast_model"]
    if purpose == "nano":
        return ai_settings["nano_model"]
    return ai_settings["primary_model"]
