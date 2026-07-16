from pydantic import BaseModel, Field


class AISettingsPublic(BaseModel):
    provider: str = "openai"
    has_api_key: bool
    chat_enabled: bool
    guardrail_enabled: bool
    primary_model: str
    fast_model: str
    nano_model: str


class AISettingsUpdate(BaseModel):
    openai_api_key: str | None = Field(default=None, min_length=1)
    clear_api_key: bool = False
    guardrail_enabled: bool | None = None
    primary_model: str | None = Field(default=None, min_length=1)
    fast_model: str | None = Field(default=None, min_length=1)
    nano_model: str | None = Field(default=None, min_length=1)
