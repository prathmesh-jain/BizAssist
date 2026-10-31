import asyncio
import logging
from functools import lru_cache

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

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

_checkpoint_pool: AsyncConnectionPool | None = None
_checkpointer: AsyncPostgresSaver | None = None


def _checkpoint_conninfo(database_url: str) -> str:
    # The checkpointer uses psycopg, not SQLAlchemy, so drop the "+asyncpg" driver suffix.
    scheme, sep, rest = database_url.partition("://")
    return f"{scheme.split('+', 1)[0]}{sep}{rest}"


async def init_checkpointer() -> None:
    """Open the checkpoint connection pool and create checkpoint tables if missing."""
    global _checkpoint_pool, _checkpointer
    if _checkpointer is not None:
        return

    if isinstance(asyncio.get_running_loop(), getattr(asyncio, "ProactorEventLoop", ())):
        raise RuntimeError(
            "psycopg cannot run on Windows' ProactorEventLoop. Start the server with "
            "`uvicorn app.main:app --reload` or add `--loop asyncio:SelectorEventLoop`."
        )

    pool = AsyncConnectionPool(
        conninfo=_checkpoint_conninfo(settings.database_url),
        max_size=10,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open(wait=True, timeout=15)
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    _checkpoint_pool, _checkpointer = pool, checkpointer
    logger.info("LangGraph PostgreSQL checkpointer ready")


async def close_checkpointer() -> None:
    global _checkpoint_pool, _checkpointer
    if _checkpoint_pool is not None:
        await _checkpoint_pool.close()
    _checkpoint_pool, _checkpointer = None, None


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
    """Build and compile the LangGraph agent graph with PostgreSQL checkpointing."""
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

    if _checkpointer is None:
        raise RuntimeError("init_checkpointer() must run before the graph is compiled")
    compiled = graph.compile(checkpointer=_checkpointer)
    logger.info("LangGraph agent graph compiled successfully with PostgreSQL checkpointing")
    return compiled
