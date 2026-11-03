from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.agents.state import AgentState


def _now_line(user_timezone: str | None) -> str:
    if user_timezone:
        try:
            now = datetime.now(ZoneInfo(user_timezone))
            return f"[Now] {now.strftime('%A %d %B %Y, %H:%M')} {user_timezone} (the user's local time)."
        except (ZoneInfoNotFoundError, ValueError):
            pass
    today = datetime.now(timezone.utc).strftime("%A %d %B %Y")
    return (
        f"[Today] {today} (UTC). The user's local date may differ: never state a specific "
        "date for words like 'tomorrow' unless calendar_now returned the user's local time."
    )


def with_business_context(system_prompt: str, state: AgentState) -> str:
    """Append today's date and the organization's confirmed business profile (if any) to a prompt."""
    prompt = f"{system_prompt}\n\n{_now_line(state.get('user_timezone'))}"
    context = (state.get("business_context") or "").strip()
    if not context:
        return prompt
    return f"{prompt}\n\n[Business Context]\n{context}"
