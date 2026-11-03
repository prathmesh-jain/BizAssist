"""LLM providers users can choose from, and how to talk to each.

OpenAI, Gemini, OpenRouter and custom endpoints use the OpenAI-compatible API (differing
only in base URL); Anthropic uses its native client. Model names aren't hard-coded here:
they go stale as providers retire models, so the UI lists live ones from the provider.
"""
import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.config import get_settings

settings = get_settings()


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    base_url: str | None = None
    key_url: str | None = None
    key_placeholder: str = ""
    needs_base_url: bool = False
    key_optional: bool = False


PROVIDERS: dict[str, Provider] = {p.id: p for p in (
    Provider("openai", "OpenAI", key_url="https://platform.openai.com/api-keys", key_placeholder="sk-…"),
    Provider("anthropic", "Anthropic (Claude)", key_url="https://console.anthropic.com/settings/keys", key_placeholder="sk-ant-…"),
    Provider("gemini", "Google Gemini", base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
             key_url="https://aistudio.google.com/apikey", key_placeholder="AIza…"),
    Provider("openrouter", "OpenRouter", base_url="https://openrouter.ai/api/v1",
             key_url="https://openrouter.ai/keys", key_placeholder="sk-or-…"),
    Provider("custom", "Custom (OpenAI-compatible URL)", needs_base_url=True, key_optional=True,
             key_placeholder="Leave blank if your server needs no key"),
)}


@dataclass(frozen=True)
class LLMCredentials:
    provider: str
    api_key: str
    base_url: str | None = None


class ProviderError(RuntimeError):
    pass


def provider_catalog() -> list[dict]:
    return [
        {
            "id": p.id, "label": p.label, "key_url": p.key_url, "key_placeholder": p.key_placeholder,
            "needs_base_url": p.needs_base_url, "key_optional": p.key_optional,
        }
        for p in PROVIDERS.values()
    ]


def effective_base_url(provider: str, custom_base_url: str | None) -> str | None:
    return custom_base_url if PROVIDERS[provider].needs_base_url else PROVIDERS[provider].base_url


