"""
memory.py — Chat memory utility (NOT a LangGraph node).

Implements an incremental sliding-window summarization strategy:

  Window design
  ─────────────
  Let W = memory_window_size (default 20, from settings)
  Let half = W // 2             → messages to summarize each time

  When total messages reach W:
    - Summarize messages [0 .. half + overlap]  (with overlap for continuity)
    - Keep messages [half .. W] raw (the recent half + overlap)
    - Combine with any existing summary so old context is never lost

  When total messages reach 2W (loaded since last summarization):
    - Summarize messages [half .. W + overlap] and prepend to existing summary
    - Keep messages [W .. 2W] raw
    - And so on...

  Overlap: ~15% of `half` (configurable via memory_overlap in settings).
  Overlap means the boundary messages appear in both the summarized chunk
  AND the raw window, so no information is abruptly cut off.

Public API
──────────
  prepare_messages_for_llm(messages, summary) -> list[BaseMessage]
      Returns [SystemMessage(summary)] + last (W//2) messages.
      This is what each agent passes to the LLM — a lean, token-efficient slice.

  run_summarization(messages, chat_id, existing_summary) -> str
      Applies the sliding-window strategy and persists the updated summary.
"""

import logging
import math
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage as LCAIMessage
from bson import ObjectId
from datetime import datetime
from app.config import get_settings
from app.services.llm_service import get_llm

logger = logging.getLogger(__name__)
settings = get_settings()

_SUMMARIZE_SYSTEM = """
You are a concise memory manager for a business AI assistant called BizAssist.

You will receive a conversation transcript and optionally a prior summary.
Produce an updated summary that preserves, with high accuracy:

  • User identity (name, company, role if mentioned)
  • Business context (industry, business model, stage)
  • Stated goals, preferences, or priorities
  • Key financial data (amounts, currencies, vendors, dates)
  • Spreadsheet or document references
  • Decisions made, confirmations given, or open follow-ups

Write 7-9 concise bullet points, past tense. Do NOT include generic filler.
If a prior summary is given, merge it with the new transcript — do not repeat information.
"""


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


def prepare_messages_for_llm(
    messages: list[BaseMessage],
    summary: str,
) -> list[BaseMessage]:
    """
    Return a token-efficient window of messages for the LLM.

    The LLM receives: [SystemMessage(summary)] + last (window_size // 2) messages.
    The full message list stays in MongoDB and is always shown to the user.
    """
    half = max(settings.memory_window_size // 2, 5)
    recent = messages[-half:] if len(messages) > half else list(messages)

    if summary:
        prefix = SystemMessage(
            content=f"[Earlier conversation — summarized for context]\n{summary}"
        )
        return [prefix] + recent

    return recent


async def run_summarization(
    messages: list[BaseMessage],
    chat_id: str,
    existing_summary: str,
) -> str:
    """
    Incremental sliding-window summarization.

    Only fires when len(messages) >= memory_window_size.
    Summarizes the OLDER half (with a small overlap) and combines it
    with the existing summary, so we never re-summarize from scratch.

    Returns the updated summary string (unchanged if threshold not met).
    """
    W = settings.memory_window_size
    messages_length=len(messages)
    if messages_length < W:
        return existing_summary

    if messages_length % W != 0:
        return existing_summary

    half = W // 2
    overlap = max(1, math.ceil(half * settings.memory_overlap))  # e.g. 15% of half

    # We include the overlap region so the summary captures boundary context.
    start = messages_length - W
    end = messages_length - half + overlap
    to_summarize = messages[start:end]

    transcript = _make_transcript(to_summarize)
    if not transcript.strip():
        return existing_summary

    # Build prompt — include prior summary so we combine incrementally
    if existing_summary:
        user_content = (
            f"Prior summary:\n{existing_summary}\n\n"
            f"New conversation segment to incorporate:\n{transcript}"
        )
    else:
        user_content = f"Conversation to summarize:\n{transcript}"

    try:
        llm = get_llm(model_name=settings.fast_model, temperature=0.1)
        resp = await llm.ainvoke([
            SystemMessage(content=_SUMMARIZE_SYSTEM),
            HumanMessage(content=user_content),
        ])
        new_summary = resp.content.strip()
        logger.info(
            f"[Memory] Summarized {len(to_summarize)} msgs (overlap={overlap}) "
            f"→ {len(new_summary)} chars | chat={chat_id}"
        )
    except Exception as exc:
        logger.warning(f"[Memory] Summarization failed: {exc}. Keeping existing summary.")
        return existing_summary

    # Persist to MongoDB so it's available on the next request
    if chat_id and new_summary:
        try:
            from app.database import chats_col
            await chats_col().update_one(
                {"_id": ObjectId(chat_id)},
                {"$set": {
                    "message_summary": new_summary,
                    "summarized_up_to": messages_length - half + overlap,   # track how far we've summarized
                    "updated_at": datetime.utcnow(),
                }},
            )
        except Exception as exc:
            logger.warning(f"[Memory] Failed to persist summary: {exc}")

    return new_summary
