from typing import TypedDict, Optional, Annotated, Any
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


class AgentState(TypedDict):
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
    
    # Guardrail (transient state for the safety node)
    is_safe: bool
    guardrail_reason: str
    refusal_message: str
