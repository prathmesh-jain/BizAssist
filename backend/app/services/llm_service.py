import logging
import re
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.language_models.chat_models import BaseChatModel
from app.config import get_settings
from app.services.llm_providers import LLMCredentials, build_chat_model
from app.services.user_settings_service import (
    LLMPurpose,
    get_user_model_for_purpose,
    require_user_llm_credentials,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# gpt-5, gpt-5-mini, gpt-5-nano (with optional date). Later 5.x models name their efforts differently.
_GPT5_MINIMAL_EFFORT = re.compile(r"^gpt-5(-mini|-nano)?(-\d{4}-\d{2}-\d{2})?$")


async def get_llm(
    model_name: str = None,
    user_id: str | None = None,
    purpose: LLMPurpose = "primary",
    temperature: float = 0,
    streaming: bool = False,
    max_retries: int = 3,
    session: AsyncSession = None,
    **kwargs
) -> BaseChatModel:
    """
    Get a chat model for the user's selected provider, with default settings and retry logic.

    Args:
        model_name: The name of the model to use (defaults to 4.1-mini).
        temperature: Temperature for the model (defaults to 0).
        streaming: Whether to enable streaming (defaults to False).
        max_retries: Number of retries for failed API calls (defaults to 3).
        session: Database session for user settings lookup.

    Returns:
        A configured LangChain chat model.
    """
    if user_id:
        # BYOK: user-scoped calls must always use the user's own key, never the server key.
        if session is None:
            # Graph nodes have no request session; open a short-lived one.
            from app.db.base import session_scope

            async with session_scope() as own_session:
                credentials = await require_user_llm_credentials(user_id, own_session)
                if model_name is None:
                    model_name = await get_user_model_for_purpose(user_id, purpose, own_session)
        else:
            credentials = await require_user_llm_credentials(user_id, session)
            if model_name is None:
                model_name = await get_user_model_for_purpose(user_id, purpose, session)
    else:
        credentials = LLMCredentials(provider="openai", api_key=settings.openai_api_key)
        if model_name is None:
            model_name = settings.primary_model

    # GPT-5 models reason by default, which took a planner call to 12s+. Routing-style work doesn't need it.
    if credentials.provider == "openai" and purpose in ("fast", "nano") and _GPT5_MINIMAL_EFFORT.match(model_name or ""):
        kwargs.setdefault("reasoning_effort", "minimal")

    logger.info(f"Initializing LLM: {model_name} (temp={temperature}, streaming={streaming}, retries={max_retries})")

    return build_chat_model(
        credentials, model_name, temperature=temperature, streaming=streaming, max_retries=max_retries, **kwargs,
    )
