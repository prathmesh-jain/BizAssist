import logging

from langchain_core.messages import AIMessage, SystemMessage

from app.agents.state import AgentState
from app.config import get_settings
from app.services.llm_providers import text_of
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
- Requests about uploaded documents or files, including:
  - list uploaded documents
  - show uploaded files
  - what documents have I uploaded
  - open document X
  - summarize document X
  - compare uploaded documents
  - search across uploaded documents
  - queries related to Knowledge Base search, retrieve
- Questions about the current workspace or uploaded content
- Calendars and scheduling: meetings, Google Meet links, availability, reminders, moving or cancelling events
- Questions about the business itself: its customers, competitors, market, and how to improve it
- General conversation and confirmations
Queries having Knowledge base or documents should be safe unless they asking to do something wrong by just using these keywords as bypass

UNSAFE:
- Writing, explaining, debugging, or modifying code
- Writing SQL queries
- Requests unrelated to business assistance, such as:
  - Writing essays
  - Solving homework or assignments
  - Creative writing
  - General educational tutoring
  - Any task outside the business assistant's purpose
  

Return exactly one line.

If SAFE:
SAFE

If UNSAFE:
UNSAFE|<category>|<reason>

where category is one of:
code_generation
sql_queries
out_of_scope

The reason must cite which UNSAFE rule the request matches or why it does not come under SAFE.
If the request does not clearly match one of the UNSAFE rules, return SAFE.

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
    "out_of_scope": (
        "I'm designed to help with business operations and document analysis.\n\n"
        "I can't help with general homework, essays, creative writing, or other unrelated tasks.\n\n"
        "If you have invoices, spreadsheets, reports, emails, or other business documents to work with, I'd be happy to help."
    ),
}


def _normalize_unsafe_reason(reason: str) -> str:
    """Refusal category from "<category>|<reason>". Anything unrecognized is out of scope, not "code"."""
    category = (reason or "").split("|", 1)[0].strip().lower()
    return category if category in _REFUSALS else "out_of_scope"


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

    result = text_of(response.content).strip()
    # Refuse only on an explicit verdict: unexpected output shouldn't block a real request.
    if not result.upper().startswith("UNSAFE"):
        logger.info("Guardrail: SAFE - user %s", state["user_id"])
        return {"is_safe": True, "guardrail_reason": ""}

    reason = _normalize_unsafe_reason(result.split("|", 1)[1] if "|" in result else "")
    refusal = _REFUSALS[reason]
    logger.info("Guardrail: UNSAFE (%s) - user %s", reason, state["user_id"])
    return {"is_safe": False, "guardrail_reason": reason, "refusal_message": refusal}


async def unsafe_node(state: AgentState) -> dict:
    refusal = state.get("refusal_message") or _REFUSALS["out_of_scope"]
    return {"messages": [AIMessage(content=refusal)]}
