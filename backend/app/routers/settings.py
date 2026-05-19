from fastapi import APIRouter

from app.dependencies import CurrentUser
from app.models.settings import AISettingsPublic, AISettingsUpdate
from app.services.user_settings_service import get_user_ai_settings, update_user_ai_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/ai", response_model=AISettingsPublic)
async def get_ai_settings(user: CurrentUser):
    return AISettingsPublic(**(await get_user_ai_settings(user.id)))


@router.patch("/ai", response_model=AISettingsPublic)
async def patch_ai_settings(body: AISettingsUpdate, user: CurrentUser):
    updated = await update_user_ai_settings(
        user.id,
        openai_api_key=body.openai_api_key,
        clear_api_key=body.clear_api_key,
        primary_model=body.primary_model,
        fast_model=body.fast_model,
        nano_model=body.nano_model,
    )
    return AISettingsPublic(**updated)
