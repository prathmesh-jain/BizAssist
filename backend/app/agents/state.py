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
    
    # Observability
    tool_calls_made: list[str]

    # Chat / planning flow
    chat_route: str
    execution_brief: str
    execution_plan: str
    execution_steps: list[str]
    execution_query: str
    execution_completed: bool
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
