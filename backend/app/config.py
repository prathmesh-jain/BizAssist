from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # LLM — override any of these in .env to swap models
    openai_api_key: str = ""
    primary_model: str = "gpt-4.1-mini"    # chat, analytics, invoice
    fast_model: str = "gpt-4.1-mini"        # title gen, summarization
    nano_model: str = "gpt-4.1-nano"        # safety check only (cheapest)

    # Memory sliding-window — override in .env
    memory_window_size: int = 20    # total messages before summarization fires
    memory_overlap: float = 0.15    # fraction of the summarized chunk to keep raw (for continuity)

    # Database
    mongodb_uri: str = "mongodb://localhost:27017"
    db_name: str = "bizassist"

    # Auth (Firebase)
    firebase_project_id: str = ""

    firebase_type: str = ""
    firebase_private_key_id: str = ""
    firebase_private_key: str = ""
    firebase_client_email: str = ""
    firebase_client_id: str = ""
    firebase_auth_uri: str = ""
    firebase_token_uri: str = ""
    firebase_auth_provider_x509_cert_url: str = ""
    firebase_client_x509_cert_url: str = ""
    firebase_universe_domain: str = ""

    # Google Sheets (Custom OAuth)
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = ""
    # Used to encrypt persisted OAuth tokens at rest (Fernet key)
    google_oauth_token_encryption_key: str = ""

    # Vector store
    chroma_path: str = "./chroma_db"

    # CORS
    cors_origins: list[str] = ["http://localhost:5173"]

    # Guardrails
    use_guardrail: bool = False

    # Agent runtime
    agent_run_retries: int = 2

    # Temp storage cleanup (chat attachments)
    chat_tmp_ttl_seconds: int = 60 * 60 * 24  # 24h
    chat_tmp_sweep_interval_seconds: int = 60 * 15  # 15m

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
