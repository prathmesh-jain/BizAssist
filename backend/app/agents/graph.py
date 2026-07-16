import logging
from functools import lru_cache

from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.graph import END, StateGraph
from pymongo import MongoClient

from app.agents.chat_agent import chat_node
from app.agents.executor_agent import executor_node
from app.agents.guardrail import guardrail_node, unsafe_node
from app.agents.memory import summarization_node
from app.agents.planner_agent import planner_node
from app.agents.state import AgentState
from app.agents.tooling import common_tool_node, last_message_has_tool_calls
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def route_from_guardrail(state: AgentState) -> str:
    if not state.get("is_safe", True):
        return "unsafe"
    return "chat"


def route_from_chat(state: AgentState) -> str:
    if last_message_has_tool_calls(state):
        return "tools"
    if state.get("chat_route") == "planner":
        return "planner"
    return END


def route_from_planner(state: AgentState) -> str:
    if last_message_has_tool_calls(state):
        return "tools"
    return "executor"


def route_from_executor(state: AgentState) -> str:
    if last_message_has_tool_calls(state):
        return "tools"
    return "chat"


def route_from_tools(state: AgentState) -> str:
    return state.get("active_agent", "executor")


@lru_cache(maxsize=1)
def get_compiled_graph():
    """Build and compile the LangGraph agent graph."""
    graph = StateGraph(AgentState)

    graph.add_node("summarize", summarization_node)
    graph.add_node("guardrail", guardrail_node)
    graph.add_node("unsafe", unsafe_node)
    graph.add_node("chat", chat_node)
    graph.add_node("planner", planner_node)
    graph.add_node("executor", executor_node)
    graph.add_node("tools", common_tool_node)

    graph.set_entry_point("summarize")
    graph.add_edge("summarize", "guardrail")

    graph.add_conditional_edges(
        "guardrail",
        route_from_guardrail,
        {
            "unsafe": "unsafe",
            "chat": "chat",
        },
    )

    graph.add_edge("unsafe", END)

    graph.add_conditional_edges(
        "chat",
        route_from_chat,
        {
            "tools": "tools",
            "planner": "planner",
            END: END,
        },
    )

    graph.add_conditional_edges(
        "planner",
        route_from_planner,
        {
            "tools": "tools",
            "executor": "executor",
        },
    )

    graph.add_conditional_edges(
        "executor",
        route_from_executor,
        {
            "tools": "tools",
            "chat": "chat",
        },
    )

    graph.add_conditional_edges(
        "tools",
        route_from_tools,
        {
            "chat": "chat",
            "planner": "planner",
            "executor": "executor",
        },
    )

    client = MongoClient(settings.mongodb_uri)
    checkpointer = MongoDBSaver(client, db_name=settings.db_name)
    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("LangGraph agent graph compiled successfully")
    return compiled
