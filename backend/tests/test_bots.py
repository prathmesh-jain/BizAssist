"""WhatsApp and Telegram bots: setup, webhooks, the job queue, team and customer flows, gating,
delivery statuses and the inbox. Telegram, Meta and the AI model are faked."""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from langchain_core.messages import AIMessage

from app.agents import customer_agent
from app.agents.tool_policy import restrict, tool_names_for
from app.channels import formatting, telegram, whatsapp
from app.channels.base import Button
from app.services import bot_service, jobs

TG_TOKEN = "123456789:AAH-test-token-abcdefghijklmnop"
APP_SECRET = "meta-app-secret"


# ---------- pure helpers ----------

@pytest.mark.no_db
def test_formatting_for_each_app_and_splitting():
    md = "## Orders\n**Total:** 5 boxes, see [the sheet](https://x.test/s)\n- one\n- two [Source: price.pdf]"
    assert formatting.to_whatsapp(md) == "*Orders*\n*Total:* 5 boxes, see the sheet: https://x.test/s\n• one\n• two"
    tg = formatting.to_telegram_html("**a < b** and `x` [link](https://x.test)")
    assert tg == '<b>a &lt; b</b> and <code>x</code> <a href="https://x.test">link</a>'
    parts = formatting.split_message(("word " * 400 + "\n\n") * 4, 1000)
    assert all(len(p) <= 800 for p in parts) and len(parts) > 4


@pytest.mark.no_db
def test_parsing_webhooks_and_checking_signatures():
    update = {"update_id": 1, "message": {"message_id": 7, "date": 1700000000, "text": "hi",
                                          "chat": {"id": 42, "type": "private"},
                                          "from": {"id": 42, "first_name": "Meera", "username": "meera"}}}
    [msg] = telegram.parse(update).messages
    assert (msg.chat_id, msg.text, msg.name, msg.handle) == ("42", "hi", "Meera", "@meera")
    assert telegram.parse({"message": {**update["message"], "chat": {"id": -1, "type": "group"}}}).messages == []

    payload = _wa_payload("919820011223", "wamid.1", text="hello", statuses=[
        {"id": "wamid.out", "status": "failed", "errors": [{"code": 131047, "title": "Re-engagement message"}]}])
    parsed = whatsapp.parse(payload)["555"]
    assert parsed.messages[0].handle == "+919820011223" and parsed.messages[0].name == "Ravi"
    assert (parsed.statuses[0].status, parsed.statuses[0].error_code) == ("failed", "131047")

    raw = json.dumps(payload).encode()
    assert whatsapp.check_signature(raw, _sign(raw), APP_SECRET)
    assert not whatsapp.check_signature(raw, _sign(raw, "other"), APP_SECRET)
    assert not whatsapp.check_signature(raw, None, APP_SECRET)


@pytest.mark.no_db
def test_answers_to_approvals_and_questions():
    approval = {"interrupt_type": "accept_decline", "question": "Create it?"}
    assert bot_service._resume_value(approval, "", "approve") == (True, True)
    assert bot_service._resume_value(approval, "No", None) == (True, False)
    assert bot_service._resume_value(approval, "what time?", None) == (False, None)
    question = {"interrupt_type": "text_input", "options": ["Sales", "Ops", "HR", "Finance"]}
    assert bot_service._resume_value(question, "2", None) == (True, "Ops")
    text, buttons = bot_service._interrupt_text({**approval, "data": {"when": "Fri 10:00", "attendees": ["a@b.c"]}})
    assert "• When: Fri 10:00" in text and [b.id for b in buttons] == ["approve", "decline"]


@pytest.mark.no_db
def test_tool_policy_hides_tools_that_are_not_enabled():
    class T:
        def __init__(self, name):
            self.name = name

    tools = [T("calendar_create_event"), T("calendar_list_events"), T("sheets_update_values"), T("delegate_to_planner")]
    state = {"tool_policy": tool_names_for(["calendar_read"])}
    assert [t.name for t in restrict(state, tools)] == ["calendar_list_events", "delegate_to_planner"]
    assert restrict({}, tools) == tools  # the web app has no policy


# ---------- fakes ----------

