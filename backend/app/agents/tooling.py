import ast
import difflib
import json
import logging
from collections import Counter
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app.agents.state import AgentState

logger = logging.getLogger(__name__)


class ListDocumentsInput(BaseModel):
    filename: str | None = Field(
        default=None,
        description="Optional filename or partial filename to fuzzy-match against available documents.",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum number of matching documents to return.",
    )


def _state_ids(state: AgentState) -> tuple[str, str | None]:
    return state.get("user_id", ""), state.get("chat_id")


def _latest_user_message(state: AgentState) -> str:
    for message in reversed(state.get("messages") or []):
        if getattr(message, "type", "") == "human":
            return str(getattr(message, "content", "") or "").strip()
    return ""


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part for part in parts if part).strip()
    return str(content or "").strip()


def build_execution_tool_query(state: AgentState) -> str:
    """Build a search query for executor tool selection."""
    execution_query = str(state.get("execution_query") or "").strip()
    if execution_query:
        return execution_query

    planned_parts: list[str] = []
    execution_brief = str(state.get("execution_brief") or "").strip()
    execution_plan = str(state.get("execution_plan") or "").strip()
    if execution_brief:
        planned_parts.append(f"Execution brief:\n{execution_brief}")
    if execution_plan:
        planned_parts.append(f"Execution plan:\n{execution_plan}")
    if planned_parts:
        return "\n\n".join(planned_parts)

    parts: list[str] = []

    summary = str(state.get("message_summary") or "").strip()
    if summary:
        parts.append(f"Summary:\n{summary}")

    recent_messages = state.get("messages") or []
    recent_context: list[str] = []
    for message in reversed(recent_messages):
        if isinstance(message, ToolMessage):
            continue
        role = None
        if isinstance(message, HumanMessage):
            role = "User"
        elif isinstance(message, AIMessage):
            role = "Assistant"
        elif isinstance(message, SystemMessage):
            continue
        elif getattr(message, "type", "") == "human":
            role = "User"
        elif getattr(message, "type", "") == "ai":
            role = "Assistant"
        else:
            continue

        text = _message_text(getattr(message, "content", ""))
        if not text:
            continue

        recent_context.append(f"{role}: {text}")
        if len(recent_context) >= 6:
            break

    if recent_context:
        parts.append("Recent conversation:\n" + "\n".join(reversed(recent_context)))

    return "\n\n".join(part for part in parts if part).strip()


def _infer_search_category(query: str, matches: list[dict[str, Any]]) -> str:
    integrations = [str(match.get("integration") or "").strip() for match in matches if match.get("integration")]
    if integrations:
        return Counter(integrations).most_common(1)[0][0]

    normalized = query.lower()
    if any(token in normalized for token in ("sheet", "spreadsheet", "tab", "row", "column", "cell")):
        return "google_sheets"
    if any(token in normalized for token in ("document", "invoice", "pdf", "contract", "file")):
        return "rag"
    if any(token in normalized for token in ("attachment", "upload", "uploaded")):
        return "attachments"
    return "general"


def _tool_search_interrupt_question(category: str, query: str) -> str:
    if category == "google_sheets":
        return (
            "I keep searching spreadsheet tools but still need a clearer instruction. "
            "Tell me exactly what you want to do in the spreadsheet."
        )
    if category == "rag":
        return (
            "I keep searching document tools but still need a clearer instruction. "
            "Tell me which document, file, or business question you want me to focus on."
        )
    if category == "attachments":
        return (
            "I keep searching attachment tools but still need a clearer instruction. "
            "Tell me which uploaded file to inspect and what you want from it."
        )
    return (
        "I keep searching for the right tools but still need a clearer instruction. "
        "Please describe exactly what you want me to do."
    )


