"""Step 1 sign-off: PostgreSQL persistence, tenant isolation, BYOK, and the agent stream."""
import json

import pytest


async def _set_api_key(client, key="sk-test-not-a-real-key"):
    resp = await client.patch("/api/settings/ai", json={"openai_api_key": key})
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_api_key"] is True


def _sse_events(body: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in body.splitlines() if line.startswith("data: ")]


async def test_first_login_provisions_user_org_and_settings(make_user):
    ctx = await make_user("uid-a", "Owner@Example.com")

    assert ctx.user.email == "owner@example.com"
    assert ctx.role == "owner"
    assert ctx.organization.slug.startswith("owner-")

    again = await make_user("uid-a", "owner@example.com")
    assert again.user.id == ctx.user.id
    assert again.organization.id == ctx.organization.id


async def test_same_email_local_part_gets_separate_workspaces(make_user):
    a = await make_user("uid-a", "john@a.com")
    b = await make_user("uid-b", "john@b.com")

    assert a.organization.id != b.organization.id
    assert a.organization.slug != b.organization.slug


async def test_chat_crud_and_tenant_isolation(make_user, client_for):
    alice = client_for(await make_user("uid-a", "alice@a.com"))
    bob = client_for(await make_user("uid-b", "bob@b.com"))

    created = await alice.post("/api/chat", json={"title": "Q3 numbers"})
    assert created.status_code == 200, created.text
    chat_id = created.json()["id"]

    assert [c["id"] for c in (await alice.get("/api/chat")).json()] == [chat_id]
    assert (await bob.get("/api/chat")).json() == []

    # Another organization can't read, rename, message, or delete the chat.
    assert (await bob.get(f"/api/chat/{chat_id}/messages")).status_code == 404
    assert (await bob.patch(f"/api/chat/{chat_id}", json={"title": "x"})).status_code == 404
    assert (await bob.post(f"/api/chat/{chat_id}/message", json={"content": "hi"})).status_code == 404
    assert (await bob.delete(f"/api/chat/{chat_id}")).status_code == 404

    renamed = await alice.patch(f"/api/chat/{chat_id}", json={"title": "Renamed"})
    assert renamed.json()["title"] == "Renamed"

    messages = await alice.get(f"/api/chat/{chat_id}/messages")
    assert messages.status_code == 200
    assert messages.json() == {"messages": [], "has_more": False}


async def test_delete_chat_with_messages(make_user, client_for):
    from app.db.base import session_scope
    from app.repositories import MessageRepository

    alice = client_for(await make_user("uid-a", "alice@a.com"))
    chat_id = (await alice.post("/api/chat", json={})).json()["id"]
    async with session_scope() as session:
        await MessageRepository.create(session, chat_id=chat_id, user_id=None, role="assistant", content="hello")

    assert (await alice.delete(f"/api/chat/{chat_id}")).status_code == 200
    assert (await alice.get(f"/api/chat/{chat_id}/messages")).status_code == 404


async def test_interrupt_resolution_is_persisted(make_user, client_for):
    from app.db.base import session_scope
    from app.repositories import MessageRepository

    alice = client_for(await make_user("uid-a", "alice@a.com"))
    chat_id = (await alice.post("/api/chat", json={})).json()["id"]
    async with session_scope() as session:
        await MessageRepository.create(
            session, chat_id=chat_id, user_id=None, role="assistant", content="",
            interrupt={"id": "i1", "question": "Proceed?", "is_pending": True},
        )

    visible = (await alice.get(f"/api/chat/{chat_id}/messages")).json()["messages"]
    assert visible[0]["interrupt"]["is_pending"] is True

    async with session_scope() as session:
        assert await MessageRepository.mark_interrupts_resolved(session, chat_id, "accept") == 1

    # Resolved interrupts are hidden, which only works if the JSON update was actually written.
    assert (await alice.get(f"/api/chat/{chat_id}/messages")).json()["messages"] == []


