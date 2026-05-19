import logging
from functools import lru_cache
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient
from app.agents.state import AgentState
from app.agents.chat_agent import chat_node
from app.agents.guardrail import guardrail_node, unsafe_node
from app.agents.memory import summarization_node
from app.agents.tooling import common_tool_node, last_message_has_tool_calls
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def route_from_guardrail(state: AgentState) -> str:
    if not state.get("is_safe", True):
        return "unsafe"
    return "agent"


def route_from_agent(state: AgentState) -> str:
    if last_message_has_tool_calls(state):
        return "tools"
    return END


@lru_cache(maxsize=1)
def get_compiled_graph():
    """
    Build and compile the LangGraph agent graph.
    """
    graph = StateGraph(AgentState)

    graph.add_node("summarize", summarization_node)
    graph.add_node("guardrail", guardrail_node)
    graph.add_node("unsafe", unsafe_node)
    graph.add_node("agent", chat_node)
    graph.add_node("tools", common_tool_node)

    graph.set_entry_point("summarize")
    graph.add_edge("summarize", "guardrail")

    # Guardrail routes to unsafe or agent.
    graph.add_conditional_edges(
        "guardrail",
        route_from_guardrail,
        {
            "unsafe": "unsafe",
            "agent": "agent",
        }
    )

    graph.add_edge("unsafe", END)

    # Agent <-> Tools loop
    graph.add_conditional_edges(
        "agent",
        route_from_agent,
        {
            "tools": "tools",
            END: END,
        }
    )

    graph.add_edge("tools", "agent")

    client = MongoClient(settings.mongodb_uri)
    checkpointer = MongoDBSaver(client, db_name=settings.db_name)
    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("LangGraph agent graph compiled successfully ✓")
    return compiled