def _sign(raw: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _wa_payload(sender, message_id, *, text=None, button=None, statuses=None, phone_id="555"):
    messages = []
    if text is not None:
        messages.append({"from": sender, "id": message_id, "timestamp": "1700000000", "type": "text", "text": {"body": text}})
    if button is not None:
        messages.append({"from": sender, "id": message_id, "timestamp": "1700000000", "type": "interactive",
                         "interactive": {"type": "button_reply", "button_reply": {"id": button[0], "title": button[1]}}})
    return {"object": "whatsapp_business_account", "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": phone_id, "display_phone_number": "+91 98200 00000"},
        "contacts": [{"wa_id": sender, "profile": {"name": "Ravi"}}], "messages": messages, "statuses": statuses or []}}]}]}


@pytest.fixture
def platforms(monkeypatch):
    """Fake Telegram and Meta APIs; every call is recorded."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "public_api_url", "https://api.biz.test")
    calls: list[tuple[str, dict]] = []
    state = {"wa_send_error": None, "msg": 100}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        if request.url.host == "api.telegram.org":
            method = request.url.path.rsplit("/", 1)[-1]
            calls.append((f"tg.{method}", body))
            if not request.url.path.startswith(f"/bot{TG_TOKEN}/"):
                return httpx.Response(401, json={"ok": False, "error_code": 401, "description": "Unauthorized"})
            if method == "getMe":
                return httpx.Response(200, json={"ok": True, "result": {"id": 123456789, "username": "shop_bot", "first_name": "Shop"}})
            if method == "getWebhookInfo":
                return httpx.Response(200, json={"ok": True, "result": {"url": calls_url(calls), "pending_update_count": 0}})
            if method == "sendMessage":
                state["msg"] += 1
                return httpx.Response(200, json={"ok": True, "result": {"message_id": state["msg"]}})
            return httpx.Response(200, json={"ok": True, "result": True})
        path = request.url.path.split("/", 2)[-1]
        calls.append((f"wa.{request.method} {path}", body))
        if request.headers.get("authorization") != "Bearer wa-token":
            return httpx.Response(401, json={"error": {"code": 190, "message": "Invalid OAuth access token."}})
        if path == "555" and request.method == "GET":
            return httpx.Response(200, json={"display_phone_number": "+91 98200 00000", "verified_name": "Shop", "id": "555"})
        if path == "555/messages":
            if body.get("status") == "read":
                return httpx.Response(200, json={"success": True})
            if state["wa_send_error"]:
                return httpx.Response(400, json={"error": {"code": state["wa_send_error"], "message": "nope"}})
            state["msg"] += 1
            return httpx.Response(200, json={"messages": [{"id": f"wamid.out{state['msg']}"}]})
        if path.endswith("subscribed_apps"):
            return httpx.Response(200, json={"success": True} if request.method == "POST" else {"data": [{"id": "app"}]})
        return httpx.Response(404, json={"error": {"code": 100, "message": "Unknown path"}})

    def calls_url(recorded):
        hooks = [b for name, b in recorded if name == "tg.setWebhook"]
        return hooks[-1]["url"] if hooks else ""

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(telegram, "http_client", client)
    monkeypatch.setattr(whatsapp, "http_client", client)
    return {"calls": calls, "state": state}


class _FakeLLM:
    """Scripted model: each ainvoke pops the next reply. `bind_tools` returns itself."""

    def __init__(self, script):
        self.script, self.calls = script, []

    def bind_tools(self, tools):
        self.tools = [t.name for t in tools]
        return self

    async def ainvoke(self, messages):
        self.calls.append(messages)
        item = self.script.pop(0)
        return item if isinstance(item, AIMessage) else AIMessage(content=item)


@pytest.fixture
def model(monkeypatch):
    script: list = []
    llm = _FakeLLM(script)

    async def fake_model(user_id, purpose):
        return llm

    monkeypatch.setattr(customer_agent, "_model", fake_model)
    return llm


@pytest.fixture
async def team(make_user):
    from app.db.base import session_scope
    from app.repositories import UserRepository

    owner = await make_user("uid-owner", "owner@shop.test", name="Asha Owner")
    viewer_home = await make_user("uid-viewer", "viewer@shop.test")
    async with session_scope() as session:
        await UserRepository.create_organization_member(session, owner.organization.id, viewer_home.user.id, role="viewer")
    viewer = await make_user("uid-viewer", "viewer@shop.test", organization_id=owner.organization.id)
    return owner, viewer


async def _connect(client, platform="telegram", audience="customer", settings=None):
    creds = {"token": TG_TOKEN} if platform == "telegram" else {
        "access_token": "wa-token", "phone_number_id": "555", "app_secret": APP_SECRET, "waba_id": "777"}
    resp = await client.post("/api/bots", json={"platform": platform, "audience": audience, "name": "Shop bot",
                                                "credentials": creds, "settings": settings or {}})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _tg_send(client, bot_id, secret, *, text=None, message_id=1, user_id=42, callback=None):
    if callback:
        update = {"update_id": message_id, "callback_query": {"id": f"cq{message_id}", "data": callback,
                  "from": {"id": user_id, "first_name": "Meera"},
                  "message": {"message_id": 9, "chat": {"id": user_id, "type": "private"}}}}
    else:
        update = {"update_id": message_id, "message": {"message_id": message_id, "date": 1700000000, "text": text,
                  "chat": {"id": user_id, "type": "private"}, "from": {"id": user_id, "first_name": "Meera"}}}
    return await client.post(f"/api/webhooks/telegram/{bot_id}", json=update,
                             headers={telegram.SECRET_HEADER: secret})


async def _secret(bot_id):
    from app.db.base import session_scope
    from app.db.models.bot import Bot

    async with session_scope() as session:
        return (await session.get(Bot, bot_id)).webhook_secret


def _sent(platforms, kind="tg.sendMessage"):
    return [body for name, body in platforms["calls"] if name == kind]


# ---------- setup ----------

async def test_connecting_a_telegram_bot_registers_the_webhook(team, client_for, platforms):
    owner, viewer = team
    o, v = client_for(owner), client_for(viewer)
    assert (await v.post("/api/bots", json={"platform": "telegram", "audience": "customer",
                                            "credentials": {"token": TG_TOKEN}})).status_code == 403
    bad = await o.post("/api/bots", json={"platform": "telegram", "audience": "customer", "credentials": {"token": "nope"}})
    assert bad.status_code == 400 and "BotFather" in bad.json()["detail"]

    data = await _connect(o)
    bot = data["bot"]
    assert bot["handle"] == "@shop_bot" and data["setup"]["webhook"] == "registered"
    hook = _sent(platforms, "tg.setWebhook")[-1]
    assert hook["url"] == f"https://api.biz.test/api/webhooks/telegram/{bot['id']}"
    assert hook["secret_token"] == await _secret(bot["id"])
    assert "token" not in json.dumps(bot["setup"])  # credentials never come back out

    again = await o.post("/api/bots", json={"platform": "telegram", "audience": "team", "credentials": {"token": TG_TOKEN}})
    assert again.status_code == 409

    checks = {c["id"]: c for c in (await o.get(f"/api/bots/{bot['id']}/health")).json()["checks"]}
    assert checks["credentials"]["ok"] and checks["webhook"]["ok"] and checks["inbound"]["ok"] is None

    # Viewers see team bots (to link themselves) but not customer bots or their conversations.
    assert (await v.get("/api/bots")).json()["bots"] == []
    assert (await v.get(f"/api/bots/{bot['id']}/conversations")).status_code == 403


async def test_customer_bot_answers_on_topic_and_blocks_the_rest(team, client_for, platforms, model):
    owner, _ = team
    o = client_for(owner)
    bot = (await _connect(o, settings={"about": "Open 10am-7pm. Boxes from ₹12 each."}))["bot"]
    secret = await _secret(bot["id"])

    assert (await _tg_send(o, bot["id"], "wrong", text="hi")).status_code == 401
    model.script += ["ON_TOPIC", "Our boxes start at ₹12 each."]
    assert (await _tg_send(o, bot["id"], secret, text="How much are boxes?", message_id=1)).status_code == 200
    assert (await _tg_send(o, bot["id"], secret, text="How much are boxes?", message_id=1)).status_code == 200  # retry
    assert await jobs.drain() == 1  # the duplicate wasn't queued
    assert _sent(platforms)[-1]["text"] == "Our boxes start at ₹12 each."
    assert "Boxes from ₹12" in model.calls[-1][0].content  # owner's info reached the prompt

    model.script += ["OFF_TOPIC"]
    await _tg_send(o, bot["id"], secret, text="Write me a python script", message_id=2)
    await jobs.drain()
    assert "only help with questions about" in _sent(platforms)[-1]["text"]
    assert len(model.calls) == 3  # the main model never ran for the off-topic message

    [conv] = (await o.get(f"/api/bots/{bot['id']}/conversations")).json()["conversations"]
    assert conv["contact_name"] == "Meera" and conv["problems"] == 1
    messages = (await o.get(f"/api/bots/{bot['id']}/conversations/{conv['id']}")).json()["messages"]
    assert [(m["direction"], m["status"]) for m in messages] == [
        ("in", "answered"), ("out", "sent"), ("in", "blocked"), ("out", "sent")]
    assert {"step": "guardrail", "verdict": "OFF_TOPIC"}.items() <= messages[2]["trace"][-1].items() or any(
        s.get("verdict") == "OFF_TOPIC" for s in messages[2]["trace"])
    assert messages[1]["reply_to_id"] == messages[0]["id"]


async def test_customer_handoff_pauses_the_bot_and_staff_can_reply(team, client_for, platforms, model):
    owner, _ = team
    o = client_for(owner)
    bot = (await _connect(o))["bot"]
    secret = await _secret(bot["id"])
    model.script += ["ON_TOPIC", AIMessage(content="", tool_calls=[{"id": "c1", "name": "hand_to_person",
                                                                    "args": {"reason": "wants a refund"}}]),
                     "Sure, someone from the team will reply here shortly."]
    await _tg_send(o, bot["id"], secret, text="I want to talk to a person", message_id=1)
    await jobs.drain()
    [conv] = (await o.get(f"/api/bots/{bot['id']}/conversations")).json()["conversations"]
    assert conv["mode"] == "human"

    await _tg_send(o, bot["id"], secret, text="hello?", message_id=2)
    await jobs.drain()
    assert len(_sent(platforms)) == 1  # the bot stayed quiet

    reply = await o.post(f"/api/bots/{bot['id']}/conversations/{conv['id']}/reply", json={"text": "Hi, Asha here."})
    assert reply.status_code == 200 and reply.json()["author"] == "staff"
    assert _sent(platforms)[-1]["text"] == "Hi, Asha here."
    await o.patch(f"/api/bots/{bot['id']}/conversations/{conv['id']}", json={"mode": "bot"})
    model.script += ["ON_TOPIC", "Anything else?"]
    await _tg_send(o, bot["id"], secret, text="thanks", message_id=3)
    await jobs.drain()
    assert _sent(platforms)[-1]["text"] == "Anything else?"


async def test_daily_cap_and_paused_bots_stop_replies(team, client_for, platforms, model):
    owner, _ = team
    o = client_for(owner)
    bot = (await _connect(o, settings={"daily_cap": 1}))["bot"]
    secret = await _secret(bot["id"])
    model.script += ["ON_TOPIC", "First answer."]
    await _tg_send(o, bot["id"], secret, text="first question here", message_id=1)
    await _tg_send(o, bot["id"], secret, text="second question here", message_id=2)
    await jobs.drain()
    assert [m["text"] for m in _sent(platforms)] == ["First answer."]
    listing = (await o.get("/api/bots")).json()["bots"][0]
    assert listing["last_error_explained"]["what"].startswith("The bot reached its daily message limit")

    await o.patch(f"/api/bots/{bot['id']}", json={"status": "paused", "settings": {"daily_cap": 50}})
    await _tg_send(o, bot["id"], secret, text="third question", message_id=3)
    await jobs.drain()
    assert len(_sent(platforms)) == 1


async def test_booking_only_accepts_offered_free_times(team, monkeypatch):
    from zoneinfo import ZoneInfo

    from app.services import google_calendar_service as gcal

    owner, _ = team
    created: list = []
    tz = ZoneInfo("Asia/Kolkata")
    tomorrow = (datetime.now(tz) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    while tomorrow.weekday() >= 5:
        tomorrow += timedelta(days=1)

    class FakeCalendar:
        def __init__(self, *_, **__):
            pass

        async def timezone_name(self):
            return "Asia/Kolkata"

        async def busy_intervals(self, start, end, calendars):
            return [(tomorrow.replace(hour=10), tomorrow.replace(hour=12))], []

        async def list_events(self, *_, **__):
            return []

        async def create_event(self, draft):
            created.append(draft)
            return {"meet_link": "https://meet.test/abc"}

    monkeypatch.setattr(gcal, "GoogleCalendar", FakeCalendar)
    ctx = customer_agent.CustomerContext(
        organization_id=owner.organization.id, owner_user_id=owner.user.id, platform="whatsapp",
        business_name="Shop", business_info="", settings={"booking": {"start": "10:00", "end": "14:00"}},
        contact_name="Ravi", contact_handle="+919820011223", conversation_id="c")
    tools = {t.name: t for t in customer_agent._tools(ctx, {"booking"}, {})}
    free = await tools["find_free_times"].ainvoke({"day": tomorrow.date().isoformat()})
    assert [t["start"][11:16] for t in free["times"]] == ["12:00", "12:30", "13:00", "13:30"]

    busy = await tools["book_time"].ainvoke({"start": tomorrow.replace(hour=10).isoformat(), "customer_name": "Ravi", "purpose": "Quote"})
    assert busy["ok"] is False and created == []
    after_hours = await tools["book_time"].ainvoke({"start": tomorrow.replace(hour=16).isoformat(), "customer_name": "Ravi", "purpose": "Quote"})
    assert after_hours["ok"] is False
    booked = await tools["book_time"].ainvoke({"start": free["times"][0]["start"], "customer_name": "Ravi", "purpose": "Quote"})
    assert booked == {"ok": True, "start": booked["start"], "meet_link": "https://meet.test/abc"}
    assert "+919820011223" in created[0].description and created[0].end - created[0].start == timedelta(minutes=30)


async def test_customer_bots_share_only_public_business_info():
    class Profile:
        status, name, website, location = "confirmed", "Sharma Packaging", "https://sharma.test", "Pune"
        description, products_services = "Corrugated boxes", ["Boxes", "Tape"]
        goals, challenges, existing_tools = "Raise prices 10%", "Cash flow", ["Tally"]

    name, info = customer_agent.public_business_info(Profile(), "Delivery in 2 days.")
    assert name == "Sharma Packaging" and "Boxes, Tape" in info and "Delivery in 2 days." in info
    assert "Raise prices" not in info and "Cash flow" not in info and "Tally" not in info


# ---------- WhatsApp ----------

async def test_whatsapp_verification_signatures_replies_and_delivery_status(team, client_for, platforms, model):
    owner, _ = team
    o = client_for(owner)
    data = await _connect(o, platform="whatsapp")
    bot, setup = data["bot"], data["setup"]
    assert setup["subscribed"] == "ok" and setup["webhook_url"].endswith(f"/api/webhooks/whatsapp/{bot['id']}")
    hook = f"/api/webhooks/whatsapp/{bot['id']}"

    bad = await o.get(hook, params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "123"})
    assert bad.status_code == 403
    ok = await o.get(hook, params={"hub.mode": "subscribe", "hub.verify_token": setup["verify_token"], "hub.challenge": "123"})
    assert ok.text == "123"

    raw = json.dumps(_wa_payload("919820011223", "wamid.in1", text="Do you deliver to Pune?")).encode()
    assert (await o.post(hook, content=raw, headers={whatsapp.SIGNATURE_HEADER: _sign(raw, "forged")})).status_code == 401
    model.script += ["ON_TOPIC", "Yes, **2-day** delivery to Pune."]
    assert (await o.post(hook, content=raw, headers={whatsapp.SIGNATURE_HEADER: _sign(raw),
                                                     "content-type": "application/json"})).status_code == 200
    await jobs.drain()
    sent = _sent(platforms, "wa.POST 555/messages")
    assert sent[0]["status"] == "read" and sent[0]["typing_indicator"] == {"type": "text"}
    assert sent[-1]["to"] == "919820011223" and sent[-1]["text"]["body"] == "Yes, *2-day* delivery to Pune."

    out_id = f"wamid.out{platforms['state']['msg']}"
    for status in ("delivered", "sent"):  # out of order: "sent" must not undo "delivered"
        raw = json.dumps(_wa_payload("919820011223", "x", statuses=[{"id": out_id, "status": status}])).encode()
        await o.post(hook, content=raw, headers={whatsapp.SIGNATURE_HEADER: _sign(raw)})
    [conv] = (await o.get(f"/api/bots/{bot['id']}/conversations")).json()["conversations"]
    messages = (await o.get(f"/api/bots/{bot['id']}/conversations/{conv['id']}")).json()["messages"]
    assert messages[-1]["status"] == "delivered"

    raw = json.dumps(_wa_payload("919820011223", "x", statuses=[
        {"id": out_id, "status": "failed", "errors": [{"code": 131047, "title": "Re-engagement message"}]}])).encode()
    await o.post(hook, content=raw, headers={whatsapp.SIGNATURE_HEADER: _sign(raw)})
    messages = (await o.get(f"/api/bots/{bot['id']}/conversations/{conv['id']}")).json()["messages"]
    assert messages[-1]["status"] == "failed" and "24 hours" in messages[-1]["explained"]["what"]

    # The 24-hour window: replies from the inbox are refused once it has passed.
    from app.db.base import session_scope
    from app.db.models.bot import BotConversation

    async with session_scope() as session:
        (await session.get(BotConversation, conv["id"])).last_inbound_at = datetime.now(timezone.utc) - timedelta(hours=25)
    refused = await o.post(f"/api/bots/{bot['id']}/conversations/{conv['id']}/reply", json={"text": "hello"})
    assert refused.status_code == 400 and "24 hours" in refused.json()["detail"]


async def test_whatsapp_send_failures_are_explained(team, client_for, platforms, model):
    owner, _ = team
    o = client_for(owner)
    bot = (await _connect(o, platform="whatsapp"))["bot"]
    platforms["state"]["wa_send_error"] = 131030
    model.script += ["ON_TOPIC", "Hello!"]
    raw = json.dumps(_wa_payload("919820011223", "wamid.in1", text="hello there")).encode()
    await o.post(f"/api/webhooks/whatsapp/{bot['id']}", content=raw, headers={whatsapp.SIGNATURE_HEADER: _sign(raw)})
    await jobs.drain()
    listing = (await o.get("/api/bots")).json()["bots"][0]
    assert "allowed recipients" in listing["last_error_explained"]["what"]


# ---------- team bots ----------

@pytest.fixture
def assistant(monkeypatch):
    """Fake the regular assistant run: records each call and replays scripted SSE events."""
    from app.services import chat_service

    runs: list[dict] = []
    script: list[list[dict]] = []

    async def fake_stream(user_message, chat_id, user_id, organization_id, **kwargs):
        runs.append({"message": user_message, "chat_id": chat_id, "user_id": user_id, **kwargs})
        for event in script.pop(0):
            yield f"data: {json.dumps(event)}\n\n"

    monkeypatch.setattr(chat_service, "stream_agent_response", fake_stream)
    return {"runs": runs, "script": script}


async def test_team_bot_links_members_gates_tools_and_handles_approvals(team, client_for, platforms, assistant):
    owner, viewer = team
    o, v = client_for(owner), client_for(viewer)
    bot = (await _connect(o, audience="team", settings={"tools": ["calendar_read", "calendar_write"]}))["bot"]
    secret = await _secret(bot["id"])

    await _tg_send(o, bot["id"], secret, text="what's on today?", message_id=1, user_id=77)
    await jobs.drain()
    assert "Link my account" in _sent(platforms)[-1]["text"] and assistant["runs"] == []

    # The viewer sees the team bot, gets a code, and sends it from Telegram.
    assert [b["id"] for b in (await v.get("/api/bots")).json()["bots"]] == [bot["id"]]
    code = (await v.post(f"/api/bots/{bot['id']}/link-code")).json()
    assert code["chat_link"] == f"https://t.me/shop_bot?start=link_{code['code']}"
    await _tg_send(o, bot["id"], secret, text=f"/start link_{code['code']}", message_id=2, user_id=77)
    await jobs.drain()
    assert "You're linked" in _sent(platforms)[-1]["text"]
    assert (await v.get("/api/bots")).json()["bots"][0]["linked"] is True

    assistant["script"].append([
        {"type": "tool_start", "name": "calendar_create_event"},
        {"type": "interrupt", "content": {"id": "i1", "question": "Create “Supplier call” on Fri?",
                                          "interrupt_type": "accept_decline", "data": {"when": "Fri 10:00"}}},
    ])
    await _tg_send(o, bot["id"], secret, text="book a supplier call friday 10am", message_id=3, user_id=77)
    await jobs.drain()
    run = assistant["runs"][-1]
    assert run["user_id"] == viewer.user.id and run["role"] == "viewer"
    assert set(run["channel"]["tool_policy"]) == {"calendar_now", "calendar_list_events", "calendar_find_free_slots",
                                                  "calendar_create_event", "calendar_update_event", "calendar_delete_event"}
    assert run["channel"]["strict_guardrail"] is True
    last = _sent(platforms)[-1]
    assert "Supplier call" in last["text"] and "Fri 10:00" in last["text"]
    assert [b[0]["callback_data"] for b in last["reply_markup"]["inline_keyboard"]] == ["approve", "decline"]

    assistant["script"].append([{"type": "token", "content": "Booked: Supplier call, Fri 10:00."}])
    await _tg_send(o, bot["id"], secret, callback="approve", message_id=4, user_id=77)
    await jobs.drain()
    resumed = assistant["runs"][-1]
    assert resumed["is_resume"] is True and resumed["resume_value"] is True and resumed["message"] is None
    assert resumed["chat_id"] == run["chat_id"]  # same BizAssist chat, visible in the web app too
    assert _sent(platforms)[-1]["text"] == "Booked: Supplier call, Fri 10:00."

    # Removed from the organization: the link stops working.
    from app.db.base import session_scope
    from app.repositories.membership_repository import MembershipRepository

    async with session_scope() as session:
        await session.delete(await MembershipRepository.get_member(session, owner.organization.id, viewer.user.id))
    await _tg_send(o, bot["id"], secret, text="what's on today?", message_id=5, user_id=77)
    await jobs.drain()
    assert "Link my account" in _sent(platforms)[-1]["text"] and len(assistant["runs"]) == 2


async def test_test_messages_run_the_bot_without_sending(team, client_for, platforms, model):
    owner, _ = team
    o = client_for(owner)
    bot = (await _connect(o))["bot"]
    model.script += ["ON_TOPIC", "We open at 10."]
    result = (await o.post(f"/api/bots/{bot['id']}/test", json={"text": "When do you open?"})).json()
    assert [m["text"] for m in result["messages"]] == ["When do you open?", "We open at 10."]
    assert result["conversation"]["is_test"] is True
    assert _sent(platforms) == []
    stats = (await o.get("/api/bots")).json()["bots"][0]["stats"]
    assert stats["conversations"] == 0  # tests don't count as real conversations


async def test_jobs_retry_with_backoff_then_fail(db_engine):
    from app.db.base import session_scope
    from app.db.models.bot import Job

    attempts = []

    @jobs.handler("test.flaky")
    async def flaky(payload):
        attempts.append(payload)
        raise RuntimeError("boom")

    async with session_scope() as session:
        job = await jobs.enqueue(session, "test.flaky", {"n": 1}, max_attempts=2)
        job_id = job.id
    assert await jobs.run_due_jobs() == 1
    async with session_scope() as session:
        row = await session.get(Job, job_id)
        assert row.status == "queued" and "boom" in row.last_error and row.run_after > datetime.now(timezone.utc)
        row.run_after = datetime.now(timezone.utc)
    await jobs.run_due_jobs()
    async with session_scope() as session:
        assert (await session.get(Job, job_id)).status == "failed"
    assert len(attempts) == 2


@pytest.mark.no_db
def test_real_tool_builders_respect_the_policy():
    from app.agents.tooling import get_chat_local_tools, get_planner_tools

    base = {"user_id": "u", "chat_id": "c", "organization_id": "o", "role": "member",
            "messages": [], "chat_tool_ids": ["calendar_list_events", "calendar_create_event", "sheets_read_range"]}
    open_names = {t.name for t in get_chat_local_tools(base)}
    assert {"calendar_create_event", "sheets_read_range", "remember", "rag_retrieve"} <= open_names

    gated = {**base, "tool_policy": tool_names_for(["calendar_read"])}
    names = {t.name for t in get_chat_local_tools(gated)}
    assert "calendar_list_events" in names and "delegate_to_planner" in names
    assert not names & {"calendar_create_event", "sheets_read_range", "remember", "rag_retrieve", "list_documents"}
    assert {t.name for t in get_planner_tools(gated)} <= {"request_clarification", "search_available_tools"}