async def test_byok_is_required_and_server_key_is_never_used(make_user, client_for):
    from app.services.llm_service import get_llm
    from app.services.user_settings_service import UserSettingsError

    ctx = await make_user("uid-a", "alice@a.com")
    alice = client_for(ctx)
    chat_id = (await alice.post("/api/chat", json={})).json()["id"]

    resp = await alice.post(f"/api/chat/{chat_id}/message", json={"content": "hi"})
    assert resp.status_code == 400
    assert "API key" in resp.json()["detail"]

    # Graph nodes call get_llm without a session; that must not fall back to the server key.
    with pytest.raises(UserSettingsError):
        await get_llm(user_id=ctx.user.id)

    await _set_api_key(alice)
    settings = (await alice.get("/api/settings/ai")).json()
    assert settings["has_api_key"] is True and settings["chat_enabled"] is True
    llm = await get_llm(user_id=ctx.user.id)
    assert llm.openai_api_key.get_secret_value() == "sk-test-not-a-real-key"


async def test_agent_stream_runs_graph_and_persists_user_message(make_user, client_for):
    """End to end through the router, LangGraph, and the Postgres checkpointer.

    OpenAI is unreachable in tests, so the run ends with an error event, but the
    graph, checkpointer, and message persistence are all exercised.
    """
    from app.agents.graph import close_checkpointer, get_compiled_graph, init_checkpointer

    await init_checkpointer()
    get_compiled_graph.cache_clear()
    try:
        ctx = await make_user("uid-a", "alice@a.com")
        alice = client_for(ctx)
        await _set_api_key(alice)
        chat_id = (await alice.post("/api/chat", json={})).json()["id"]

        resp = await alice.post(f"/api/chat/{chat_id}/message", json={"content": "What were Q3 sales?"})
        assert resp.status_code == 200
        events = _sse_events(resp.text)
        assert events[-1] == {"type": "done"}
        assert any(e["type"] == "error" for e in events), events

        messages = (await alice.get(f"/api/chat/{chat_id}/messages")).json()["messages"]
        assert [(m["role"], m["content"]) for m in messages] == [("user", "What were Q3 sales?")]

        state = await get_compiled_graph().aget_state(
            {"configurable": {"thread_id": f"{ctx.organization.id}_{chat_id}"}}
        )
        assert state.values["organization_id"] == ctx.organization.id
    finally:
        get_compiled_graph.cache_clear()
        await close_checkpointer()


async def test_provider_emails_are_not_revalidated(make_user, client_for):
    """Emails come from the verified token; a reserved TLD must not turn auth into a 500."""
    ctx = await make_user("uid-t", "owner@bizassist.test")
    me = await client_for(ctx).get("/api/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "owner@bizassist.test"


async def test_concurrent_first_requests_provision_one_account(make_user):
    """A new client sends several requests at once; they must share one user and workspace."""
    import asyncio

    from app.db.base import session_scope
    from app.repositories import UserRepository

    results = await asyncio.gather(*[make_user("uid-new", "new@acme.com") for _ in range(6)])

    assert len({r.user.id for r in results}) == 1
    assert len({r.organization.id for r in results}) == 1
    async with session_scope() as session:
        assert len(await UserRepository.list_memberships(session, results[0].user.id)) == 1


async def test_nameless_signup_gets_distinguishable_workspace(make_user):
    ctx = await make_user("uid-p", "priya@acme.com", name=None)
    assert ctx.organization.name == "priya's Workspace"
    assert ctx.user.full_name is None


async def test_new_users_get_the_configured_default_models(make_user, monkeypatch):
    from app.config import get_settings
    from app.db.base import session_scope
    from app.repositories import UserRepository

    monkeypatch.setattr(get_settings(), "fast_model", "configured-fast")
    monkeypatch.setattr(get_settings(), "nano_model", "configured-nano")
    ctx = await make_user("uid-m", "models@acme.com")
    async with session_scope() as session:
        stored = await UserRepository.get_ai_settings(session, ctx.user.id)
    assert (stored.fast_model, stored.nano_model) == ("configured-fast", "configured-nano")
