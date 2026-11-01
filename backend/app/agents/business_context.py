from app.agents.state import AgentState


def with_business_context(system_prompt: str, state: AgentState) -> str:
    """Append the organization's confirmed business profile (if any) to a node's system prompt."""
    context = (state.get("business_context") or "").strip()
    if not context:
        return system_prompt
    return f"{system_prompt}\n\n[Business Context]\n{context}"
