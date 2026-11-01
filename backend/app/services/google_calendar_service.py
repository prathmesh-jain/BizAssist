"""Google Calendar (and Meet links via Calendar events) for one member.

A Calendar connection belongs to the user who connected it (owner_scope "user"), unlike
the organization-wide Sheets connection. All times are timezone-aware; naive input is
interpreted in the user's calendar timezone.
"""
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import OAuthConnectionRepository, OAuthStateRepository
from app.services import google_oauth
from app.services.google_oauth import GoogleOAuthError

logger = logging.getLogger(__name__)

PROVIDER = "google_calendar"
INTEGRATION = "google_calendar"
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",    # create/update/delete events (incl. Meet)
    "https://www.googleapis.com/auth/calendar.readonly",  # list events, free/busy, timezone setting
    "openid",
    "email",
]
API = "https://www.googleapis.com/calendar/v3"
NOT_CONNECTED = "Google Calendar is not connected. Connect it in Settings → Integrations."


class CalendarError(GoogleOAuthError):
    pass


# ---------- OAuth ----------

async def create_authorization_url(session: AsyncSession, *, user_id: str, organization_id: str, chat_id: str | None = None) -> str:
    return await google_oauth.create_authorization_url(
        session, user_id=user_id, organization_id=organization_id,
        integration=INTEGRATION, scopes=CALENDAR_SCOPES, chat_id=chat_id,
    )


async def handle_oauth_callback(session: AsyncSession, *, user_id: str, organization_id: str, code: str, state: str) -> dict:
    oauth_state = await OAuthStateRepository.get_valid_state(session, user_id, organization_id, google_oauth.hash_state(state))
    if not oauth_state or oauth_state.integration != INTEGRATION:
        raise CalendarError("Invalid or expired OAuth state")
    token_payload = await google_oauth.exchange_code_for_token(code)
    await OAuthStateRepository.mark_used(session, oauth_state.id)

    connection = await OAuthConnectionRepository.upsert_user_connection(
        session, organization_id=organization_id, user_id=user_id, provider=PROVIDER,
        scopes={"scopes": CALENDAR_SCOPES}, connection_metadata={},
        **google_oauth.token_fields(token_payload),
    )
    calendar = GoogleCalendar(session, organization_id=organization_id, user_id=user_id)
    try:
        tz = await calendar.timezone_name()
        primary = await calendar._request("GET", "/calendars/primary")
        connection.connection_metadata = {"timezone": tz, "email": primary.get("id")}
    except CalendarError:
        logger.warning("calendar.connect.metadata_failed user_id=%s", user_id, exc_info=True)
    return {"connected": True, **(connection.connection_metadata or {})}


async def connection_status(session: AsyncSession, *, user_id: str, organization_id: str) -> dict:
    connection = await OAuthConnectionRepository.get_user_connection(session, organization_id, user_id, PROVIDER)
    if connection is None:
        return {"connected": False}
    return {"connected": True, **(connection.connection_metadata or {})}


async def disconnect(session: AsyncSession, *, user_id: str, organization_id: str) -> bool:
    connection = await OAuthConnectionRepository.get_user_connection(session, organization_id, user_id, PROVIDER)
    if connection is None:
        return False
    await OAuthConnectionRepository.delete(session, connection.id, organization_id)
    return True


# ---------- Pure helpers (no I/O) ----------

def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CalendarError(f"Unknown timezone '{name}'. Use an IANA name like Asia/Kolkata.") from exc


def parse_when(value: str, tz: ZoneInfo) -> datetime:
    """ISO date or datetime -> aware datetime. Naive values are taken in `tz`; a bare date is midnight."""
    text = (value or "").strip()
    if not text:
        raise CalendarError("A date or time is required.")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(text), time.min)
        except ValueError as exc:
            raise CalendarError(f"Could not read '{value}' as a date/time; use ISO format like 2026-11-03T15:00.") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


