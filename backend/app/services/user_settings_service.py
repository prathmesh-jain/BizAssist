import logging
from typing import Literal

from cryptography.fernet import Fernet
from bson import ObjectId

from app.config import get_settings
from app.database import users_col

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


async def get_user_ai_settings(user_id: str) -> dict:
    doc = await users_col().find_one(
        {"_id": ObjectId(user_id)},
        projection={"ai_settings": 1},
    )
    ai = (doc or {}).get("ai_settings") or {}
    defaults = _default_models()
    encrypted_key = ai.get("openai_api_key_encrypted")
    return {
        "provider": "openai",
        "has_api_key": bool(encrypted_key),
        "chat_enabled": bool(encrypted_key),
        "guardrail_enabled": bool(ai.get("guardrail_enabled", settings.use_guardrail)),
        "primary_model": (ai.get("primary_model") or defaults["primary_model"]).strip(),
        "fast_model": (ai.get("fast_model") or defaults["fast_model"]).strip(),
        "nano_model": (ai.get("nano_model") or defaults["nano_model"]).strip(),
    }


async def update_user_ai_settings(
    user_id: str,
    *,
    openai_api_key: str | None = None,
    clear_api_key: bool = False,
    guardrail_enabled: bool | None = None,
    primary_model: str | None = None,
    fast_model: str | None = None,
    nano_model: str | None = None,
) -> dict:
    updates: dict[str, str] = {}
    unsets: dict[str, str] = {}

    if clear_api_key:
        unsets["ai_settings.openai_api_key_encrypted"] = ""

    if openai_api_key is not None:
        token = openai_api_key.strip()
        if token:
            updates["ai_settings.openai_api_key_encrypted"] = _fernet().encrypt(
                token.encode("utf-8")
            ).decode("utf-8")

    if guardrail_enabled is not None:
        updates["ai_settings.guardrail_enabled"] = bool(guardrail_enabled)

    for key, value in (
        ("ai_settings.primary_model", primary_model),
        ("ai_settings.fast_model", fast_model),
        ("ai_settings.nano_model", nano_model),
    ):
        if value is not None:
            cleaned = value.strip()
            if cleaned:
                updates[key] = cleaned

    update_doc: dict[str, dict] = {}
    if updates:
        update_doc["$set"] = updates
    if unsets:
        update_doc["$unset"] = unsets

    if update_doc:
        await users_col().update_one({"_id": ObjectId(user_id)}, update_doc)

    return await get_user_ai_settings(user_id)


async def get_user_openai_api_key(user_id: str) -> str:
    doc = await users_col().find_one(
        {"_id": ObjectId(user_id)},
        projection={"ai_settings.openai_api_key_encrypted": 1},
    )
    encrypted = ((doc or {}).get("ai_settings") or {}).get("openai_api_key_encrypted")
    if not encrypted:
        return ""

    try:
        return _fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        logger.exception("Failed to decrypt user OpenAI API key")
        raise UserSettingsError("Stored OpenAI API key could not be decrypted.") from exc


async def require_user_openai_api_key(user_id: str) -> str:
    api_key = await get_user_openai_api_key(user_id)
    if api_key:
        return api_key
    raise UserSettingsError(
        "OpenAI API key is required. Add it in Settings before using chat."
    )


async def get_user_model_for_purpose(user_id: str, purpose: LLMPurpose) -> str:
    ai_settings = await get_user_ai_settings(user_id)
    if purpose == "fast":
        return ai_settings["fast_model"]
    if purpose == "nano":
        return ai_settings["nano_model"]
    return ai_settings["primary_model"]
