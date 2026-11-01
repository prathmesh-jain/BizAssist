"""Google Calendar: scheduling helpers, OAuth/connection per user, and agent tools with approval.

Google is replaced by an in-memory fake served through httpx.MockTransport.
"""
import json
from datetime import datetime, time, timedelta
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.services.google_calendar_service import (
    CalendarError, EventDraft, find_free_slots, meet_link, parse_when, simplify_event,
)

IST = ZoneInfo("Asia/Kolkata")


# ---------- pure helpers ----------

@pytest.mark.no_db
def test_parse_when_uses_user_timezone_for_naive_values():
    assert parse_when("2026-11-03T15:00", IST) == datetime(2026, 11, 3, 15, 0, tzinfo=IST)
    assert parse_when("2026-11-03", IST) == datetime(2026, 11, 3, 0, 0, tzinfo=IST)
    assert parse_when("2026-11-03T09:30:00Z", IST).utcoffset() == timedelta(0)
    with pytest.raises(CalendarError):
        parse_when("tomorrow", IST)


@pytest.mark.no_db
def test_find_free_slots_respects_busy_time_working_hours_and_weekends():
    monday = datetime(2026, 11, 2, 8, 0, tzinfo=IST)  # a Monday
    busy = [
        (datetime(2026, 11, 2, 9, 0, tzinfo=IST), datetime(2026, 11, 2, 10, 30, tzinfo=IST)),
        (datetime(2026, 11, 2, 11, 0, tzinfo=IST), datetime(2026, 11, 2, 17, 30, tzinfo=IST)),
    ]
    slots = find_free_slots(
        busy, window_start=monday, window_end=monday + timedelta(days=6), duration=timedelta(minutes=60), tz=IST, limit=3,
    )
    # 10:30-11:00 is too short and 17:30-18:00 too; next day starts at 09:00.
    assert slots[0] == (datetime(2026, 11, 3, 9, 0, tzinfo=IST), datetime(2026, 11, 3, 10, 0, tzinfo=IST))
    friday_evening = datetime(2026, 11, 6, 17, 45, tzinfo=IST)
    weekend = find_free_slots([], window_start=friday_evening, window_end=friday_evening + timedelta(days=3),
                              duration=timedelta(minutes=30), tz=IST, limit=1)
    assert weekend[0][0] == datetime(2026, 11, 9, 9, 0, tzinfo=IST)  # skips Sat/Sun
    odd_start = datetime(2026, 11, 3, 9, 7, tzinfo=IST)
    aligned = find_free_slots([], window_start=odd_start, window_end=odd_start + timedelta(hours=2),
                              duration=timedelta(minutes=30), tz=IST, limit=1, work_start=time(9))
    assert aligned[0][0] == datetime(2026, 11, 3, 9, 30, tzinfo=IST)


@pytest.mark.no_db
def test_event_draft_body_validation_and_idempotency():
    start = datetime(2026, 11, 3, 15, 0, tzinfo=IST)
    draft = EventDraft(title="Supplier review", start=start, end=start + timedelta(minutes=45), timezone="Asia/Kolkata",
                       attendees=["rahul@acme.com"], add_meet=True, reminder_minutes=[2880, 30, 30],
                       recurrence=["RRULE:FREQ=WEEKLY;BYDAY=TU"])
    draft.validate()
    body = draft.to_body("user-1")
    assert body["conferenceData"]["createRequest"]["conferenceSolutionKey"] == {"type": "hangoutsMeet"}
    assert body["reminders"] == {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}, {"method": "popup", "minutes": 2880}]}
    assert body["id"] == draft.to_body("user-1")["id"] and set(body["id"]) <= set("0123456789abcdefghijklmnopqrstuv")
    assert body["id"] != draft.to_body("user-2")["id"]
    for bad in (
        EventDraft(title="", start=start, end=start + timedelta(hours=1), timezone="UTC"),
        EventDraft(title="x", start=start, end=start, timezone="UTC"),
        EventDraft(title="x", start=start, end=start + timedelta(hours=1), timezone="UTC", attendees=["rahul"]),
        EventDraft(title="x", start=start, end=start + timedelta(hours=1), timezone="UTC", recurrence=["weekly"]),
    ):
        with pytest.raises(CalendarError):
            bad.validate()


