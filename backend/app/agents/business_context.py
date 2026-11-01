from datetime import datetime, timezone

from app.agents.state import AgentState


def with_business_context(system_prompt: str, state: AgentState) -> str:
    """Append today's date and the organization's confirmed business profile (if any) to a prompt."""
    today = datetime.now(timezone.utc).strftime("%A %d %B %Y")
    prompt = f"{system_prompt}\n\n[Today] {today} (UTC). Use calendar_now for the user's local time."
    context = (state.get("business_context") or "").strip()
    if not context:
        return prompt
    return f"{prompt}\n\n[Business Context]\n{context}"
