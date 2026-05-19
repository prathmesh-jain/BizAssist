import logging
from langchain_core.messages import SystemMessage, AIMessage
from app.agents.state import AgentState
from app.config import get_settings
from app.services.llm_service import get_llm

logger = logging.getLogger(__name__)
settings = get_settings()

GUARDRAIL_SYSTEM = """
You are a safety guardrail for BizAssist.
BizAssist supports: Business/finance, invoices, documents, and spreadsheet operations.
Calculations and spreadsheet formulas are SAFE. Confirmations like "yes/ok" are SAFE.
Block only out-of-scope requests like writing code or SQL.
Respond: SAFE or UNSAFE|reason.
"""

_REFUSALS = {
    "code_generation": (
        "I can't write or explain code — that's outside my scope.\n\n"
        "What I *can* help with:\n"
        "- Analysing your invoices and financial documents\n"
        "- Business strategy and email drafting\n"
        "- Reviewing expenses and identifying spending patterns\n\n"
        "Would any of those be useful?"
    ),
    "sql_queries": (
        "I can't create SQL queries. I'm a business operations assistant, not a database tool.\n\n"
        "If you want to analyse your data, I can read your Google Sheets or invoices directly — "
        "just ask!"
    ),
}


async def guardrail_node(state: AgentState) -> dict:
    """Check if the user's request is in-scope before routing to any agent."""
    if not settings.use_guardrail:
        return {"is_safe": True, "guardrail_reason": ""}

    last_user_msg = next(
        (m.content for m in reversed(state["messages"]) if m.type == "human"), ""
    )
    if not last_user_msg:
        return {"is_safe": True, "guardrail_reason": ""}

    llm = await get_llm(
        user_id=state["user_id"],
        purpose="nano",
        temperature=0,
    )
    response = await llm.ainvoke([
        SystemMessage(content=GUARDRAIL_SYSTEM),
        {"role": "user", "content": last_user_msg},
    ])

    result = response.content.strip()
    if result.upper().startswith("SAFE"):
        logger.info(f"Guardrail: SAFE — user {state['user_id']}")
        return {"is_safe": True, "guardrail_reason": ""}

    reason = result.replace("UNSAFE|", "").strip().lower()
    if reason not in _REFUSALS:
        logger.info(f"Guardrail: UNSAFE ({reason}) — user {state['user_id']}")
        return {"is_safe": True, "guardrail_reason": ""}
    refusal = _REFUSALS[reason]
    logger.info(f"Guardrail: UNSAFE ({reason}) — user {state['user_id']}")
    return {"is_safe": False, "guardrail_reason": reason, "refusal_message": refusal}


async def unsafe_node(state: AgentState) -> dict:
    refusal = state.get("refusal_message") or _REFUSALS["code_generation"]
    return {"messages": [AIMessage(content=refusal)]}