@pytest.mark.no_db
def test_meet_link_only_when_google_created_it():
    assert meet_link({"conferenceData": {"createRequest": {"status": {"statusCode": "pending"}}}}) is None
    assert meet_link({"hangoutLink": "https://meet.google.com/abc"}) == "https://meet.google.com/abc"
    simple = simplify_event({"id": "e1", "summary": "Standup", "start": {"date": "2026-11-03"}, "end": {"date": "2026-11-04"}})
    assert simple["all_day"] is True and simple["meet_link"] is None


# ---------- fake Google ----------

class FakeGoogle:
    def __init__(self, *, meet_pending=False):
        self.events: dict[str, dict] = {}
        self.meet_pending = meet_pending
        self.requests: list[tuple[str, str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        body = json.loads(request.content) if request.content else {}
        self.requests.append((request.method, url.path, params))
        path = url.path.removeprefix("/calendar/v3")
        if path == "/users/me/settings/timezone":
            return httpx.Response(200, json={"value": "Asia/Kolkata"})
        if path == "/calendars/primary" and request.method == "GET":
            return httpx.Response(200, json={"id": "owner@acme.com"})
        if path == "/freeBusy":
            cals = {}
            for item in body["items"]:
                if item["id"] == "primary":
                    cals["primary"] = {"busy": [{"start": e["start"]["dateTime"], "end": e["end"]["dateTime"]} for e in self.events.values()]}
                else:
                    cals[item["id"]] = {"errors": [{"reason": "notFound"}]}
            return httpx.Response(200, json={"calendars": cals})
        if path == "/calendars/primary/events" and request.method == "GET":
            lo = datetime.fromisoformat(params["timeMin"].replace("Z", "+00:00"))
            hi = datetime.fromisoformat(params["timeMax"].replace("Z", "+00:00"))
            items = [e for e in self.events.values()
                     if datetime.fromisoformat(e["start"]["dateTime"]) < hi and lo < datetime.fromisoformat(e["end"]["dateTime"])]
            return httpx.Response(200, json={"items": items})
        if path == "/calendars/primary/events" and request.method == "POST":
            if body["id"] in self.events:
                return httpx.Response(409, json={"error": {"message": "The requested identifier already exists."}})
            event = {**body, "status": "confirmed", "htmlLink": f"https://calendar.example/{body['id']}"}
            if "conferenceData" in body and params.get("conferenceDataVersion") == "1":
                if self.meet_pending:
                    event["conferenceData"] = {"createRequest": {**body["conferenceData"]["createRequest"], "status": {"statusCode": "pending"}}}
                else:
                    event["hangoutLink"] = "https://meet.google.com/xyz-abcd-efg"
            self.events[body["id"]] = event
            return httpx.Response(200, json=event)
        if path.startswith("/calendars/primary/events/"):
            event_id = path.rsplit("/", 1)[1]
            if event_id not in self.events:
                return httpx.Response(404, json={"error": {"message": "Not Found"}})
            if request.method == "GET":
                return httpx.Response(200, json=self.events[event_id])
            if request.method == "PATCH":
                self.events[event_id].update(body)
                return httpx.Response(200, json=self.events[event_id])
            if request.method == "DELETE":
                del self.events[event_id]
                return httpx.Response(204)
        return httpx.Response(404, json={"error": {"message": f"unhandled {request.method} {path}"}})


@pytest.fixture
def google(monkeypatch):
    """Route Calendar API + token exchange to the fake."""
    from app.services import google_calendar_service, google_oauth

    fake = FakeGoogle()
    real_client = httpx.AsyncClient
    monkeypatch.setattr(google_calendar_service.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(fake.handler)))

    async def exchange(code):
        return {"access_token": f"access-{code}", "refresh_token": f"refresh-{code}", "expires_in": 3600}

    monkeypatch.setattr(google_oauth, "exchange_code_for_token", exchange)
    monkeypatch.setattr(google_oauth.settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(google_oauth.settings, "google_oauth_redirect_uri", "http://localhost:5173/oauth-callback")
    from cryptography.fernet import Fernet
    monkeypatch.setattr(google_oauth.settings, "google_oauth_token_encryption_key", Fernet.generate_key().decode())
    return fake


async def _connect(client):
    """Run connect + callback for the client's user; returns the callback payload."""
    url = (await client.post("/api/integrations/google-calendar/connect")).json()["auth_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    resp = await client.post("/api/integrations/google/callback", json={"code": "c1", "state": state})
    assert resp.status_code == 200, resp.text
    return resp.json(), url


@pytest.fixture
def approvals(monkeypatch):
    from app.tools import google_calendar_tools

    asked: list[tuple[str, dict]] = []
    answers: list[bool] = []

    def fake_approval(question, details):
        asked.append((question, details))
        return answers.pop(0) if answers else True

    monkeypatch.setattr(google_calendar_tools, "request_approval", fake_approval)
    return asked, answers


# ---------- OAuth + connections ----------

async def test_calendar_connection_is_per_user_and_routed_by_state(make_user, client_for, google):
    from app.db.base import session_scope
    from app.repositories import UserRepository

    owner_ctx = await make_user("uid-o", "owner@acme.com")
    personal = await make_user("uid-v", "viewer@acme.com")
    async with session_scope() as session:
        await UserRepository.create_organization_member(session, owner_ctx.organization.id, personal.user.id, role="viewer")
    viewer_ctx = await make_user("uid-v", "viewer@acme.com", organization_id=owner_ctx.organization.id)
    owner, viewer = client_for(owner_ctx), client_for(viewer_ctx)

    assert (await viewer.get("/api/integrations/google-calendar/status")).json() == {"connected": False}
    result, url = await _connect(viewer)  # even viewers can connect their own calendar
    assert "calendar.events" in parse_qs(urlparse(url).query)["scope"][0]
    assert result == {"integration": "google_calendar", "connected": True, "timezone": "Asia/Kolkata", "email": "owner@acme.com"}
    await _connect(owner)

    assert (await viewer.get("/api/integrations/google-calendar/status")).json()["connected"] is True
    assert (await owner.delete("/api/integrations/google-calendar")).json()["removed"] is True
    assert (await owner.get("/api/integrations/google-calendar/status")).json() == {"connected": False}
    assert (await viewer.get("/api/integrations/google-calendar/status")).json()["connected"] is True

    # A state is single-use and bound to the integration that issued it.
    state = parse_qs(urlparse(url).query)["state"][0]
    assert (await viewer.post("/api/integrations/google/callback", json={"code": "c2", "state": state})).status_code == 400
    sheets_url = (await owner.post("/api/integrations/google-sheets/connect", json={})).json()["auth_url"]
    sheets_state = parse_qs(urlparse(sheets_url).query)["state"][0]
    assert (await viewer.post("/api/integrations/google/callback", json={"code": "c3", "state": sheets_state})).status_code == 400


# ---------- tools ----------

def _tools(ctx):
    from app.tools.google_calendar_tools import get_calendar_tools

    return {t.name: t for t in get_calendar_tools(user_id=ctx.user.id, organization_id=ctx.organization.id)}


async def test_tools_report_not_connected(make_user, google):
    ctx = await make_user("uid-o", "owner@acme.com")
    out = await _tools(ctx)["calendar_list_events"].ainvoke({})
    assert out["ok"] is False and "not connected" in out["error"]


async def test_create_event_needs_approval_and_returns_confirmed_meet_link(make_user, client_for, google, approvals):
    asked, answers = approvals
    ctx = await make_user("uid-o", "owner@acme.com")
    await _connect(client_for(ctx))
    tools = _tools(ctx)

    now = await tools["calendar_now"].ainvoke({})
    assert now["timezone"] == "Asia/Kolkata"

    args = {"title": "Call with Rahul", "start": "2026-11-03T15:00", "duration_minutes": 30,
            "attendees": ["rahul@acme.com"], "add_google_meet": True}
    answers.append(False)
    declined = await tools["calendar_create_event"].ainvoke(args)
    assert declined["cancelled"] is True and google.events == {}

    created = await tools["calendar_create_event"].ainvoke(args)
    assert created["ok"] and created["event"]["meet_link"] == "https://meet.google.com/xyz-abcd-efg"
    question, details = asked[-1]
    assert "Call with Rahul" in question and details["attendees"] == ["rahul@acme.com"] and details["google_meet"] is True
    event = next(iter(google.events.values()))
    assert event["start"] == {"dateTime": "2026-11-03T15:00:00+05:30", "timeZone": "Asia/Kolkata"}
    invite = [r for r in google.requests if r[0] == "POST" and r[1].endswith("/events")][-1]
    assert invite[2]["sendUpdates"] == "all" and invite[2]["conferenceDataVersion"] == "1"

    # Retrying the same create is idempotent (Google answers 409 for the same event id).
    again = await tools["calendar_create_event"].ainvoke(args)
    assert again["ok"] and len(google.events) == 1

    # A clashing event is flagged in the approval request.
    await tools["calendar_create_event"].ainvoke({"title": "Overlap", "start": "2026-11-03T15:15", "duration_minutes": 30})
    assert "overlaps 1 existing event" in asked[-1][0] and asked[-1][1]["conflicts"]


async def test_meet_link_is_not_invented_while_google_is_still_creating_it(make_user, client_for, google, approvals, monkeypatch):
    import asyncio

    async def no_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    google.meet_pending = True
    ctx = await make_user("uid-o", "owner@acme.com")
    await _connect(client_for(ctx))
    out = await _tools(ctx)["calendar_create_event"].ainvoke(
        {"title": "Customer demo", "start": "2026-11-04T11:00", "add_google_meet": True})
    assert out["ok"] and out["event"]["meet_link"] is None and "Meet link" in out["warning"]


async def test_free_slots_update_and_delete(make_user, client_for, google, approvals):
    asked, answers = approvals
    ctx = await make_user("uid-o", "owner@acme.com")
    await _connect(client_for(ctx))
    tools = _tools(ctx)
    created = await tools["calendar_create_event"].ainvoke(
        {"title": "4 PM sync", "start": "2099-11-02T16:00", "duration_minutes": 60})  # a Monday
    event_id = created["event"]["id"]

    slots = await tools["calendar_find_free_slots"].ainvoke({
        "duration_minutes": 60, "start": "2099-11-02T15:00", "end": "2099-11-02T18:00", "attendees": ["sales@acme.com"]})
    assert [s["start"] for s in slots["slots"]] == ["2099-11-02T15:00+05:30", "2099-11-02T17:00+05:30"]
    assert slots["unknown_availability"] == ["sales@acme.com"]

    moved = await tools["calendar_update_event"].ainvoke({"event_id": event_id, "start": "2099-11-06T16:00"})
    assert moved["ok"] and moved["event"]["start"].startswith("2099-11-06T16:00")
    assert moved["event"]["end"].startswith("2099-11-06T17:00")  # kept its one-hour length
    assert "Update" in asked[-1][0] and "new_time" in asked[-1][1]

    answers.append(False)
    kept = await tools["calendar_delete_event"].ainvoke({"event_id": event_id})
    assert kept["cancelled"] and event_id in google.events
    gone = await tools["calendar_delete_event"].ainvoke({"event_id": event_id})
    assert gone["deleted"] and event_id not in google.events
