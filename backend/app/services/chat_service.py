import json
import logging
import asyncio
import base64
import io
from datetime import datetime
from typing import AsyncGenerator
from bson import ObjectId

from app.database import chats_col, messages_col
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _extract_pdf_sample(file_bytes: bytes, max_pages: int = 2, max_chars: int = 2500) -> str:
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        texts: list[str] = []
        for p in reader.pages[: max(1, max_pages)]:
            texts.append(p.extract_text() or "")
        text = "\n".join(texts).strip()
    except Exception:
        text = ""

    if not text:
        return ""
    return text[:max_chars]


def _extract_txt_sample(file_bytes: bytes, max_chars: int = 2500) -> str:
    try:
        text = file_bytes.decode("utf-8", errors="replace").strip()
    except Exception:
        text = ""
    return text[:max_chars] if text else ""


async def _extract_image_sample(file_bytes: bytes, content_type: str) -> str:
    from langchain_core.messages import SystemMessage, HumanMessage
    from app.services.llm_service import get_llm

    b64 = base64.b64encode(file_bytes).decode("utf-8")
    llm = get_llm(model_name=settings.primary_model, temperature=0)
    prompt = (
        "You are given an image uploaded by a user. "
        "Extract all visible text from the image in structured format "
        "Return plain text only."
    )

    resp = await llm.ainvoke(
        [
            SystemMessage(content=prompt),
            HumanMessage(
                content=[
                    {"type": "text", "text": "Analyze this image:"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{content_type};base64,{b64}",
                            "detail": "high",
                        },
                    },
                ]
            ),
        ]
    )
    return (resp.content or "").strip()[:1200]


async def extract_text_from_image_bytes(file_bytes: bytes, content_type: str) -> str:
    """Extract plain text from an uploaded image using an LLM.

    This is used in the chat attachment upload flow so we can store an extracted
    text artifact (as .txt) and keep the downstream pipeline identical to PDFs.
    """
    if not file_bytes:
        return ""
    ctype = (content_type or "image/*").lower()
    if not ctype.startswith("image/"):
        return ""
    try:
        return await _extract_image_sample(file_bytes, ctype)
    except Exception:
        logger.exception("Failed to extract text from image bytes")
        return ""


async def _build_attachments_prompt_context(attachment_files: list[dict]) -> tuple[str, list[dict]]:
    if not attachment_files:
        return "", []

    attachment_samples: list[dict] = []
    for a in attachment_files:
        filename = a.get("filename") or "file"
        content_type = (a.get("content_type") or "application/octet-stream").lower()
        stored_path = a.get("stored_path")
        if not stored_path:
            continue

        try:
            raw = open(stored_path, "rb").read()
        except Exception:
            raw = b""

        sample_text = ""
        if content_type == "application/pdf":
            sample_text = _extract_pdf_sample(raw)
        elif content_type == "text/plain":
            sample_text = _extract_txt_sample(raw)
        elif content_type.startswith("image/"):
            try:
                sample_text = await _extract_image_sample(raw, content_type)
            except Exception:
                sample_text = ""

        attachment_samples.append(
            {
                "filename": filename,
                "content_type": content_type,
                "size": len(raw),
                "sample": sample_text,
            }
        )

    payload = {
        "attachments": attachment_samples,
        "note": "Samples are partial extracts; do not assume missing fields are absent.",
    }
    attachments_prompt_context = "\n\n" + "ATTACHMENTS_CONTEXT:\n" + json.dumps(payload, ensure_ascii=False)
    return attachments_prompt_context, attachment_samples


async def generate_chat_title(first_message: str) -> str:
    """Generate a short title from the first user message."""
    from app.services.llm_service import get_llm

    llm = get_llm(model_name=settings.nano_model, temperature=0)
    response = await llm.ainvoke([
        {"role": "system", "content": (
            "Generate a short, descriptive title (3–5 words) for a business conversation "
            "based on the user's first message. Return only the title — no punctuation, no quotes."
        )},
        {"role": "user", "content": first_message},
    ])
    return (response.content.strip()[:60]) or "New Chat"


