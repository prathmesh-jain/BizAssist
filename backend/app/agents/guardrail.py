import logging
from langchain_core.messages import SystemMessage, AIMessage
from app.agents.state import AgentState
from app.config import get_settings
from app.services.llm_service import get_llm

logger = logging.getLogger(__name__)
settings = get_settings()

GUARDRAIL_SYSTEM = """
You are a safety guardrail for BizAssist, a business finance assistant.

Your job is to decide if the user's latest message is SAFE or UNSAFE.

BizAssist supports:
- Business and financial questions
- Invoice and document processing
- Spreadsheet and financial data operations
- Reading, updating, and analyzing financial data
- Logging invoices and expenses
- Spreadsheet formulas and calculations (SUM, totals, averages, etc.)
- Google Sheets operations like View/Acess sheet, update sheet, create sheet, delete sheet, rename sheet, etc.

IMPORTANT:
All spreadsheet-related tasks, including formulas, totals, calculations, and automation inside spreadsheets, are ALWAYS SAFE.

Short confirmations such as "yes", "ok", or "proceed" are ALWAYS SAFE.

Block the request only if the request is to write some code, something which is out of scope of the application.

If the request is ambiguous, treat it as SAFE.

Judge ONLY the latest message.

Respond with exactly one line:

SAFE

OR

UNSAFE|code_generation
UNSAFE|sql_queries
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

    llm = get_llm(
        model_name=settings.nano_model,
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
    refusal = state.get("refusal_message") or _REFUSALS["technical_implementation"]
    return {"messages": [AIMessage(content=refusal)]}
