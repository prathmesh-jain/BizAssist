import logging
from typing import Literal

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.repositories import SettingsRepository
from app.services.llm_providers import PROVIDERS, LLMCredentials, ProviderError, validate_base_url

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


def _decrypt(cipher: str) -> str:
    try:
        return _fernet().decrypt(cipher.encode("utf-8")).decode("utf-8")
    except UserSettingsError:
        raise
    except Exception as exc:
        logger.exception("Failed to decrypt a stored API key")
        raise UserSettingsError("A stored API key could not be decrypted. Save it again in Settings.") from exc


def _is_ready(provider: str, keys: dict, base_url: str | None) -> bool:
    if PROVIDERS[provider].needs_base_url:
        return bool(base_url)
    return bool(keys.get(provider))


async def get_user_ai_settings(user_id: str, session: AsyncSession) -> dict:
    """Get user AI settings from PostgreSQL."""
    ai_settings = await SettingsRepository.get_by_user_id(session, user_id)
    defaults = _default_models()

    if not ai_settings:
        return {
            "provider": "openai",
            "base_url": None,
            "has_api_key": False,
            "chat_enabled": False,
            "has_embedding_key": False,
            "saved_key_providers": [],
            "guardrail_enabled": settings.use_guardrail,
            "primary_model": defaults["primary_model"].strip(),
            "fast_model": defaults["fast_model"].strip(),
            "nano_model": defaults["nano_model"].strip(),
        }

    keys = ai_settings.api_keys_encrypted or {}
    provider = ai_settings.provider if ai_settings.provider in PROVIDERS else "openai"
    return {
        "provider": provider,
        "base_url": ai_settings.base_url,
        "has_api_key": bool(keys.get(provider)),
        "chat_enabled": _is_ready(provider, keys, ai_settings.base_url),
        "has_embedding_key": bool(keys.get("openai")),
        "saved_key_providers": sorted(keys),
        "guardrail_enabled": ai_settings.guardrail_enabled,
        "primary_model": (ai_settings.primary_model or defaults["primary_model"]).strip(),
        "fast_model": (ai_settings.fast_model or defaults["fast_model"]).strip(),
        "nano_model": (ai_settings.nano_model or defaults["nano_model"]).strip(),
    }


async def update_user_ai_settings(
    user_id: str,
    session: AsyncSession,
    *,
    provider: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    openai_api_key: str | None = None,
    clear_api_key: bool = False,
    guardrail_enabled: bool | None = None,
    primary_model: str | None = None,
    fast_model: str | None = None,
    nano_model: str | None = None,
) -> dict:
    """Update user AI settings. `api_key` belongs to the selected provider; `openai_api_key`
    is always OpenAI's, which also powers document search whichever provider is selected."""
    current = await get_user_ai_settings(user_id, session)
    target = provider or current["provider"]
    if target not in PROVIDERS:
        raise UserSettingsError(f"Unknown provider '{target}'.")

    if provider and provider != current["provider"] and not (primary_model and fast_model and nano_model):
        raise UserSettingsError("Choose a main, fast and small model for the new provider.")

    new_base_url = current["base_url"]
    if PROVIDERS[target].needs_base_url:
        try:
            new_base_url = await validate_base_url(base_url if base_url is not None else current["base_url"])
        except ProviderError as exc:
            raise UserSettingsError(str(exc)) from exc

    updates: dict[str, str | None] = {}
    if clear_api_key:
        updates[target] = None
    if api_key and api_key.strip():
        updates[target] = _fernet().encrypt(api_key.strip().encode("utf-8")).decode("utf-8")
    if openai_api_key and openai_api_key.strip():
        updates["openai"] = _fernet().encrypt(openai_api_key.strip().encode("utf-8")).decode("utf-8")
    if updates:
        await SettingsRepository.update_api_keys(session, user_id, updates)

    if provider or base_url is not None:
        await SettingsRepository.update_provider(session, user_id, provider=target, base_url=new_base_url)

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


async def get_user_provider_key(user_id: str, provider: str, session: AsyncSession) -> str:
    ai_settings = await SettingsRepository.get_by_user_id(session, user_id)
    cipher = ((ai_settings.api_keys_encrypted or {}) if ai_settings else {}).get(provider)
    return _decrypt(cipher) if cipher else ""


async def get_user_openai_api_key(user_id: str, session: AsyncSession) -> str:
    """The user's OpenAI key if saved, whichever provider is selected for chat."""
    return await get_user_provider_key(user_id, "openai", session)


async def require_user_llm_credentials(user_id: str, session: AsyncSession) -> LLMCredentials:
    """Credentials for the user's selected provider (BYOK: never the server's key)."""
    ai_settings = await SettingsRepository.get_by_user_id(session, user_id)
    provider = ai_settings.provider if ai_settings and ai_settings.provider in PROVIDERS else "openai"
    spec = PROVIDERS[provider]
    base_url = ai_settings.base_url if ai_settings else None
    if spec.needs_base_url and not base_url:
        raise UserSettingsError("Add your provider's base URL in Settings before using chat.")
    if spec.needs_base_url:
        try:
            base_url = await validate_base_url(base_url)
        except ProviderError as exc:
            raise UserSettingsError(str(exc)) from exc
    api_key = await get_user_provider_key(user_id, provider, session)
    if not api_key and not spec.key_optional:
        raise UserSettingsError(f"An API key for {spec.label} is required. Add it in Settings before using chat.")
    return LLMCredentials(provider=provider, api_key=api_key, base_url=base_url)


async def require_user_embedding_key(user_id: str, session: AsyncSession) -> str:
    """Document search embeds text with OpenAI's model, whichever provider runs chat."""
    api_key = await get_user_openai_api_key(user_id, session)
    if api_key:
        return api_key
    raise UserSettingsError(
        "Reading documents needs an OpenAI API key, even if chat uses another provider. Add one in Settings."
    )


async def get_user_model_for_purpose(user_id: str, purpose: LLMPurpose, session: AsyncSession) -> str:
    """Get the appropriate model for a given purpose."""
    ai_settings = await get_user_ai_settings(user_id, session)
    if purpose == "fast":
        return ai_settings["fast_model"]
    if purpose == "nano":
        return ai_settings["nano_model"]
    return ai_settings["primary_model"]