async def stream_agent_response(
    user_message: str,
    chat_id: str,
    user_id: str,
    attachment_files: list[dict] | None = None,
    attachments_context_override: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Pre-processes memory, builds LangGraph state, and streams SSE events.

    Fix for blank responses:
    - We no longer filter tokens by node name, because `on_node_start`
      event metadata is not reliable across LangGraph versions.
    - Instead we use a simple blacklist: skip tokens ONLY from the
      guardrail and planner LLMs (cheap, non-streaming models).
      We detect these via the `tags` on the event, which LangChain
      sets based on the LLM call site.
    - As a belt-and-suspenders fallback, on_chain_end / on_node_end
      capture any non-streamed final content.
    """
    from app.agents.graph import get_compiled_graph
    from app.agents.memory import run_summarization
    from langchain_core.messages import HumanMessage, AIMessage as LCAIMessage

    graph = get_compiled_graph()

    # ── 1. Load chat doc and persisted summary ───────────────────────────
    chat_doc = await chats_col().find_one({"_id": ObjectId(chat_id)})
    persisted_summary: str = (chat_doc or {}).get("message_summary", "") if chat_doc else ""

    # ── 2. Load recent history from MongoDB ──────────────────────────────
    # We load only settings.memory_window_size messages — the sliding-window
    # logic in run_summarization handles older context via the summary.
    load_limit = max(settings.memory_window_size, 20)
    prev_cursor = messages_col().find({"chat_id": chat_id}, sort=[("created_at", 1)])
    prev_msgs = await prev_cursor.to_list(length=load_limit)

    history_messages = []
    for m in prev_msgs:
        if m["role"] == "user":
            history_messages.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            history_messages.append(LCAIMessage(content=m["content"]))

    attachments_prompt_context = attachments_context_override or ""
    if not attachments_prompt_context and attachment_files:
        try:
            attachments_prompt_context, _attachment_samples = await _build_attachments_prompt_context(attachment_files)
        except Exception:
            logger.exception("Failed to build attachments context")
            attachments_prompt_context = ""

    combined_user = (user_message or "").strip()
    if not combined_user and attachments_prompt_context:
        combined_user = "User uploaded files."
    if attachments_prompt_context:
        combined_user = (combined_user + attachments_prompt_context).strip()

    all_messages = history_messages + [HumanMessage(content=combined_user)]

    # IMPORTANT: Do not persist attachment extracted text into chat memory summary.
    # We strip the ATTACHMENTS_CONTEXT block before summarization, but keep it for the agent run.
    summarization_messages = []
    marker = "ATTACHMENTS_CONTEXT:"
    for m in all_messages:
        try:
            if isinstance(m, HumanMessage) and isinstance(getattr(m, "content", None), str):
                c = m.content
                if marker in c:
                    c = c.split(marker, 1)[0].strip()
                    if not c:
                        c = "User uploaded files."
                summarization_messages.append(HumanMessage(content=c))
            else:
                summarization_messages.append(m)
        except Exception:
            summarization_messages.append(m)

    # ── 3. Sliding-window summarization (before graph runs) ──────────────
    active_summary = await run_summarization(
        messages=summarization_messages,
        chat_id=chat_id,
        existing_summary=persisted_summary,
    )

    # ── 4. Build LangGraph initial state ─────────────────────────────────
    state = {
        "messages": all_messages,
        "intent": "",
        "is_safe": True,
        "guardrail_reason": "",
        "refusal_message": "",
        "retrieved_context": "",
        "invoice_data": None,
        "user_id": user_id,
        "chat_id": chat_id,
        "confirmed": False,
        "spreadsheet_id": "",
        "sheet_name": "Expenses",
        "next": "",
        "tool_calls_made": [],
        "message_summary": active_summary,
    }

    full_response = ""
    tool_calls_made: list[str] = []
    tool_calls_meta: list[dict] = []
    in_planning_node = False  # True while guardrail or planner is the active node

    yielded_any = False
    max_attempts = max(int(getattr(settings, "agent_run_retries", 2) or 2), 1)

    for attempt in range(1, max_attempts + 1):
        try:
            async for event in graph.astream_events(state, version="v2"):
                kind = event.get("event", "")
                name = event.get("name", "")
                metadata = event.get("metadata", {})
                langgraph_node = metadata.get("langgraph_node", "")

                # ── Node lifecycle telemetry (used for sources) ──────────
                if kind == "on_chain_start" and langgraph_node == "document_query":
                    # Retrieval agent runs RAG-only in this codebase.
                    # We emit tool_start here for a consistent UI pill, and emit citations on_chain_end
                    # once we can see which documents were actually retrieved.
                    yield f"data: {json.dumps({'type': 'tool_start', 'tool': 'RAG Retrieval'})}\n\n"

                # ── Track which node we're in ─────────────────────────────
                if kind == "on_chain_start" and langgraph_node:
                    in_planning_node = langgraph_node in ("guardrail", "planner")

                # ── Capture streaming tokens from execution agents ────────
                if kind == "on_chat_model_stream":
                    # Skip tokens from planning nodes (guardrail, planner)
                    if in_planning_node:
                        continue

                    chunk = event.get("data", {}).get("chunk")
                    token = ""
                    if chunk:
                        if hasattr(chunk, "content"):
                            token = chunk.content or ""
                        elif isinstance(chunk, dict):
                            token = chunk.get("content", "")

                    if token:
                        yielded_any = True
                        full_response += token
                        yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

                # ── Capture non-streamed output (e.g., non-streaming LLM calls) ────
                # Some LangGraph/LangChain versions omit langgraph_node metadata on end events.
                # Fall back to the event name to avoid swallowing the final assistant message.
                elif kind == "on_chain_end":
                    node_name = (langgraph_node or name or "").strip().lower()
                    if node_name and node_name in ("guardrail", "planner"):
                        continue

                    # document_query finished: mark our synthetic tool as completed and persist metadata
                    if node_name == "document_query":
                        # Extract citations from the retrieval node output.
                        citations: list[str] = []
                        try:
                            output = event.get("data", {}).get("output", {})
                            # retrieval_node returns {"retrieved_context": "..."}
                            if isinstance(output, dict):
                                retrieved_context = output.get("retrieved_context") or ""
                                if isinstance(retrieved_context, str) and retrieved_context:
                                    # rag_service formats chunks with: [Source: filename]
                                    citations = list(dict.fromkeys(re.findall(r"\[Source:\s*([^\]]+)\]", retrieved_context)))
                                    citations = [c.strip() for c in citations if c and c.strip()]
                        except Exception:
                            citations = []

                        # Emit a 'source' event for the UI with document-level citations.
                        if citations:
                            yield f"data: {json.dumps({'type': 'source', 'name': 'RAG Retrieval', 'citations': citations[:6]})}\n\n"
                        tool_calls_made.append("RAG Retrieval")
                        tool_calls_meta.append({"name": "RAG Retrieval", "citations": citations[:6]})
                        yield f"data: {json.dumps({'type': 'tool_end', 'tool': 'RAG Retrieval'})}\n\n"

                    if not full_response:
                        output = event.get("data", {}).get("output", {})
                        # LangGraph wraps node output in {"messages": [...]} 
                        if isinstance(output, dict):
                            msgs = output.get("messages", [])
                            if msgs:
                                content = getattr(msgs[-1], "content", None)
                                if content:
                                    yielded_any = True
                                    full_response = str(content)
                                    yield f"data: {json.dumps({'type': 'token', 'content': full_response})}\n\n"

                # ── Tool telemetry ────────────────────────────────────────
                elif kind == "on_tool_start":
                    tool_name = name or event.get("data", {}).get("name", "tool")
                    tool_calls_made.append(tool_name)
                    yield f"data: {json.dumps({'type': 'tool_start', 'tool': tool_name})}\n\n"

                elif kind == "on_tool_end":
                    tool_name = name or "tool"
                    yield f"data: {json.dumps({'type': 'tool_end', 'tool': tool_name})}\n\n"

            # If we got anything, don't retry
            if full_response:
                break

            # No output at all — allow retry only if we didn't stream anything
            if not yielded_any and attempt < max_attempts:
                logger.exception(
                    "Agent run produced no output; retrying (attempt %s/%s). chat_id=%s user_id=%s",
                    attempt,
                    max_attempts,
                    chat_id,
                    user_id,
                )
                await asyncio.sleep(0.2)
                continue

        except Exception:
            # If streaming started, we must not retry because the client already received partial output.
            logger.exception(
                "Error streaming agent response (attempt %s/%s). chat_id=%s user_id=%s",
                attempt,
                max_attempts,
                chat_id,
                user_id,
            )
            if not yielded_any and attempt < max_attempts:
                await asyncio.sleep(0.2)
                continue

            err_msg = "I'm sorry, something went wrong. Please try again."
            if not full_response:
                full_response = err_msg
                yield f"data: {json.dumps({'type': 'token', 'content': err_msg})}\n\n"
            break

    # ── 5. Persist assistant message ─────────────────────────────────────
    if full_response:
        persisted_tool_calls = tool_calls_meta or ([{"name": t} for t in tool_calls_made] if tool_calls_made else None)
        await messages_col().insert_one({
            "chat_id": chat_id,
            "user_id": user_id,
            "role": "assistant",
            "content": full_response,
            "tool_calls": persisted_tool_calls,
            "created_at": datetime.utcnow(),
        })

        user_msg_count = await messages_col().count_documents(
            {"chat_id": chat_id, "role": "user"}
        )
        if user_msg_count == 1:
            title = await generate_chat_title(user_message)
            await chats_col().update_one(
                {"_id": ObjectId(chat_id)},
                {"$set": {"title": title, "updated_at": datetime.utcnow()}},
            )
            yield f"data: {json.dumps({'type': 'title_update', 'chat_id': chat_id, 'title': title})}\n\n"
    else:
        # Nothing came through at all - last-resort log (include context)
        logger.error(
            "No response generated for chat_id=%s user_id=%s. tool_calls=%s yielded_any=%s",
            chat_id,
            user_id,
            tool_calls_made,
            yielded_any,
        )

    yield f"data: {json.dumps({'type': 'done'})}\n\n"
