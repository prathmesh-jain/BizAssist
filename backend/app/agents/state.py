from typing import TypedDict, Optional, Annotated
from langchain_core.messages import BaseMessage
import operator


class AgentState(TypedDict):
    """
    Shared state passed between all nodes in the LangGraph agent graph.
    """
    messages: Annotated[list[BaseMessage], operator.add]  # message accumulation
    intent: str          # planner-detected intent: chat|invoice|analytics|retrieval
    is_safe: bool        # guardrail: whether request is within scope
    guardrail_reason: str  # reason if request is unsafe
    refusal_message: str   # guardrail refusal text for unsafe requests
    retrieved_context: str   # RAG-retrieved passages
    invoice_data: Optional[dict]   # structured invoice extraction result
    user_id: str
    chat_id: str
    confirmed: bool      # user confirmed an action (Google Sheets logging etc.)
    spreadsheet_id: str  # Google Sheet ID for analytics/invoice
    sheet_name: str      # Sheet tab name (default: Expenses)
    next: str            # next node to route to
    tool_calls_made: list[str]  # for observability
    message_summary: str  # summarized older messages for context
