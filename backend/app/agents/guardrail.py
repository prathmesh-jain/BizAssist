import logging

from langchain_core.messages import AIMessage, SystemMessage

from app.agents.state import AgentState
from app.config import get_settings
from app.services.llm_service import get_llm

logger = logging.getLogger(__name__)
settings = get_settings()

GUARDRAIL_SYSTEM = """
You are a safety classifier for BizAssist.

SAFE:
- Reading, summarizing, or analyzing spreadsheets, invoices, PDFs, and business documents
- Spreadsheet calculations and formulas
- Business, finance, accounting, operations, reports
- Follow-up questions about uploaded files
- General conversation and confirmations

UNSAFE:
- Writing, explaining, debugging, or modifying code
- Writing SQL queries

Return exactly one of:
SAFE
UNSAFE|code_generation
UNSAFE|sql_queries

Do not invent other categories.
"""

_REFUSALS = {
    "code_generation": (
        "I can't write or explain code - that's outside my scope.\n\n"
        "What I can help with:\n"
        "- Analyzing your invoices and financial documents\n"
        "- Business strategy and email drafting\n"
        "- Reviewing expenses and identifying spending patterns\n\n"
        "Would any of those be useful?"
    ),
    "sql_queries": (
        "I can't create SQL queries. I'm a business operations assistant, not a database tool.\n\n"
        "If you want to analyze your data, I can read your Google Sheets or invoices directly - just ask!"
    ),
}


def _normalize_unsafe_reason(reason: str) -> str:
    normalized = (reason or "").strip().lower()
    if normalized in _REFUSALS:
        return normalized
    if "sql" in normalized:
        return "sql_queries"
    if "code" in normalized or "program" in normalized or "script" in normalized:
        return "code_generation"
    return ""


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

    result = str(response.content or "").strip()
    if result.upper().startswith("SAFE"):
        logger.info("Guardrail: SAFE - user %s", state["user_id"])
        return {"is_safe": True, "guardrail_reason": ""}

    reason = _normalize_unsafe_reason(result.replace("UNSAFE|", "").strip())
    refusal = _REFUSALS.get(reason) or _REFUSALS["code_generation"]
    log_reason = reason or "generic_out_of_scope"
    logger.info("Guardrail: UNSAFE (%s) - user %s", log_reason, state["user_id"])
    return {"is_safe": False, "guardrail_reason": reason, "refusal_message": refusal}


async def unsafe_node(state: AgentState) -> dict:
    refusal = state.get("refusal_message") or _REFUSALS["code_generation"]
    return {"messages": [AIMessage(content=refusal)]}
