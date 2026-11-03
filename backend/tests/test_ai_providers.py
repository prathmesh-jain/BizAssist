"""Choosing an AI provider: settings, key handling, endpoint safety, and provider-neutral agent code."""
import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.services.llm_providers import (
    LLMCredentials, ProviderError, build_chat_model, list_models, provider_catalog,
    supports_openai_strict_schema, text_of, validate_base_url,
)

FOUR = {"primary_model": "m-1", "fast_model": "m-2", "nano_model": "m-3"}


# ---------- no database ----------

@pytest.mark.no_db
def test_catalog_lists_every_provider():
    assert {p["id"] for p in provider_catalog()} == {"openai", "anthropic", "gemini", "openrouter", "custom"}


@pytest.mark.no_db
@pytest.mark.parametrize("provider, base_url, expected", [
    ("openai", None, None),
    ("gemini", None, "https://generativelanguage.googleapis.com/v1beta/openai/"),
    ("openrouter", None, "https://openrouter.ai/api/v1"),
    ("custom", "https://llm.example.com/v1", "https://llm.example.com/v1"),
])
def test_openai_compatible_providers_use_the_right_endpoint(provider, base_url, expected):
    llm = build_chat_model(LLMCredentials(provider, "key", base_url), "some-model")
    assert (llm.openai_api_base or None) == expected
    assert supports_openai_strict_schema(llm) is (provider == "openai")


@pytest.mark.no_db
def test_anthropic_uses_its_native_client_and_keyless_custom_servers_work():
    from langchain_anthropic import ChatAnthropic

    llm = build_chat_model(LLMCredentials("anthropic", "key"), "claude-x")
    assert isinstance(llm, ChatAnthropic) and not supports_openai_strict_schema(llm)
    assert build_chat_model(LLMCredentials("custom", "", "http://x/v1"), "m").openai_api_key.get_secret_value() == "not-needed"


@pytest.mark.no_db
@pytest.mark.parametrize("url", [
    "http://example.com/v1", "ftp://example.com", "not a url", "", None,
    "https://user:pw@example.com/v1", "https://127.0.0.1/v1", "https://localhost/v1",
    "https://10.0.0.5/v1", "https://169.254.169.254/latest",
])
async def test_custom_endpoints_cannot_reach_internal_services(url):
    with pytest.raises(ProviderError):
        await validate_base_url(url)


@pytest.mark.no_db
async def test_private_endpoints_only_when_explicitly_allowed(monkeypatch):
    from app.services import llm_providers

    monkeypatch.setattr(llm_providers.settings, "allow_private_llm_base_urls", True)
    assert await validate_base_url("http://localhost:11434/v1/") == "http://localhost:11434/v1"


@pytest.mark.no_db
def test_text_is_read_from_any_provider_format():
    assert text_of("plain") == "plain"
    assert text_of(None) == ""
    assert text_of([{"type": "text", "text": "Hello "}, {"type": "tool_use", "id": "x"}, {"type": "text", "text": "there"}]) == "Hello there"


@pytest.mark.no_db
def test_conversations_have_the_shape_strict_providers_require():
    """Anthropic rejects a system message after the start of a conversation."""
    from langchain_anthropic.chat_models import _format_messages

    from app.agents.chat_agent import _with_system

    history = [
        SystemMessage(content="[Earlier Conversation Summary]\nThey sell chai."),
        HumanMessage(content="What did we discuss?"),
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "c1"}]),
        ToolMessage(content="{}", tool_call_id="c1"),
    ]
    messages = _with_system("PROMPT", history)
    assert [type(m).__name__ for m in messages] == ["SystemMessage", "HumanMessage", "AIMessage", "ToolMessage"]
    assert "PROMPT" in messages[0].content and "They sell chai." in messages[0].content
    system, formatted = _format_messages(messages, model="claude-test")
    assert "They sell chai." in str(system) and formatted[0]["role"] == "user"


