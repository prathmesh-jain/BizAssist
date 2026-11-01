"""LangChain tools for the member's own Google Calendar (events, availability, Meet).

Read tools run directly. Tools that create, move or delete events always pause for
explicit approval (an accept/decline interrupt) showing exactly what will happen,
including conflicts, and act only after the user accepts.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, Optional

from langchain_core.tools import tool
from langgraph.types import interrupt

from app.db.base import session_scope
from app.services.google_calendar_service import (
    CalendarError, EventDraft, GoogleCalendar, find_free_slots, parse_when, zone,
)


def request_approval(question: str, details: dict) -> bool:
    """Pause the run until the user accepts or declines. Decline resumes with False."""
    answer = interrupt({
        "question": question,
        "interrupt_type": "accept_decline",
        "action_required": "approve_calendar_change",
        "data": details,
    })
    return answer is not False and answer not in ("reject", "decline")


def _fmt(moment: datetime, tz) -> str:
    return moment.astimezone(tz).strftime("%a %d %b %Y, %H:%M")


def get_calendar_tools(*, user_id: str, organization_id: str):
    async def run(fn):
        async with session_scope() as session:
            calendar = GoogleCalendar(session, organization_id=organization_id, user_id=user_id)
            tz = zone(await calendar.timezone_name())
            return await fn(calendar, tz)

    def error(exc: Exception) -> dict:
        return {"ok": False, "error": str(exc)}

    @tool("calendar_now")
    async def calendar_now() -> dict:
        """Current date and time in the user's calendar timezone.

        Call this first to resolve relative dates such as "tomorrow at 3 PM" or "next week".
        """
        async def go(calendar, tz):
            now = datetime.now(tz)
            return {"ok": True, "now": now.isoformat(timespec="minutes"), "weekday": now.strftime("%A"), "timezone": str(tz)}
        try:
            return await run(go)
        except CalendarError as exc:
            return error(exc)

    @tool("calendar_list_events")
    async def calendar_list_events(start: Optional[str] = None, end: Optional[str] = None, query: Optional[str] = None) -> dict:
        """List the user's calendar events between two dates (default: the next 7 days).

        Args:
            start: ISO date/datetime, e.g. "2026-11-03" or "2026-11-03T09:00". Naive values use the user's timezone.
            end: ISO date/datetime (exclusive). For a single day, pass the next day.
            query: Optional text to match (title, attendees, location).
        Returns events with ids (needed to update or delete), times, attendees and Meet links.
        """
        async def go(calendar, tz):
            time_min = parse_when(start, tz) if start else datetime.now(tz)
            time_max = parse_when(end, tz) if end else time_min + timedelta(days=7)
            events = await calendar.list_events(time_min, time_max, query=query)
            return {"ok": True, "timezone": str(tz), "count": len(events), "events": events}
        try:
            return await run(go)
        except CalendarError as exc:
            return error(exc)

    @tool("calendar_find_free_slots")
    async def calendar_find_free_slots(
        duration_minutes: int,
        start: Optional[str] = None,
        end: Optional[str] = None,
        attendees: Optional[list[str]] = None,
        work_start: str = "09:00",
        work_end: str = "18:00",
    ) -> dict:
        """Find open meeting slots for the user (and optionally attendees) within working hours.

        Args:
            duration_minutes: Meeting length.
            start / end: Search window as ISO dates/datetimes (default: next 5 days).
            attendees: Emails whose calendars to check too. Only calendars the user can see
                are checked; others are listed under "unknown_availability".
            work_start / work_end: Working hours in the user's timezone, "HH:MM".
        """
        async def go(calendar, tz):
            window_start = max(parse_when(start, tz), datetime.now(tz)) if start else datetime.now(tz)
            window_end = parse_when(end, tz) if end else window_start + timedelta(days=5)
            busy, unknown = await calendar.busy_intervals(window_start, window_end, ["primary", *(attendees or [])])
            slots = find_free_slots(
                busy, window_start=window_start, window_end=window_end,
                duration=timedelta(minutes=int(duration_minutes)), tz=tz,
                work_start=time.fromisoformat(work_start), work_end=time.fromisoformat(work_end),
            )
            return {
                "ok": True,
                "timezone": str(tz),
                "slots": [{"start": s.isoformat(timespec="minutes"), "end": e.isoformat(timespec="minutes")} for s, e in slots],
                "unknown_availability": unknown,
            }
        try:
            return await run(go)
        except (CalendarError, ValueError) as exc:
            return error(exc)

    @tool("calendar_create_event")
    async def calendar_create_event(
        title: str,
        start: str,
        end: Optional[str] = None,
        duration_minutes: Optional[int] = None,
        attendees: Optional[list[str]] = None,
        description: str = "",
        location: str = "",
        add_google_meet: bool = False,
        recurrence: Optional[list[str]] = None,
        reminder_minutes_before: Optional[list[int]] = None,
        timezone: Optional[str] = None,
    ) -> dict:
        """Create a calendar event (meeting, reminder, deadline) after the user approves it.

        Args:
            title: Event title.
            start: ISO datetime, e.g. "2026-11-03T15:00" (user's timezone unless an offset is given).
            end / duration_minutes: Give one; default 30 minutes.
            attendees: Guest emails; they receive invitations. Never guess emails: ask the user.
            add_google_meet: True to attach a Google Meet link.
            recurrence: RRULE lines, e.g. ["RRULE:FREQ=WEEKLY;BYDAY=MO"].
            reminder_minutes_before: Popup reminders, e.g. [2880] for two days before.
            timezone: IANA zone; defaults to the user's calendar timezone.
        The user sees the details and any conflicts and must accept before anything is created.
        A Meet link is returned only once Google has actually created it.
        """
        async def go(calendar, user_tz):
            tz = zone(timezone) if timezone else user_tz
            begin = parse_when(start, tz)
            finish = parse_when(end, tz) if end else begin + timedelta(minutes=int(duration_minutes or 30))
            draft = EventDraft(
                title=title, start=begin, end=finish, timezone=str(tz), attendees=list(attendees or []),
                description=description, location=location, add_meet=bool(add_google_meet),
                recurrence=list(recurrence or []), reminder_minutes=[int(m) for m in (reminder_minutes_before or [])],
            )
            draft.validate()
            conflicts = await calendar.conflicts(begin, finish)
            details = {
                "title": draft.title,
                "when": f"{_fmt(begin, tz)} – {finish.astimezone(tz).strftime('%H:%M')} ({tz})",
                "attendees": draft.attendees or None,
                "google_meet": draft.add_meet or None,
                "repeats": draft.recurrence or None,
                "reminders_minutes_before": draft.reminder_minutes or None,
                "conflicts": [f"{c['title']} ({c['start']} – {c['end']})" for c in conflicts] or None,
            }
            details = {k: v for k, v in details.items() if v is not None}
            question = f"Create “{draft.title}” on {_fmt(begin, tz)}?"
            if conflicts:
                question += f" It overlaps {len(conflicts)} existing event(s)."
            if not request_approval(question, details):
                return {"ok": False, "cancelled": True, "message": "The user declined; nothing was created."}
            event = await calendar.create_event(draft)
            result: dict[str, Any] = {"ok": True, "created": True, "event": event}
            if draft.add_meet and not event.get("meet_link"):
                result["warning"] = "The event was created but Google has not returned a Meet link yet."
            return result
        try:
            return await run(go)
        except CalendarError as exc:
            return error(exc)

    @tool("calendar_update_event")
    async def calendar_update_event(
        event_id: str,
        title: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        duration_minutes: Optional[int] = None,
        add_attendees: Optional[list[str]] = None,
        remove_attendees: Optional[list[str]] = None,
        location: Optional[str] = None,
        description: Optional[str] = None,
        add_google_meet: Optional[bool] = None,
    ) -> dict:
        """Move or edit an existing event (get event_id from calendar_list_events) after the user approves.

        When only `start` is given, the event keeps its original length.
        """
        async def go(calendar, tz):
            current = await calendar.get_event(event_id)
            changes: dict[str, Any] = {}
            summary: dict[str, Any] = {"event": current.get("summary")}
            if title:
                changes["summary"] = summary["new_title"] = title
            old_start = current.get("start", {}).get("dateTime")
            old_end = current.get("end", {}).get("dateTime")
            if start or end or duration_minutes:
                if not (old_start and old_end) and not (start and (end or duration_minutes)):
                    raise CalendarError("All-day events need both a new start and end.")
                begin = parse_when(start, tz) if start else datetime.fromisoformat(old_start)
                length = datetime.fromisoformat(old_end) - datetime.fromisoformat(old_start) if old_start and old_end else timedelta(minutes=30)
                finish = parse_when(end, tz) if end else begin + (timedelta(minutes=int(duration_minutes)) if duration_minutes else length)
                if finish <= begin:
                    raise CalendarError("The event must end after it starts.")
                changes["start"] = {"dateTime": begin.isoformat(), "timeZone": str(tz)}
                changes["end"] = {"dateTime": finish.isoformat(), "timeZone": str(tz)}
                summary["new_time"] = f"{_fmt(begin, tz)} – {finish.astimezone(tz).strftime('%H:%M')}"
                conflicts = [c for c in await calendar.conflicts(begin, finish) if c["id"] != event_id]
                if conflicts:
                    summary["conflicts"] = [f"{c['title']} ({c['start']} – {c['end']})" for c in conflicts]
            if add_attendees or remove_attendees:
                emails = [a.get("email") for a in current.get("attendees") or []]
                emails = [e for e in emails if e not in (remove_attendees or [])] + [e for e in add_attendees or [] if e not in emails]
                changes["attendees"] = [{"email": e} for e in emails]
                summary["attendees"] = emails
            if location is not None:
                changes["location"] = summary["location"] = location
            if description is not None:
                changes["description"] = description
            if add_google_meet and not current.get("hangoutLink"):
                changes["conferenceData"] = {"createRequest": {"requestId": f"{event_id}-meet", "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
                summary["google_meet"] = True
            if not changes:
                return {"ok": False, "error": "Nothing to change."}
            if not request_approval(f"Update “{current.get('summary')}”?", summary):
                return {"ok": False, "cancelled": True, "message": "The user declined; the event is unchanged."}
            event = await calendar.update_event(event_id, changes)
            return {"ok": True, "updated": True, "event": event}
        try:
            return await run(go)
        except CalendarError as exc:
            return error(exc)

    @tool("calendar_delete_event")
    async def calendar_delete_event(event_id: str) -> dict:
        """Cancel/delete an event (get event_id from calendar_list_events) after the user approves.
        Attendees are notified."""
        async def go(calendar, tz):
            current = await calendar.get_event(event_id)
            start = (current.get("start") or {}).get("dateTime") or (current.get("start") or {}).get("date")
            if not request_approval(
                f"Delete “{current.get('summary')}”?",
                {"event": current.get("summary"), "when": start,
                 "attendees_notified": [a.get("email") for a in current.get("attendees") or []] or None},
            ):
                return {"ok": False, "cancelled": True, "message": "The user declined; the event was kept."}
            await calendar.delete_event(event_id)
            return {"ok": True, "deleted": True}
        try:
            return await run(go)
        except CalendarError as exc:
            return error(exc)

    return [
        calendar_now, calendar_list_events, calendar_find_free_slots,
        calendar_create_event, calendar_update_event, calendar_delete_event,
    ]