async def validate_base_url(url: str | None) -> str:
    """A custom endpoint is called from the server with the user's key, so it must not reach internal services."""
    value = (url or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ProviderError("Enter a full base URL, like https://api.example.com/v1.")
    if parsed.username or parsed.password:
        raise ProviderError("The base URL must not contain a username or password.")
    if settings.allow_private_llm_base_urls:
        return value  # local development, e.g. Ollama on localhost
    if parsed.scheme != "https":
        raise ProviderError("The base URL must use https.")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ProviderError(f"Could not find {parsed.hostname}.") from exc
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ProviderError(f"{parsed.hostname} is a private address, which isn't allowed.")
    return value


# Models found to reject `temperature`. Which ones do changes too often to list in advance.
_REJECTS_TEMPERATURE: set[str] = set()


def _rejected_temperature(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) in (400, 422) and "temperature" in str(exc).lower()


class _AdaptiveTemperature:
    """Retries once without `temperature` when a model refuses it, then stops sending it to that model."""

    def _temperature_key(self) -> str:
        return getattr(self, "model_name", None) or self.model

    def _get_request_payload(self, *args: Any, **kwargs: Any) -> dict:
        payload = super()._get_request_payload(*args, **kwargs)
        if self._temperature_key() in _REJECTS_TEMPERATURE:
            payload.pop("temperature", None)
        return payload

    async def _agenerate(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return await super()._agenerate(*args, **kwargs)
        except Exception as exc:
            if not _rejected_temperature(exc):
                raise
        _REJECTS_TEMPERATURE.add(self._temperature_key())
        return await super()._agenerate(*args, **kwargs)

    async def _astream(self, *args: Any, **kwargs: Any) -> Any:
        # The refusal arrives when the request is made, before any chunk has been yielded.
        try:
            async for chunk in super()._astream(*args, **kwargs):
                yield chunk
            return
        except Exception as exc:
            if not _rejected_temperature(exc):
                raise
        _REJECTS_TEMPERATURE.add(self._temperature_key())
        async for chunk in super()._astream(*args, **kwargs):
            yield chunk


class _OpenAICompatibleChat(_AdaptiveTemperature, ChatOpenAI):
    pass


def build_chat_model(
    credentials: LLMCredentials,
    model: str,
    *,
    temperature: float = 0,
    streaming: bool = False,
    max_retries: int = 3,
    **kwargs: Any,
) -> BaseChatModel:
    if credentials.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        class _AnthropicChat(_AdaptiveTemperature, ChatAnthropic):
            pass

        kwargs.setdefault("max_tokens", 4096)  # required by Anthropic's API
        return _AnthropicChat(
            model=model, api_key=credentials.api_key, temperature=temperature,
            streaming=streaming, max_retries=max_retries, **kwargs,
        )
    return _OpenAICompatibleChat(
        model=model,
        api_key=credentials.api_key or "not-needed",  # the client insists; keyless servers ignore it
        base_url=effective_base_url(credentials.provider, credentials.base_url),
        temperature=temperature,
        streaming=streaming,
        max_retries=max_retries,
        **kwargs,
    )


def supports_openai_strict_schema(llm: BaseChatModel) -> bool:
    """Strict JSON-schema output combined with tools is reliable only on OpenAI's own API."""
    return isinstance(llm, ChatOpenAI) and not llm.openai_api_base


def structured(llm: BaseChatModel, schema: type):
    """Structured output in the form this provider supports."""
    if isinstance(llm, ChatOpenAI) and llm.openai_api_base:
        return llm.with_structured_output(schema, method="function_calling")
    return llm.with_structured_output(schema)


def text_of(content: Any) -> str:
    """Text from a message: OpenAI-style providers send strings, Anthropic sends content blocks."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in ("text", "text_delta"):
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content)


async def list_models(credentials: LLMCredentials) -> list[str]:
    """Model ids the provider currently offers for this key."""
    if credentials.provider == "anthropic":
        url = "https://api.anthropic.com/v1/models"
        headers = {"x-api-key": credentials.api_key, "anthropic-version": "2023-06-01"}
        params: dict = {"limit": 100}
    else:
        base = effective_base_url(credentials.provider, credentials.base_url) or "https://api.openai.com/v1"
        url = f"{base.rstrip('/')}/models"
        headers = {"Authorization": f"Bearer {credentials.api_key}"} if credentials.api_key else {}
        params = {}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=headers, params=params)
    except httpx.HTTPError as exc:
        raise ProviderError(f"Could not reach the provider: {exc.__class__.__name__}") from exc
    if resp.status_code in (401, 403):
        raise ProviderError("The provider rejected this API key.")
    if resp.status_code >= 400:
        raise ProviderError(f"The provider returned HTTP {resp.status_code} when listing models.")
    try:
        items = resp.json().get("data") or resp.json().get("models") or []
        ids = [str(i.get("id") or i.get("name")).removeprefix("models/") for i in items if isinstance(i, dict)]
    except (ValueError, AttributeError) as exc:
        raise ProviderError("The provider's model list wasn't in the expected format.") from exc
    return sorted({i for i in ids if i and i != "None"})


async def test_connection(credentials: LLMCredentials, model: str) -> None:
    """One tiny real request: proves the key, URL and model work together. Raises on failure."""
    llm = build_chat_model(credentials, model, max_retries=0, timeout=30)
    try:
        await llm.ainvoke("Reply with the single word: ok")
    except Exception as exc:
        raise ProviderError(friendly_provider_error(exc)) from exc


def friendly_provider_error(exc: Exception) -> str:
    text = str(exc)
    low = text.lower()
    if "model_not_found" in low or "not_found" in low or "does not exist" in low or "has been deprecated" in low:
        return "That model isn't available for this key. Choose another."
    if "401" in low or "invalid_api_key" in low or "authentication" in low or "api key" in low:
        return "The provider rejected this API key."
    if "429" in low or "rate limit" in low or "quota" in low or "credit" in low:
        return "The provider says the rate limit or quota has been reached."
    return f"The provider returned an error: {text[:200]}"
