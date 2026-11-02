import json
import logging
import asyncio
import base64
import re
import time
from datetime import datetime, timezone
from typing import AsyncGenerator
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.repositories import ChatRepository, MessageRepository
from app.db.base import session_scope

logger = logging.getLogger(__name__)
settings = get_settings()

# Strong references so background tasks aren't garbage-collected mid-run.
_background_tasks: set[asyncio.Task] = set()


async def _extract_image_sample(file_bytes: bytes, content_type: str, user_id: str, session: AsyncSession) -> str:
    from langchain_core.messages import SystemMessage, HumanMessage
    from app.services.llm_service import get_llm

    b64 = base64.b64encode(file_bytes).decode("utf-8")
    llm = await get_llm(user_id=user_id, purpose="primary", temperature=0, session=session)
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
    return (resp.content or "").strip()


async def extract_text_from_image_bytes(
    file_bytes: bytes,
    content_type: str,
    user_id: str,
    session: AsyncSession,
) -> str:
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
        return await _extract_image_sample(file_bytes, ctype, user_id, session)
    except Exception:
        logger.exception("Failed to extract text from image bytes")
        return ""


def build_attachment_event_text(attachments: list[dict]) -> str:
    names = [
        (a.get("filename") or "file").strip()
        for a in attachments
        if isinstance(a, dict) and (a.get("filename") or "").strip()
    ]
    if not names:
        return "User uploaded files."
    return "User uploaded file(s): " + ", ".join(names[:5])


async def generate_chat_title(first_message: str, user_id: str, session: AsyncSession) -> str:
    """Generate a short title from the first user message."""
    from app.services.llm_service import get_llm

    llm = await get_llm(user_id=user_id, purpose="fast", temperature=0, session=session)
    response = await llm.ainvoke([
        {"role": "system", "content": (
            "Generate a short, descriptive title (3–5 words) for a business conversation "
            "based on the user's first message. Return only the title — no punctuation, no quotes."
        )},
        {"role": "user", "content": first_message},
    ])
    return (response.content.strip()[:60]) or "New Chat"


def new_messages_since(before: list, after: list) -> list:
    """Messages added during a run, by id. Position can't be used: chat removes its tool
    exchange and the summarizer replaces old messages, so the list can shrink during a run."""
    seen = {getattr(m, "id", None) for m in before}
    return [m for m in after if getattr(m, "id", None) not in seen]


async def _title_new_chat(first_message: str, chat_id: str, user_id: str, organization_id: str) -> str | None:
    """Generate and save a chat title in its own session. A failure just keeps the default title."""
    try:
        async with session_scope() as session:
            title = await generate_chat_title(first_message, user_id, session)
            await ChatRepository.update_title(session, chat_id, organization_id, user_id, title)
            return title
    except Exception:
        logger.warning("Chat title generation failed for chat %s", chat_id, exc_info=True)
        return None


async def _title_event(title_task: asyncio.Task | None, chat_id: str, *, timeout: float = 3.0) -> str | None:
    """SSE event for the new title. Waits briefly; a slower title still saves and shows on reload."""
    if title_task is None:
        return None
    done, _ = await asyncio.wait({title_task}, timeout=timeout)
    title = title_task.result() if done else None
    if not title:
        return None
    return f"data: {json.dumps({'type': 'title_update', 'chat_id': chat_id, 'title': title})}\n\n"


async def stream_agent_response(
    user_message: str | None,
    chat_id: str,
    user_id: str,
    organization_id: str,
    role: str = "viewer",
    **kwargs,
) -> AsyncGenerator[str, None]:
    """SSE generator for an agent run. It owns its DB session: the request's session is
    committed before the response starts, so work done while streaming needs its own."""
    async with session_scope() as session:
        async for event in _stream_agent_response(
            user_message, chat_id, user_id, organization_id, session, role=role, **kwargs
        ):
            yield event


