from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import CurrentUser
from app.db.base import get_db_session
from app.models.settings import AISettingsPublic, AISettingsUpdate, ProviderCheck
from app.repositories import SettingsRepository
from app.services.llm_providers import (
    PROVIDERS, LLMCredentials, ProviderError, list_models, provider_catalog, test_connection, validate_base_url,
)
from app.services.user_settings_service import (
    UserSettingsError, get_user_ai_settings, get_user_provider_key, update_user_ai_settings,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/ai", response_model=AISettingsPublic)
async def get_ai_settings(user: CurrentUser, session = Depends(get_db_session, scope="function")):
    return AISettingsPublic(**(await get_user_ai_settings(user.user.id, session)))


@router.patch("/ai", response_model=AISettingsPublic)
async def patch_ai_settings(body: AISettingsUpdate, user: CurrentUser, session = Depends(get_db_session, scope="function")):
    try:
        updated = await update_user_ai_settings(
            user.user.id,
            session,
            provider=body.provider,
            base_url=body.base_url,
            api_key=body.api_key,
            openai_api_key=body.openai_api_key,
            clear_api_key=body.clear_api_key,
            guardrail_enabled=body.guardrail_enabled,
            primary_model=body.primary_model,
            fast_model=body.fast_model,
            nano_model=body.nano_model,
        )
    except UserSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AISettingsPublic(**updated)


async def _credentials_for_check(body: ProviderCheck, user_id: str, session) -> LLMCredentials:
    if body.provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{body.provider}'.")
    spec = PROVIDERS[body.provider]
    api_key = (body.api_key or "").strip() or await get_user_provider_key(user_id, body.provider, session)
    if not api_key and not spec.key_optional:
        raise HTTPException(status_code=400, detail=f"Enter an API key for {spec.label} first.")
    base_url = None
    if spec.needs_base_url:
        saved = await SettingsRepository.get_by_user_id(session, user_id)
        try:
            base_url = await validate_base_url(body.base_url or (saved.base_url if saved else None))
        except ProviderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LLMCredentials(provider=body.provider, api_key=api_key, base_url=base_url)


@router.get("/ai/providers")
async def get_providers(user: CurrentUser):
    return {"providers": provider_catalog()}


@router.post("/ai/models")
async def get_provider_models(body: ProviderCheck, user: CurrentUser, session = Depends(get_db_session, scope="function")):
    """Models the provider offers for this key, so the list never goes stale."""
    credentials = await _credentials_for_check(body, user.user.id, session)
    try:
        return {"models": await list_models(credentials)}
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ai/test")
async def test_provider(body: ProviderCheck, user: CurrentUser, session = Depends(get_db_session, scope="function")):
    """Send one tiny real request with this key, URL and model."""
    if not (body.model or "").strip():
        raise HTTPException(status_code=400, detail="Choose a model to test.")
    credentials = await _credentials_for_check(body, user.user.id, session)
    try:
        await test_connection(credentials, body.model.strip())
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}

