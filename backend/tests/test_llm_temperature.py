"""Models that refuse `temperature` keep working, on every call path."""
import json

import httpx
import pytest

from app.services import llm_providers
from app.services.llm_providers import LLMCredentials, build_chat_model


def _picky_server(requests):
    """Answers like OpenAI's API, refusing any request that sets temperature."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if "temperature" in body:
            return httpx.Response(400, json={"error": {
                "message": "Unsupported value: 'temperature' does not support 0.0 with this model.",
                "type": "invalid_request_error", "param": "temperature", "code": "unsupported_value",
            }})
        if body.get("stream"):
            chunk = {"id": "c", "object": "chat.completion.chunk", "created": 1, "model": "m",
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n")
        return httpx.Response(200, json={"id": "c", "object": "chat.completion", "created": 1, "model": "m", "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.no_db
@pytest.mark.parametrize("streaming", [False, True])
async def test_models_that_refuse_temperature_still_work(monkeypatch, streaming):
    monkeypatch.setattr(llm_providers, "_REJECTS_TEMPERATURE", set())
    requests = []
    llm = build_chat_model(
        LLMCredentials("openai", "sk-test"), "picky-model", streaming=streaming, max_retries=0,
        http_async_client=_picky_server(requests),
    )

    assert (await llm.ainvoke("hi")).content == "ok"
    assert len(requests) == 2  # refused once, then accepted

    assert (await llm.ainvoke("again")).content == "ok"
    assert len(requests) == 3  # remembered, so no second refusal


@pytest.mark.no_db
async def test_other_bad_requests_are_not_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(400, json={"error": {"message": "Context length exceeded."}})

    llm = build_chat_model(
        LLMCredentials("openai", "sk-test"), "m", max_retries=0,
        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(Exception, match="Context length"):
        await llm.ainvoke("hi")
    assert len(calls) == 1