async def _stream_agent_response(
    user_message: str | None,
    chat_id: str,
    user_id: str,
    organization_id: str,
    session: AsyncSession,
    role: str = "viewer",
    user_message_context: str | None = None,
    is_resume: bool = False,
    resume_value: str | bool | dict | None = None,
) -> AsyncGenerator[str, None]:
    """
    Pre-processes memory, builds LangGraph state, and streams SSE events.
    """
    from app.agents.graph import get_compiled_graph
    from langchain_core.messages import HumanMessage

    graph = get_compiled_graph()

    from app.services.business_profile_service import business_context_text
    from app.services.google_calendar_service import connection_status

    business_context = await business_context_text(session, organization_id)
    calendar_status = await connection_status(session, user_id=user_id, organization_id=organization_id)
    user_timezone = calendar_status.get("timezone") or ""

    combined_user = (user_message or "").strip()
    if user_message_context:
        combined_user = (combined_user + "\n\n" + user_message_context.strip()).strip()
    graph_messages = [HumanMessage(content=combined_user)] if combined_user else []

    initial_state = {
        "messages": graph_messages,
        "user_id": user_id,
        "chat_id": chat_id,
        "organization_id": organization_id,
        "role": role,
        "business_context": business_context,
        "user_timezone": user_timezone,
    }

    full_response = ""
    yielded_any = False
    started_at = last_step_at = time.monotonic()
    step_timings: list[str] = []
    first_token_ms: int | None = None

    # Organization-aware thread ID
    thread_id = f"{organization_id}_{chat_id}"
    config = {"configurable": {"thread_id": thread_id}}

    # Get current state before run to calculate new messages later
    pre_run_state = await graph.aget_state(config)
    pre_run_messages = pre_run_state.values.get("messages") or []
    pre_run_msgs_count = len(pre_run_messages)

    # Name a new chat alongside the run so the answer never waits for it.
    title_task: asyncio.Task | None = None
    if user_message and not is_resume and pre_run_msgs_count == 0:
        title_task = asyncio.create_task(_title_new_chat(user_message, chat_id, user_id, organization_id))
        _background_tasks.add(title_task)
        title_task.add_done_callback(_background_tasks.discard)

    # Use Command(resume=...) if resuming, otherwise use initial_state
    # On resume, refresh the role too so a demotion during a pending interrupt takes effect.
    input_data = initial_state if not is_resume else Command(resume=resume_value, update={"role": role, "business_context": business_context, "user_timezone": user_timezone})

    max_attempts = 1 if is_resume else max(int(getattr(settings, "agent_run_retries", 2) or 2), 1)

    for attempt in range(1, max_attempts + 1):
        # A retry resumes from the last checkpoint; re-sending the input would duplicate the user message.
        attempt_input = input_data if attempt == 1 else None
        try:
            async for part in graph.astream(
                attempt_input,
                config=config,
                stream_mode=["messages", "updates"],
                version="v2"
            ):
                chunk_type = part["type"]
                data = part["data"]

                if chunk_type == "updates":
                    for node_name, node_output in data.items():
                        now = time.monotonic()
                        step_timings.append(f"{node_name}={int((now - last_step_at) * 1000)}ms")
                        last_step_at = now
                        # Detect Interrupts
                        if node_name == "__interrupt__":
                            if node_output:
                                interrupt_obj = node_output[0]
                                val = interrupt_obj.value
                                is_dict = isinstance(val, dict)
                                interrupt_payload = {
                                    "id": interrupt_obj.id,
                                    "question": val if isinstance(val, str) else (val.get("question") if is_dict else "Approval required"),
                                    "interrupt_type": val.get("interrupt_type", "accept_decline") if is_dict else "accept_decline",
                                    "action_required": val.get("action_required") if is_dict else None,
                                    "data": val.get("data") if is_dict else None,
                                    "is_pending": True
                                }

                                # Persist to DB
                                try:
                                    await MessageRepository.mark_interrupts_resolved(session, chat_id, "stale")
                                    await MessageRepository.create(
                                        session,
                                        chat_id=chat_id,
                                        user_id=user_id,
                                        role="assistant",
                                        content="",
                                        interrupt=interrupt_payload,
                                    )
                                except Exception:
                                    logger.exception("Failed to persist interrupt")

                                yield f"data: {json.dumps({'type': 'interrupt', 'interrupt_id': interrupt_obj.id, 'content': interrupt_payload})}\n\n"
                                title_event = await _title_event(title_task, chat_id)
                                if title_event:
                                    yield title_event
                                return

                        # Capture Tool Calls & Citations
                        if node_name in ("chat", "planner", "executor") and isinstance(node_output, dict):
                            progress_event = node_output.get("progress_event")
                            if isinstance(progress_event, dict):
                                yield f"data: {json.dumps({'type': 'status', 'content': progress_event})}\n\n"
                            if "messages" in node_output:
                                for m in node_output["messages"]:
                                    if hasattr(m, "tool_calls") and m.tool_calls:
                                        for tc in m.tool_calls:
                                            yield f"data: {json.dumps({'type': 'tool_start', 'name': tc['name']})}\n\n"

                                    if hasattr(m, "content") and m.content:
                                        citations = list(dict.fromkeys(re.findall(r"\[Source:\s*([^\]]+)\]", str(m.content))))
                                        if citations:
                                            yield f"data: {json.dumps({'type': 'source', 'name': 'RAG Retrieval', 'citations': citations[:6]})}\n\n"

                        if node_name == "tools" and isinstance(node_output, dict):
                            for m in node_output.get("messages") or []:
                                if getattr(m, "type", "") == "tool" and getattr(m, "name", None):
                                    yield f"data: {json.dumps({'type': 'tool_end', 'name': m.name})}\n\n"

                elif chunk_type == "messages":
                    msg, metadata = data
                    if metadata.get("langgraph_node") in ("chat", "unsafe"):
                        token = msg.content
                        if token:
                            if first_token_ms is None:
                                first_token_ms = int((time.monotonic() - started_at) * 1000)
                            yielded_any = True
                            full_response += token
                            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

            break

        except Exception as e:
            logger.exception(f"Error in agent stream (attempt {attempt}/{max_attempts})")
            if not yielded_any and attempt < max_attempts:
                await asyncio.sleep(0.2)
                continue

            if not yielded_any:
                # Provide specific error messages for common issues
                error_msg = str(e)
                error_msg_lower = error_msg.lower()

                if "model_not_found" in error_msg_lower or "has been deprecated" in error_msg_lower:
                    model = re.search(r"model `([^`]+)`", error_msg)
                    err_msg = (
                        f"The model {model.group(1) + ' ' if model else ''}is not available on your OpenAI account "
                        "anymore. Choose another model in Settings."
                    )
                elif "invalid_api_key" in error_msg_lower or "incorrect api key" in error_msg_lower or "api key" in error_msg_lower:
                    err_msg = "Invalid API key. Please check your API key in Settings."
                elif "authentication" in error_msg_lower or "unauthorized" in error_msg_lower:
                    err_msg = "Authentication failed. Please check your API key in Settings."
                elif "rate limit" in error_msg_lower or "quota" in error_msg_lower:
                    err_msg = "API rate limit exceeded. Please try again later."
                elif "network" in error_msg_lower or "connection" in error_msg_lower:
                    err_msg = "Network error. Please check your internet connection."
                else:
                    err_msg = "Something went wrong. Please try again."
                yield f"data: {json.dumps({'type': 'error', 'content': err_msg})}\n\n"
            break

    logger.info(
        "agent.run.timing chat_id=%s total=%sms first_token=%sms steps=%s",
        chat_id, int((time.monotonic() - started_at) * 1000), first_token_ms, " ".join(step_timings),
    )

    # ── 5. Persist assistant message(s) ─────────────────────────────────────
    final_state = await graph.aget_state(config)
    all_msgs = final_state.values.get("messages") or []
    new_msgs = new_messages_since(pre_run_messages, all_msgs)

    if new_msgs:
        for m in new_msgs:
            # Skip the run's own human message: the router already persisted it.
            # Compare by content, since the checkpointed copy has a LangGraph-assigned id.
            if not is_resume and m.type == "human" and m.content == combined_user:
                continue
            if m.type in ("tool", "system"):  # tool output and summary blocks aren't chat history
                continue
            if m.type == "ai" and bool(getattr(m, "tool_calls", None)):
                continue
            if m.type == "ai":
                role = "assistant"
            elif m.type == "human":
                role = "user"
            else:
                role = "system"

            m_tool_calls = [{"name": tc["name"]} for tc in m.tool_calls] if hasattr(m, "tool_calls") and m.tool_calls else None

            await MessageRepository.create(
                session,
                chat_id=chat_id,
                user_id=user_id,
                role=role,
                content=m.content,
                tool_calls=m_tool_calls,
            )

    title_event = await _title_event(title_task, chat_id)
    if title_event:
        yield title_event

    yield f"data: {json.dumps({'type': 'done'})}\n\n"