def get_core_tools(state: AgentState) -> list:
    """Build the core tools that remain available across execution turns."""
    user_id, _ = _state_ids(state)

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
        Use this for direct knowledge-base lookup and single-step document questions.
        Optionally filter by a specific filename to focus the search.
        """
        from app.services.rag_service import retrieve

        ctx = await retrieve(query=query, user_id=user_id, k=int(k or 5), filename=filename)
        return {"ok": True, "query": query, "k": int(k or 5), "filename": filename, "context": ctx}

    return [request_clarification, rag_retrieve]


def get_clarification_tools(state: AgentState) -> list:
    return [tool for tool in get_core_tools(state) if tool.name == "request_clarification"]


def get_rag_tools(state: AgentState) -> list:
    return [tool for tool in get_core_tools(state) if tool.name == "rag_retrieve"]


def get_document_listing_tools(state: AgentState) -> list:
    user_id, chat_id = _state_ids(state)

    @tool("list_documents", args_schema=ListDocumentsInput)
    async def list_documents(filename: str | None = None, limit: int = 5) -> dict:
        """List available documents from chat uploads and indexed knowledge-base documents.

        Optionally provide a filename or partial filename to return the closest matching documents.
        Results include the document source so you know whether a file is a chat upload or an indexed document.
        If you later need to read an indexed knowledge-base document, route that task to the planner.
        """
        from app.services.rag_service import list_user_documents
        from app.tools.chat_attachments_tools import list_chat_attachments_metadata

        max_results = max(1, min(int(limit or 5), 10))
        search_value = (filename or "").strip().lower()

        chat_documents = await list_chat_attachments_metadata(user_id=user_id, chat_id=chat_id)
        indexed_documents = await list_user_documents(user_id=user_id)

        combined: list[dict[str, Any]] = []
        for document in chat_documents:
            combined.append(
                {
                    "id": str(document.get("id") or ""),
                    "filename": str(document.get("filename") or ""),
                    "source": "chat_upload",
                    "source_label": "Chat Upload",
                    "content_type": document.get("content_type"),
                    "size": document.get("size"),
                }
            )
        for document in indexed_documents:
            combined.append(
                {
                    "id": str(document.get("id") or ""),
                    "filename": str(document.get("filename") or ""),
                    "source": "indexed_document",
                    "source_label": "Indexed Document",
                    "created_at": document.get("created_at"),
                }
            )

        if search_value:
            scored: list[tuple[float, dict[str, Any]]] = []
            for document in combined:
                doc_name = str(document.get("filename") or "").strip()
                if not doc_name:
                    continue
                lowered_name = doc_name.lower()
                ratio = difflib.SequenceMatcher(None, search_value, lowered_name).ratio()
                if search_value in lowered_name:
                    ratio += 0.4
                scored.append((ratio, document))
            scored.sort(key=lambda item: (item[0], item[1].get("filename", "")), reverse=True)
            documents = [document for score, document in scored if score > 0][:max_results]
        else:
            documents = combined[:max_results]

        return {
            "ok": True,
            "query": filename or "",
            "documents": documents,
        }

    return [list_documents]


def get_chat_control_tools(state: AgentState) -> list:
    @tool("delegate_to_planner")
    def delegate_to_planner(execution_brief: str) -> dict:
        """Hand off the current request to the planner with a concise execution brief."""
        return {
            "ok": True,
            "chat_route": "planner",
            "execution_brief": execution_brief.strip(),
        }

    return [delegate_to_planner]


def get_registry_control_tools(state: AgentState) -> list:
    from app.agents.tool_registry import get_tool_registry

    registry = get_tool_registry()

    @tool("search_available_tools")
    async def search_available_tools(query: str, limit: int = 5) -> dict:
        """Search for additional tools semantically when the current selection is insufficient."""
        active_tool_ids = state.get("active_tool_ids") or []
        results = await registry.search(
            query,
            state,
            limit=max(1, min(int(limit or 5), 8)),
            exclude_ids=active_tool_ids,
        )
        matches = registry.describe([result.metadata.id for result in results])
        tool_ids = [result["id"] for result in matches]
        search_category = _infer_search_category(query, matches)

        same_category = state.get("last_tool_search_category") == search_category
        same_query = (state.get("last_tool_search_query") or "").strip().lower() == query.strip().lower()
        streak = int(state.get("consecutive_tool_searches") or 0)
        if same_category or same_query:
            streak += 1
        else:
            streak = 1

        if streak >= 3:
            user_response = interrupt(
                {
                    "question": _tool_search_interrupt_question(search_category, query),
                    "interrupt_type": "text_input",
                    "reason": "tool_search_needs_clarification",
                }
            )
            return {
                "ok": True,
                "query": query,
                "search_category": search_category,
                "selected_tool_ids": [],
                "matches": [],
                "needs_user_clarification": True,
                "user_response": user_response,
            }

        result = {
            "ok": True,
            "query": query,
            "search_category": search_category,
            "selected_tool_ids": tool_ids,
            "matches": matches,
        }
        logger.info(
            "search_available_tools query=%r active_tool_ids=%s selected_tool_ids=%s matches=%s",
            query,
            active_tool_ids,
            tool_ids,
            matches,
        )
        return result

    return [search_available_tools]


def get_chat_local_tools(state: AgentState) -> list:
    from app.tools.chat_attachments_tools import get_chat_attachment_read_tools

    user_id, chat_id = _state_ids(state)
    tools = get_chat_control_tools(state)
    tools.extend(get_clarification_tools(state))
    tools.extend(get_rag_tools(state))
    tools.extend(get_document_listing_tools(state))
    tools.extend(get_chat_attachment_read_tools(user_id=user_id, chat_id=chat_id))
    return tools


def get_planner_tools(state: AgentState) -> list:
    from app.tools.chat_attachments_tools import get_chat_attachment_read_tools

    user_id, chat_id = _state_ids(state)
    tools = get_clarification_tools(state)
    tools.extend(get_rag_tools(state))
    tools.extend(get_document_listing_tools(state))
    tools.extend(get_registry_control_tools(state))
    tools.extend(get_chat_attachment_read_tools(user_id=user_id, chat_id=chat_id))
    return tools


async def select_initial_tool_ids(state: AgentState) -> list[str]:
    from app.agents.tool_registry import get_tool_registry

    registry = get_tool_registry()
    execution_query = build_execution_tool_query(state)
    if not execution_query:
        return []

    results = await registry.search(execution_query, state, limit=6)
    return [result.metadata.id for result in results]


async def build_tools_for_agent(state: AgentState) -> list:
    """Build only the currently relevant tools for the execution agent."""
    from app.agents.tool_registry import get_tool_registry

    registry = get_tool_registry()
    active_tool_ids = list(state.get("active_tool_ids") or await select_initial_tool_ids(state))
    tools = get_registry_control_tools(state)
    tools.extend(registry.load(active_tool_ids, state))

    loaded_names = {tool.name for tool in tools}
    for core_tool in get_core_tools(state):
        if core_tool.name not in loaded_names:
            tools.append(core_tool)
            loaded_names.add(core_tool.name)

    return tools


def _parse_tool_message_content(content: Any) -> dict[str, Any] | None:
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            return json.loads(content)
        except Exception:
            try:
                parsed = ast.literal_eval(content)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return None
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
        if text_parts:
            try:
                return json.loads("".join(text_parts))
            except Exception:
                try:
                    parsed = ast.literal_eval("".join(text_parts))
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    return None
    return None


async def common_tool_node(state: AgentState) -> dict:
    """Execute the latest AIMessage tool calls."""
    active_agent = state.get("active_agent") or "executor"
    if active_agent == "chat":
        tools = get_chat_local_tools(state)
    elif active_agent == "planner":
        tools = get_planner_tools(state)
    else:
        tools = await build_tools_for_agent(state)
    node = ToolNode(tools)
    result = await node.ainvoke(state)

    active_tool_ids = list(state.get("active_tool_ids") or await select_initial_tool_ids(state))
    tool_calls_made = list(state.get("tool_calls_made") or [])
    result.setdefault("active_agent", active_agent)

    for message in result.get("messages") or []:
        if not isinstance(message, ToolMessage):
            continue

        if message.name and message.name not in tool_calls_made:
            tool_calls_made.append(message.name)

        payload = _parse_tool_message_content(message.content) or {}

        if message.name == "delegate_to_planner":
            execution_brief = str(payload.get("execution_brief") or "").strip()
            if not execution_brief:
                execution_brief = "Review the latest user request and plan the required operational steps."
            result["chat_route"] = "planner"
            result["execution_brief"] = execution_brief
            result["execution_plan"] = ""
            result["execution_steps"] = []
            result["execution_query"] = ""
            result["execution_completed"] = False
            result["planner_iterations"] = 0
            result["active_agent"] = "planner"
            result["active_tool_ids"] = []
            continue

        if message.name != "search_available_tools":
            continue

        search_category = str(payload.get("search_category") or "general")
        search_query = str(payload.get("query") or "").strip()

        if payload.get("needs_user_clarification"):
            result["last_tool_search_category"] = ""
            result["last_tool_search_query"] = ""
            result["consecutive_tool_searches"] = 0
            continue

        for tool_id in payload.get("selected_tool_ids") or []:
            if tool_id not in active_tool_ids:
                active_tool_ids.append(tool_id)

        same_category = state.get("last_tool_search_category") == search_category
        same_query = (state.get("last_tool_search_query") or "").strip().lower() == search_query.lower()
        previous_streak = int(state.get("consecutive_tool_searches") or 0)
        if same_category or same_query:
            consecutive_searches = previous_streak + 1
        else:
            consecutive_searches = 1

        result["last_tool_search_category"] = search_category
        result["last_tool_search_query"] = search_query
        result["consecutive_tool_searches"] = consecutive_searches

    called_search_tool = any(
        isinstance(message, ToolMessage) and message.name == "search_available_tools"
        for message in result.get("messages") or []
    )
    if not called_search_tool:
        result["last_tool_search_category"] = ""
        result["last_tool_search_query"] = ""
        result["consecutive_tool_searches"] = 0

    result["active_tool_ids"] = active_tool_ids
    result["tool_calls_made"] = tool_calls_made
    return result


def last_message_has_tool_calls(state: AgentState) -> bool:
    messages = state.get("messages") or []
    if not messages:
        return False
    last = messages[-1]
    return bool(getattr(last, "tool_calls", None))
