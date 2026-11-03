from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


class AgentState(TypedDict, total=False):
    """
    Shared state passed between all nodes in the LangGraph agent graph.
    """
    messages: Annotated[list[BaseMessage], add_messages]  # message accumulation
    message_summary: str  # summarized older messages for context

    # Infrastructure / Auth
    user_id: str
    chat_id: str
    organization_id: str  # Added for multi-tenancy
    role: str  # caller's organization role; tools enforce app.authz rules with it
    business_context: str  # confirmed business profile summary, refreshed every turn
    user_timezone: str  # IANA zone from the user's connected calendar, when known

    # Tools chat may call directly this turn, chosen from the user's message
    chat_tool_ids: list[str]

    # Observability
    tool_calls_made: list[str]

    # Chat / planning flow
    chat_route: str
    execution_brief: str
    execution_plan: str
    execution_steps: list[str]
    execution_query: str
    execution_completed: bool
    planner_iterations: int
    active_agent: str
    progress_event: dict

    # Tool selection
    active_tool_ids: list[str]
    last_tool_search_category: str
    consecutive_tool_searches: int
    last_tool_search_query: str

    # Guardrail (transient state for the safety node)
    is_safe: bool
    guardrail_reason: str
    refusal_message: str
