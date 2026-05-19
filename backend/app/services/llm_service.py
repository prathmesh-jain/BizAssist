import logging
from langchain_openai import ChatOpenAI
from app.config import get_settings
from app.services.user_settings_service import (
    LLMPurpose,
    get_user_model_for_purpose,
    require_user_openai_api_key,
)

logger = logging.getLogger(__name__)
settings = get_settings()

async def get_llm(
    model_name: str = None,
    user_id: str | None = None,
    purpose: LLMPurpose = "primary",
    temperature: float = 0,
    streaming: bool = False,
    max_retries: int = 3,
    **kwargs
) -> ChatOpenAI:
    """
    Get a centralized ChatOpenAI instance with default settings and retry logic.
    
    Args:
        model_name: The name of the model to use (defaults to 4.1-mini).
        temperature: Temperature for the model (defaults to 0).
        streaming: Whether to enable streaming (defaults to False).
        max_retries: Number of retries for failed API calls (defaults to 3).
        
    Returns:
        ChatOpenAI: A configured LangChain LLM instance.
    """
    if user_id:
        api_key = await require_user_openai_api_key(user_id)
        if model_name is None:
            model_name = await get_user_model_for_purpose(user_id, purpose)
    else:
        api_key = settings.openai_api_key
        if model_name is None:
            model_name = settings.primary_model
        
    logger.info(f"Initializing LLM: {model_name} (temp={temperature}, streaming={streaming}, retries={max_retries})")
    
    return ChatOpenAI(
        model=model_name,
        temperature=temperature,
        streaming=streaming,
        max_retries=max_retries,
        api_key=api_key,
        **kwargs
    )
