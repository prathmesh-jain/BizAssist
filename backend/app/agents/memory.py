import logging
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage as LCAIMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from app.config import get_settings
from app.services.llm_service import get_llm
from app.agents.state import AgentState

logger = logging.getLogger(__name__)
settings = get_settings()

_SUMMARIZE_SYSTEM = """
Summarize the business conversation.
Capture: User goals, financial data, spreadsheet/doc references, and decisions.
Merge with prior summary. Keep it concise (bullet points).
"""

SUMMARY_BLOCK_PREFIX = "[Earlier Conversation Summary]"


def _make_transcript(messages: list[BaseMessage]) -> str:
    lines = []
    for m in messages:
        if isinstance(m, HumanMessage):
            role = "User"
        elif isinstance(m, LCAIMessage):
            role = "Assistant"
        elif isinstance(m, SystemMessage):
            continue
        else:
            role = m.type.capitalize()
        content = str(m.content or "")[:600]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def build_summary_message(summary: str) -> SystemMessage:
    return SystemMessage(content=f"{SUMMARY_BLOCK_PREFIX}\n{summary.strip()}")


def _is_summary_message(message: BaseMessage) -> bool:
    return isinstance(message, SystemMessage) and str(getattr(message, "content", "") or "").startswith(SUMMARY_BLOCK_PREFIX)


async def summarization_node(state: AgentState) -> dict:
    """Keep checkpoint memory compact with a rolling graph-state summary.

    The user-visible chat history remains in Mongo messages. This node only
    trims LangGraph checkpoint state: whenever the raw window reaches 30
    messages, summarize the oldest 10 and keep the most recent 20.
    """
    messages = list(state.get("messages") or [])
    if len(messages) < 30:
        return {}

    to_summarize = messages[:-20]
    keep = [message for message in messages[-20:] if not _is_summary_message(message)]
    existing_summary = state.get("message_summary") or ""
    transcript = _make_transcript(to_summarize)
    if not transcript.strip():
        replacement_messages = [RemoveMessage(id=REMOVE_ALL_MESSAGES)]
        if existing_summary.strip():
            replacement_messages.append(build_summary_message(existing_summary))
        replacement_messages.extend(keep)
        return {"messages": replacement_messages}

    if existing_summary:
        user_content = (
            f"Prior summary:\n{existing_summary}\n\n"
            f"New conversation segment to incorporate:\n{transcript}"
        )
    else:
        user_content = f"Conversation to summarize:\n{transcript}"

    try:
        llm = await get_llm(
            user_id=state["user_id"],
            purpose="fast",
            temperature=0.1,
        )
        resp = await llm.ainvoke(
            [
                SystemMessage(content=_SUMMARIZE_SYSTEM),
                HumanMessage(content=user_content),
            ]
        )
        new_summary = (resp.content or "").strip() or existing_summary
    except Exception as exc:
        logger.warning("Graph memory summarization failed: %s", exc)
        new_summary = existing_summary

    return {
        "message_summary": new_summary,
        "messages": [
            RemoveMessage(id=REMOVE_ALL_MESSAGES),
            build_summary_message(new_summary),
            *keep,
        ],
    }
