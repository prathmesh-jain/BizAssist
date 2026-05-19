import json
import logging
from typing import Any, Optional

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from app.agents.state import AgentState

logger = logging.getLogger(__name__)


def _state_ids(state: AgentState) -> tuple[str, str | None]:
    return state.get("user_id", ""), state.get("chat_id")


def build_tools_for_agent(state: AgentState) -> list:
    """Build all available tools for the unified agent."""
    user_id, chat_id = _state_ids(state)

    @tool("request_clarification")
    async def request_clarification(
        question: str,
        field: str | None = None,
        options: list[str] | None = None,
        interrupt_type: str = "text_input",
        reason: str = "",
    ) -> dict:
        """Ask the user for missing information and return their answer."""
        answer = interrupt(
            {
                "question": question,
                "field": field,
                "options": options or [],
                "interrupt_type": interrupt_type or "text_input",
                "reason": reason,
            }
        )
        return {"ok": True, "user_response": answer}

    @tool("rag_retrieve")
    async def rag_retrieve(query: str, k: int = 5, filename: Optional[str] = None) -> dict:
        """Retrieve relevant passages from indexed business documents. 
        Optionally filter by a specific filename to focus the search.
        """
        from app.services.rag_service import retrieve

        ctx = await retrieve(query=query, user_id=user_id, k=int(k or 5), filename=filename)
        return {"ok": True, "query": query, "k": int(k or 5), "filename": filename, "context": ctx}

    @tool("list_ingested_documents")
    async def list_ingested_documents() -> dict:
        """List all business documents currently indexed in the RAG knowledge base.
        Returns a list of document names and IDs.
        """
        from app.services.rag_service import list_user_documents
        docs = await list_user_documents(user_id=user_id)
        return {"ok": True, "documents": docs}

    tools = [request_clarification, rag_retrieve, list_ingested_documents]

    # Add attachment tools
    from app.tools.chat_attachments_tools import get_chat_attachments_tools
    tools.extend(get_chat_attachments_tools(user_id=user_id, chat_id=chat_id))

    # Add spreadsheet tools
    from app.tools.google_sheets_tools import get_sheets_tools
    tools.extend(get_sheets_tools(user_id=user_id, chat_id=chat_id))

    return tools


async def common_tool_node(state: AgentState) -> dict:
    """Execute the latest AIMessage tool calls."""
    tools = build_tools_for_agent(state)
    node = ToolNode(tools)
    return await node.ainvoke(state)


def last_message_has_tool_calls(state: AgentState) -> bool:
    messages = state.get("messages") or []
    if not messages:
        return False
    last = messages[-1]
    return bool(getattr(last, "tool_calls", None))
