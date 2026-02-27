import logging
from langchain_openai import ChatOpenAI
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

def get_llm(
    model_name: str = None,
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
    if model_name is None:
        model_name = "gpt-4.1-mini"
        
    logger.info(f"Initializing LLM: {model_name} (temp={temperature}, streaming={streaming}, retries={max_retries})")
    
    return ChatOpenAI(
        model=model_name,
        temperature=temperature,
        streaming=streaming,
        max_retries=max_retries,
        api_key=settings.openai_api_key,
        **kwargs
    )
