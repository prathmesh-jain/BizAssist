from pydantic import BaseModel, Field


class AISettingsPublic(BaseModel):
    provider: str = "openai"
    base_url: str | None = None
    has_api_key: bool
    chat_enabled: bool
    has_embedding_key: bool = False
    saved_key_providers: list[str] = []
    guardrail_enabled: bool
    primary_model: str
    fast_model: str
    nano_model: str


class AISettingsUpdate(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = Field(default=None, min_length=1)
    openai_api_key: str | None = Field(default=None, min_length=1)
    clear_api_key: bool = False
    guardrail_enabled: bool | None = None
    primary_model: str | None = Field(default=None, min_length=1)
    fast_model: str | None = Field(default=None, min_length=1)
    nano_model: str | None = Field(default=None, min_length=1)


class ProviderCheck(BaseModel):
    """A provider configuration to try. Blank fields fall back to what's saved."""
    provider: str
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None