@pytest.mark.no_db
async def test_planner_works_without_strict_schema(monkeypatch):
    from app.agents import planner_agent

    calls = {}

    class FakeLLM:
        def bind_tools(self, tools, tool_choice=None):
            calls["tools"] = [getattr(t, "name", getattr(t, "__name__", "")) for t in tools]
            calls["tool_choice"] = tool_choice
            return self

        async def ainvoke(self, messages):
            return AIMessage(content="", tool_calls=[{
                "name": "PlannerOutput", "id": "c1",
                "args": {"execution_query": "q", "execution_plan": "p", "execution_steps": ["one"]},
            }])

    async def fake_get_llm(**kwargs):
        return FakeLLM()

    monkeypatch.setattr(planner_agent, "get_llm", fake_get_llm)
    result = await planner_agent.planner_node({"user_id": "u", "organization_id": "o", "chat_id": "c", "messages": [], "execution_brief": "b"})
    assert "PlannerOutput" in calls["tools"] and calls["tool_choice"] == "any"
    assert result["execution_plan"] == "p" and result["execution_steps"] == ["one"] and result["active_agent"] == "executor"


@pytest.mark.no_db
async def test_model_lists_are_read_live_from_each_provider(monkeypatch):
    from app.services import llm_providers

    seen = {}

    def handler(request):
        seen["url"], seen["headers"] = str(request.url), request.headers
        if "generativelanguage" in str(request.url):
            return httpx.Response(200, json={"data": [{"id": "models/gemini-x"}, {"id": "models/gemini-a"}]})
        if request.headers.get("authorization") == "Bearer bad":
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}, {"id": "a"}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(llm_providers.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler)))

    assert await list_models(LLMCredentials("gemini", "k")) == ["gemini-a", "gemini-x"]
    assert await list_models(LLMCredentials("custom", "k", "https://llm.example.com/v1")) == ["a", "b"]
    assert seen["url"] == "https://llm.example.com/v1/models"
    await list_models(LLMCredentials("anthropic", "ant"))
    assert seen["url"].startswith("https://api.anthropic.com/v1/models") and seen["headers"]["x-api-key"] == "ant"
    with pytest.raises(ProviderError, match="rejected"):
        await list_models(LLMCredentials("openrouter", "bad"))


@pytest.mark.no_db
def test_calendar_change_event_only_for_successful_changes():
    import json

    from app.services.chat_service import calendar_change_event

    created = json.dumps({"ok": True, "created": True, "event": {"title": "Sync", "start": "2026-11-03T15:00:00+05:30", "meet_link": "https://meet"}})
    assert calendar_change_event("calendar_create_event", created) == {
        "action": "created", "title": "Sync", "start": "2026-11-03T15:00:00+05:30", "meet_link": "https://meet",
    }
    assert calendar_change_event("calendar_delete_event", json.dumps({"ok": True, "deleted": True}))["action"] == "deleted"
    assert calendar_change_event("calendar_create_event", json.dumps({"ok": False, "cancelled": True})) is None
    assert calendar_change_event("calendar_list_events", json.dumps({"ok": True})) is None
    assert calendar_change_event("calendar_create_event", "not json") is None


@pytest.mark.no_db
@pytest.mark.parametrize("reply, category", [
    ("out_of_scope|not a business request", "out_of_scope"),
    ("code_generation|asks for a script", "code_generation"),
    ("sql_queries|asks for SQL", "sql_queries"),
    ("something else", "out_of_scope"),
    ("", "out_of_scope"),
])
def test_guardrail_reads_the_category_and_never_defaults_to_code(reply, category):
    from app.agents.guardrail import _normalize_unsafe_reason

    assert _normalize_unsafe_reason(reply) == category


@pytest.mark.no_db
async def test_guardrail_refuses_only_on_an_explicit_verdict(monkeypatch):
    from app.agents import guardrail

    replies = []

    class FakeLLM:
        async def ainvoke(self, messages):
            return AIMessage(content=replies.pop(0))

    async def fake_get_llm(**kwargs):
        return FakeLLM()

    monkeypatch.setattr(guardrail, "get_llm", fake_get_llm)
    monkeypatch.setattr(guardrail.settings, "use_guardrail", True)
    state = {"user_id": "u", "messages": [HumanMessage(content="hi")]}
    for reply, safe in (("SAFE", True), ("unsure, maybe", True), ("UNSAFE|out_of_scope|essay", False)):
        replies.append(reply)
        assert (await guardrail.guardrail_node(state))["is_safe"] is safe


# ---------- settings API ----------

