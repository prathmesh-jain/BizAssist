import logging
from functools import lru_cache
from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.planner import planner_node
from app.agents.retrieval import retrieval_node
from app.agents.chat_agent import chat_node
from app.agents.sheets_agent import sheets_node
from app.agents.analyst import analyst_node
from app.agents.guardrail import guardrail_node, unsafe_node

logger = logging.getLogger(__name__)


def route_from_guardrail(state: AgentState) -> str:
    if not state.get("is_safe", True):
        return "unsafe"
    return "planner"


def route_from_planner(state: AgentState) -> str:
    """Route to the correct execution agent based on planner's classified intent."""
    intent = (state.get("intent") or "").strip().lower()
    return intent


@lru_cache(maxsize=1)
def get_compiled_graph():
    """
    Build and compile the LangGraph agent graph.

    Graph topology (memory management happens OUTSIDE, in chat_service.py):
        START → guardrail → [unsafe | planner]
        planner → [conversation | spreadsheet_crud | document_query | financial_analysis]
        document_query → conversation → END
        chat / sheets / analytics / unsafe → END
    """
    graph = StateGraph(AgentState)

    # Execution + planning nodes only — NO memory node
    graph.add_node("guardrail", guardrail_node)
    graph.add_node("unsafe", unsafe_node)
    graph.add_node("planner", planner_node)
    graph.add_node("conversation", chat_node)
    graph.add_node("financial_analysis", analyst_node)
    graph.add_node("document_query", retrieval_node)
    graph.add_node("spreadsheet_crud", sheets_node)

    # Entry: safety check first
    graph.set_entry_point("guardrail")

    # Guardrail → either refuse or plan
    graph.add_conditional_edges(
        "guardrail",
        route_from_guardrail,
        {"unsafe": "unsafe", "planner": "planner"},
    )

    graph.add_edge("unsafe", END)

    # Planner → execution agent
    graph.add_conditional_edges(
        "planner",
        route_from_planner,
        {
            "conversation": "conversation",
            "spreadsheet_crud": "spreadsheet_crud",
            "document_query": "document_query",
            "financial_analysis": "financial_analysis",
        },
    )

    # Document query enriches context then hands off to conversation for the final answer
    graph.add_edge("document_query", "conversation")

    # Terminal nodes
    graph.add_edge("conversation", END)
    graph.add_edge("spreadsheet_crud", END)
    graph.add_edge("financial_analysis", END)

    compiled = graph.compile()
    logger.info("LangGraph agent graph compiled successfully ✓")
    return compiled