def rfc3339(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class EventDraft:
    title: str
    start: datetime
    end: datetime
    timezone: str
    attendees: list[str] = field(default_factory=list)
    description: str = ""
    location: str = ""
    add_meet: bool = False
    recurrence: list[str] = field(default_factory=list)  # RRULE lines, e.g. "RRULE:FREQ=WEEKLY;BYDAY=MO"
    reminder_minutes: list[int] = field(default_factory=list)

    def validate(self) -> None:
        if not self.title.strip():
            raise CalendarError("The event needs a title.")
        if self.end <= self.start:
            raise CalendarError("The event must end after it starts.")
        if self.end - self.start > timedelta(days=14):
            raise CalendarError("Events longer than 14 days aren't supported here.")
        for email in self.attendees:
            if "@" not in email or " " in email.strip():
                raise CalendarError(f"'{email}' is not an email address.")
        for rule in self.recurrence:
            if not rule.startswith(("RRULE:", "EXRULE:", "RDATE", "EXDATE")):
                raise CalendarError(f"Recurrence must be RRULE lines, got '{rule}'.")
        for minutes in self.reminder_minutes:
            if not 0 <= minutes <= 40320:  # Google's limit: four weeks
                raise CalendarError("Reminders must be between 0 minutes and 4 weeks before the event.")

    def idempotency_key(self, user_id: str) -> str:
        """Stable event id (base32hex alphabet) so a retried create can't book twice."""
        raw = "|".join([user_id, self.title.strip(), rfc3339(self.start), rfc3339(self.end), *sorted(self.attendees)])
        return "ba" + hashlib.sha256(raw.encode()).hexdigest()[:30]

    def to_body(self, user_id: str) -> dict:
        body: dict = {
            "id": self.idempotency_key(user_id),
            "summary": self.title.strip(),
            "start": {"dateTime": self.start.isoformat(), "timeZone": self.timezone},
            "end": {"dateTime": self.end.isoformat(), "timeZone": self.timezone},
        }
        if self.description:
            body["description"] = self.description
        if self.location:
            body["location"] = self.location
        if self.attendees:
            body["attendees"] = [{"email": e.strip()} for e in self.attendees]
        if self.recurrence:
            body["recurrence"] = self.recurrence
        if self.reminder_minutes:
            body["reminders"] = {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": m} for m in sorted(set(self.reminder_minutes))][:5],
            }
        if self.add_meet:
            body["conferenceData"] = {
                "createRequest": {"requestId": body["id"], "conferenceSolutionKey": {"type": "hangoutsMeet"}}
            }
        return body


def meet_link(event: dict) -> str | None:
    """The Meet URL only once Google has actually created the conference."""
    if event.get("hangoutLink"):
        return event["hangoutLink"]
    for entry in (event.get("conferenceData") or {}).get("entryPoints") or []:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return entry["uri"]
    return None


def simplify_event(event: dict) -> dict:
    start, end = event.get("start") or {}, event.get("end") or {}
    return {
        "id": event.get("id"),
        "title": event.get("summary") or "(no title)",
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "all_day": "date" in start,
        "status": event.get("status"),
        "location": event.get("location"),
        "attendees": [
            {"email": a.get("email"), "response": a.get("responseStatus")}
            for a in event.get("attendees") or [] if not a.get("resource")
        ],
        "meet_link": meet_link(event),
        "recurring": bool(event.get("recurringEventId") or event.get("recurrence")),
        "link": event.get("htmlLink"),
    }


def find_free_slots(
    busy: list[tuple[datetime, datetime]],
    *,
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
    tz: ZoneInfo,
    work_start: time = time(9, 0),
    work_end: time = time(18, 0),
    step: timedelta = timedelta(minutes=30),
    limit: int = 6,
    weekdays_only: bool = True,
) -> list[tuple[datetime, datetime]]:
    """Earliest slots of `duration` inside working hours that overlap no busy interval."""
    busy = sorted(busy)
    slots: list[tuple[datetime, datetime]] = []
    day = window_start.astimezone(tz).date()
    while day <= window_end.astimezone(tz).date() and len(slots) < limit:
        if not (weekdays_only and day.weekday() >= 5):
            cursor = max(datetime.combine(day, work_start, tz), window_start)
            # Align to the step grid (e.g. :00 / :30).
            minute_offset = (cursor.minute * 60 + cursor.second) % int(step.total_seconds())
            if minute_offset or cursor.microsecond:
                cursor += timedelta(seconds=int(step.total_seconds()) - minute_offset) - timedelta(microseconds=cursor.microsecond)
            day_end = min(datetime.combine(day, work_end, tz), window_end)
            while cursor + duration <= day_end and len(slots) < limit:
                candidate_end = cursor + duration
                if not any(b_start < candidate_end and cursor < b_end for b_start, b_end in busy):
                    slots.append((cursor, candidate_end))
                    cursor = candidate_end
                else:
                    cursor += step
        day += timedelta(days=1)
    return slots


# ---------- API client ----------

class GoogleCalendar:
    def __init__(self, session: AsyncSession, *, organization_id: str, user_id: str, client: httpx.AsyncClient | None = None):
        self._session = session
        self._organization_id = organization_id
        self._user_id = user_id
        self._client = client
        self._tz: str | None = None

    async def _token(self) -> str:
        connection = await OAuthConnectionRepository.get_user_connection(
            self._session, self._organization_id, self._user_id, PROVIDER
        )
        if connection is None:
            raise CalendarError(NOT_CONNECTED)
        return await google_oauth.valid_access_token(
            self._session, connection, reconnect_hint="Reconnect Google Calendar in Settings."
        )

    async def _request(self, method: str, path: str, *, params: dict | None = None, json_body: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {await self._token()}"}
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            resp = await client.request(method, API + path, params=params, json=json_body, headers=headers)
        except httpx.HTTPError as exc:
            raise CalendarError(f"Could not reach Google Calendar: {exc.__class__.__name__}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        if resp.status_code == 204:
            return {}
        if resp.status_code >= 400:
            try:
                message = resp.json().get("error", {}).get("message") or resp.text
            except ValueError:
                message = resp.text
            error = CalendarError(f"Google Calendar error {resp.status_code}: {message[:300]}")
            error.status_code = resp.status_code
            raise error
        return resp.json()

    async def timezone_name(self) -> str:
        if self._tz is None:
            setting = await self._request("GET", "/users/me/settings/timezone")
            self._tz = setting.get("value") or "UTC"
        return self._tz

    async def list_events(self, time_min: datetime, time_max: datetime, *, query: str | None = None, max_results: int = 25) -> list[dict]:
        params = {
            "timeMin": rfc3339(time_min), "timeMax": rfc3339(time_max), "singleEvents": "true",
            "orderBy": "startTime", "maxResults": min(max_results, 100),
        }
        if query:
            params["q"] = query
        data = await self._request("GET", "/calendars/primary/events", params=params)
        return [simplify_event(e) for e in data.get("items", []) if e.get("status") != "cancelled"]

    async def get_event(self, event_id: str) -> dict:
        return await self._request("GET", f"/calendars/primary/events/{event_id}")

    async def busy_intervals(
        self, time_min: datetime, time_max: datetime, calendars: list[str],
    ) -> tuple[list[tuple[datetime, datetime]], list[str]]:
        """Merged busy intervals across calendars, plus calendars whose availability we can't see."""
        body = {"timeMin": rfc3339(time_min), "timeMax": rfc3339(time_max), "items": [{"id": c} for c in calendars]}
        data = await self._request("POST", "/freeBusy", json_body=body)
        busy: list[tuple[datetime, datetime]] = []
        unavailable: list[str] = []
        for cal_id, info in (data.get("calendars") or {}).items():
            if info.get("errors"):
                # Someone else's calendar we can't see: report it rather than assume they're free.
                unavailable.append(cal_id)
                continue
            busy.extend(
                (datetime.fromisoformat(b["start"].replace("Z", "+00:00")), datetime.fromisoformat(b["end"].replace("Z", "+00:00")))
                for b in info.get("busy", [])
            )
        return busy, unavailable

    async def conflicts(self, start: datetime, end: datetime) -> list[dict]:
        events = await self.list_events(start, end, max_results=20)
        return [e for e in events if not e["all_day"]]

    async def create_event(self, draft: EventDraft) -> dict:
        draft.validate()
        body = draft.to_body(self._user_id)
        params = {"sendUpdates": "all" if draft.attendees else "none"}
        if draft.add_meet:
            params["conferenceDataVersion"] = 1
        try:
            event = await self._request("POST", "/calendars/primary/events", params=params, json_body=body)
        except CalendarError as exc:
            if getattr(exc, "status_code", None) != 409:
                raise
            event = await self.get_event(body["id"])  # same request already succeeded: idempotent retry
        if draft.add_meet and not meet_link(event):
            event = await self._await_conference(event["id"])
        return simplify_event(event)

    async def _await_conference(self, event_id: str) -> dict:
        import asyncio

        event: dict = {}
        for delay in (1, 2, 3):
            await asyncio.sleep(delay)
            event = await self.get_event(event_id)
            status = (((event.get("conferenceData") or {}).get("createRequest") or {}).get("status") or {}).get("statusCode")
            if meet_link(event) or status == "failure":
                break
        return event

    async def update_event(self, event_id: str, changes: dict, *, notify: bool = True) -> dict:
        params: dict = {"sendUpdates": "all" if notify else "none"}
        if "conferenceData" in changes:
            params["conferenceDataVersion"] = 1
        event = await self._request("PATCH", f"/calendars/primary/events/{event_id}", params=params, json_body=changes)
        if "conferenceData" in changes and not meet_link(event):
            event = await self._await_conference(event_id)
        return simplify_event(event)

    async def delete_event(self, event_id: str, *, notify: bool = True) -> None:
        await self._request("DELETE", f"/calendars/primary/events/{event_id}", params={"sendUpdates": "all" if notify else "none"})