async def test_switching_providers_keeps_keys_and_requires_models(make_user, client_for):
    client = client_for(await make_user("uid-a", "a@acme.com"))

    start = (await client.get("/api/settings/ai")).json()
    assert start["provider"] == "openai" and start["chat_enabled"] is False

    saved = (await client.patch("/api/settings/ai", json={"openai_api_key": "sk-openai"})).json()
    assert saved["has_api_key"] and saved["has_embedding_key"]

    resp = await client.patch("/api/settings/ai", json={"provider": "anthropic", "api_key": "sk-ant"})
    assert resp.status_code == 400 and "Choose a main" in resp.json()["detail"]

    resp = await client.patch("/api/settings/ai", json={"provider": "anthropic", "api_key": "sk-ant", **FOUR})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["provider"] == "anthropic" and data["primary_model"] == "m-1"
    assert data["has_api_key"] and data["has_embedding_key"]  # the OpenAI key survives for documents
    assert data["saved_key_providers"] == ["anthropic", "openai"]

    cleared = (await client.patch("/api/settings/ai", json={"clear_api_key": True})).json()
    assert cleared["has_api_key"] is False and cleared["chat_enabled"] is False and cleared["has_embedding_key"] is True

    back = (await client.patch("/api/settings/ai", json={"provider": "openai", **FOUR})).json()
    assert back["has_api_key"] and back["chat_enabled"]

    assert (await client.patch("/api/settings/ai", json={"provider": "nope", **FOUR})).status_code == 400


async def test_get_llm_uses_the_selected_provider_never_the_server_key(make_user, client_for):
    from langchain_anthropic import ChatAnthropic

    from app.services.llm_service import get_llm
    from app.services.user_settings_service import UserSettingsError

    ctx = await make_user("uid-a", "a@acme.com")
    client = client_for(ctx)

    await client.patch("/api/settings/ai", json={"provider": "anthropic", **FOUR})
    with pytest.raises(UserSettingsError, match="Anthropic"):
        await get_llm(user_id=ctx.user.id)

    await client.patch("/api/settings/ai", json={"provider": "anthropic", "api_key": "sk-ant", **FOUR})
    llm = await get_llm(user_id=ctx.user.id, purpose="fast")
    assert isinstance(llm, ChatAnthropic) and llm.model == "m-2"

    resp = await client.patch("/api/settings/ai", json={"provider": "gemini", "api_key": "gem", **FOUR})
    assert resp.status_code == 200
    gemini = await get_llm(user_id=ctx.user.id)
    assert "generativelanguage" in gemini.openai_api_base and gemini.openai_api_key.get_secret_value() == "gem"


async def test_custom_endpoint_validation_and_keyless_chat(make_user, client_for, monkeypatch):
    from app.services import llm_providers

    ctx = await make_user("uid-a", "a@acme.com")
    client = client_for(ctx)

    bad = await client.patch("/api/settings/ai", json={"provider": "custom", "base_url": "https://127.0.0.1/v1", **FOUR})
    assert bad.status_code == 400 and "private" in bad.json()["detail"]
    assert (await client.patch("/api/settings/ai", json={"provider": "custom", **FOUR})).status_code == 400

    monkeypatch.setattr(llm_providers.settings, "allow_private_llm_base_urls", True)
    ok = await client.patch("/api/settings/ai", json={"provider": "custom", "base_url": "http://localhost:11434/v1", **FOUR})
    assert ok.status_code == 200 and ok.json()["chat_enabled"] is True and ok.json()["has_api_key"] is False


async def test_documents_need_an_openai_key_whichever_provider_runs_chat(make_user, client_for):
    from app.db.base import session_scope
    from app.services.user_settings_service import UserSettingsError, require_user_embedding_key

    ctx = await make_user("uid-a", "a@acme.com")
    await client_for(ctx).patch("/api/settings/ai", json={"provider": "anthropic", "api_key": "sk-ant", **FOUR})
    async with session_scope() as session:
        with pytest.raises(UserSettingsError, match="OpenAI"):
            await require_user_embedding_key(ctx.user.id, session)


async def test_check_endpoints_validate_input(make_user, client_for):
    client = client_for(await make_user("uid-a", "a@acme.com"))
    assert (await client.get("/api/settings/ai/providers")).status_code == 200
    assert (await client.post("/api/settings/ai/models", json={"provider": "nope"})).status_code == 400
    missing_key = await client.post("/api/settings/ai/models", json={"provider": "anthropic"})
    assert missing_key.status_code == 400 and "API key" in missing_key.json()["detail"]
    assert (await client.post("/api/settings/ai/test", json={"provider": "openai", "api_key": "x"})).status_code == 400
