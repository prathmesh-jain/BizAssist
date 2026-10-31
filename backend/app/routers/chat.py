import logging
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import Literal,Optional,Any
from app.dependencies import ChatUser
from app.db.base import get_db_session
from app.models.chat import ChatCreate, ChatPublic
from app.models.message import MessagePublic
from app.repositories import ChatRepository, MessageRepository, OAuthStateRepository
from app.services.chat_service import (
    build_attachment_event_text,
    extract_text_from_image_bytes,
    stream_agent_response,
)
from app.services.user_settings_service import (
    UserSettingsError,
    require_user_openai_api_key,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger(__name__)


ALLOWED_CHAT_ATTACHMENT_TYPES = {
    "application/pdf",
    "text/plain",
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}

MAX_CHAT_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB


def _chat_tmp_dir(chat_id: str) -> Path:
    base = Path(__file__).resolve().parents[2] / "tmp" / "chats" / str(chat_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _safe_filename(name: str) -> str:
    n = (name or "file").replace("\\", "_").replace("/", "_")
    return n[:200] or "file"


def _extract_text_from_pdf_bytes(raw: bytes) -> str:
    try:
        import io
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(raw))
        texts: list[str] = []
        for p in reader.pages:
            texts.append(p.extract_text() or "")
        return "\n".join(texts).strip()
    except Exception:
        logger.exception("chat.upload.pdf_text_extract_failed")
        return ""


async def _ensure_chat_enabled(user_id: str, session) -> None:
    try:
        await require_user_openai_api_key(user_id, session)
    except UserSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _store_chat_attachments(
    *,
    chat_id: str,
    user_id: str,
    files: list[UploadFile],
    session,
) -> list[dict]:
    attachments: list[dict] = []
    tmp_dir = _chat_tmp_dir(chat_id)

    logger.info("chat.upload.start chat_id=%s user_id=%s files=%s", chat_id, user_id, len(files or []))

    for f in files or []:
        ctype = (f.content_type or "application/octet-stream").lower()
        if ctype not in ALLOWED_CHAT_ATTACHMENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {f.filename}. Only PDF, images, and TXT files are allowed.",
            )
        try:
            raw = await f.read()
        except Exception:
            raw = b""

        if not raw:
            raise HTTPException(status_code=400, detail=f"Empty file upload: {f.filename}")
        if len(raw) > MAX_CHAT_ATTACHMENT_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File too large: {f.filename}. Maximum size is 10MB.",
            )

        att_id = uuid4().hex
        fname = _safe_filename(f.filename or "file")
        original_content_type = ctype

        extracted_text = ""
        if ctype == "application/pdf":
            extracted_text = _extract_text_from_pdf_bytes(raw)
        elif ctype == "text/plain":
            try:
                extracted_text = raw.decode("utf-8", errors="replace")
            except Exception:
                extracted_text = ""
        else:
            extracted_text = await extract_text_from_image_bytes(raw, original_content_type, user_id, session)

        stored_name = f"{att_id}.txt"
        path = tmp_dir / stored_name
        try:
            path.write_text(extracted_text or "", encoding="utf-8", errors="replace")
        except Exception as e:
            logger.exception("Failed to persist extracted text for attachment %s for chat %s: %s", fname, chat_id, e)
            continue

        logger.info(
            "chat.upload.saved chat_id=%s attachment_id=%s filename=%s content_type=text/plain chars=%s path=%s",
            chat_id,
            att_id,
            fname,
            len(extracted_text or ""),
            str(path),
        )

        attachments.append(
            {
                "id": att_id,
                "filename": fname,
                "content_type": "text/plain",
                "size": len(raw),
                "original_content_type": original_content_type,
                "url": f"/api/chat/{chat_id}/attachments/{att_id}",
                "stored_path": str(path),
            }
        )

    return attachments


async def _persist_user_message(
    *,
    chat_id: str,
    user_id: str,
    content: str,
    attachments: list[dict] | None = None,
    session,
) -> datetime:
    now = datetime.now(timezone.utc)
    stored_content = content.strip()
    if not stored_content and attachments:
        stored_content = build_attachment_event_text(attachments)

    await MessageRepository.create(
        session,
        chat_id=chat_id,
        user_id=user_id,
        role="user",
        content=stored_content,
        attachments=attachments,
    )

    await ChatRepository.update_timestamp(session, chat_id)
    return now


def _chat_doc_to_public(chat) -> dict:
    return {
        "id": chat.id,
        "title": chat.title,
        "created_at": chat.created_at,
        "updated_at": chat.updated_at,
    }


def _should_expose_message(m) -> bool:
    if m.role == "tool":
        return False

    interrupt = m.interrupt or {}
    if interrupt and not interrupt.get("is_pending"):
        return False

    content = str(m.content or "").strip()
    attachments = m.attachments or []
    tool_calls = m.tool_calls or []
    is_tool_only_assistant = (
        m.role == "assistant"
        and not content
        and not attachments
        and bool(tool_calls)
    )
    if is_tool_only_assistant:
        return False

    return True


@router.post("", response_model=ChatPublic)
async def create_chat(data: ChatCreate, user: ChatUser, session = Depends(get_db_session)):
    """Create a new chat session."""
    chat = await ChatRepository.create(
        session,
        organization_id=user.organization.id,
        created_by_user_id=user.user.id,
        title=data.title or "New Chat",
    )
    return ChatPublic(**_chat_doc_to_public(chat))


@router.get("", response_model=list[ChatPublic])
async def list_chats(user: ChatUser, session = Depends(get_db_session)):
    """List the current user's chats in their organization."""
    chats = await ChatRepository.list_for_user(session, user.organization.id, user.user.id)
    return [ChatPublic(**_chat_doc_to_public(c)) for c in chats]


@router.get("/{chat_id}/messages")
async def get_messages(
    chat_id: str,
    user: ChatUser,
    limit: int = 10,
    before: str | None = None,
    session = Depends(get_db_session),
):
    """
    Retrieve messages in a chat session with pagination.
    - limit: number of messages to return (default 10)
    - before: message ID to fetch messages before (for infinite scroll)
    Returns: {"messages": [...], "has_more": bool}
    """
    chat = await ChatRepository.get_by_id(session, chat_id, user.organization.id, user.user.id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    messages = await MessageRepository.list_by_chat(session, chat_id, limit, before)

    # Check if there are more messages
    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]  # remove the extra one

    # Reverse to return oldest first for the UI
    messages = list(reversed(messages))

    # Filter: Only send 'pending' interrupts to the frontend
    # If a message has an 'interrupt' field that is no longer pending, we skip it
    return {
        "messages": [
            MessagePublic(
                id=m.id,
                role=m.role,
                content=m.content,
                tool_calls=m.tool_calls,
                attachments=m.attachments,
                interrupt=m.interrupt,
                created_at=m.created_at,
            )
            for m in messages
            if _should_expose_message(m)
        ],
        "has_more": has_more,
    }


@router.post("/{chat_id}/message")
async def send_message(chat_id: str, body: dict, user: ChatUser, session = Depends(get_db_session)):
    """
    Send a user message and stream back the AI response via SSE.
    Body: {"content": "..."}
    """
    content = body.get("content", "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message content is required")

    chat = await ChatRepository.get_by_id(session, chat_id, user.organization.id, user.user.id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    await _ensure_chat_enabled(user.user.id, session)
    await _persist_user_message(chat_id=chat_id, user_id=user.user.id, content=content, session=session)

    return StreamingResponse(
        stream_agent_response(
            content, chat_id, user.user.id, user.organization.id, session, role=user.role
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{chat_id}/message_with_files")
async def send_message_with_files(
    chat_id: str,
    user: ChatUser,
    content: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    session = Depends(get_db_session),
):
    """Send a user message with file attachments (multipart/form-data) and stream back the AI response via SSE."""
    content = (content or "").strip()
    if not content and not files:
        raise HTTPException(status_code=400, detail="Message content or files are required")

    chat = await ChatRepository.get_by_id(session, chat_id, user.organization.id, user.user.id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    await _ensure_chat_enabled(user.user.id, session)
    attachments = await _store_chat_attachments(chat_id=chat_id, user_id=user.user.id, files=files, session=session)
    upload_note = build_attachment_event_text(attachments) if attachments else ""
    await _persist_user_message(
        chat_id=chat_id,
        user_id=user.user.id,
        content=content,
        attachments=attachments,
        session=session,
    )

    return StreamingResponse(
        stream_agent_response(
            content,
            chat_id,
            user.user.id,
            user.organization.id,
            session,
            role=user.role,
            user_message_context=upload_note if attachments else None,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{chat_id}/attachments/{attachment_id}")
async def get_chat_attachment(chat_id: str, attachment_id: str, user: ChatUser, session = Depends(get_db_session)):
    """Serve an uploaded attachment for preview/download."""
    chat = await ChatRepository.get_by_id(session, chat_id, user.organization.id, user.user.id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Find attachment metadata from messages
    messages = await MessageRepository.list_by_chat(session, chat_id, limit=1000)
    att = None
    for msg in messages:
        if msg.attachments:
            for a in msg.attachments:
                if a.get("id") == attachment_id:
                    att = a
                    break
        if att:
            break

    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Resolve stored file path by scanning temp dir for matching id prefix.
    tmp_dir = _chat_tmp_dir(chat_id)
    matches = list(tmp_dir.glob(f"{attachment_id}*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Attachment file missing")

    path = matches[0]
    media_type = att.get("content_type") or "application/octet-stream"
    filename = att.get("filename") or path.name
    return FileResponse(
        str(path),
        media_type=media_type,
        filename=filename,
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/{chat_id}")
async def delete_chat(chat_id: str, user: ChatUser, session = Depends(get_db_session)):
    """Hard-delete a chat session."""
    chat = await ChatRepository.get_by_id(session, chat_id, user.organization.id, user.user.id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Messages and OAuth states reference the chat, so remove them first.
    await MessageRepository.delete_by_chat(session, chat_id)
    await OAuthStateRepository.clear_chat_reference(session, chat_id)
    await ChatRepository.hard_delete(session, chat_id, user.organization.id, user.user.id)

    try:
        from app.services.tmp_cleanup_service import delete_chat_tmp_dir
        delete_chat_tmp_dir(chat_id)
    except Exception:
        logger.exception("Failed to delete tmp attachments for chat_id=%s", chat_id)
    return {"ok": True}


class RenameChatRequest(BaseModel):
    title: str

class ResolveInterruptRequest(BaseModel):
    action: Literal["accept", "reject"]
    data: Optional[Any] = None

@router.patch("/{chat_id}")
async def rename_chat(chat_id: str, body: RenameChatRequest, user: ChatUser, session = Depends(get_db_session)):
    """Rename a chat session."""
    new_title = body.title.strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="Title is required")

    chat = await ChatRepository.update_title(session, chat_id, user.organization.id, user.user.id, new_title)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    return ChatPublic(**_chat_doc_to_public(chat))

@router.post("/{chat_id}/interrupt-resolve")
async def resolve_chat_interrupt(chat_id: str, body: ResolveInterruptRequest, user: ChatUser, session = Depends(get_db_session)):
    """
    Resolve a pending interrupt and resume the graph.
    """
    action = body.action
    data = body.data

    chat = await ChatRepository.get_by_id(session, chat_id, user.organization.id, user.user.id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    await _ensure_chat_enabled(user.user.id, session)

    # Mark any pending interrupt as resolved instead of deleting (Audit Log)
    await MessageRepository.mark_interrupts_resolved(session, chat_id, action)
    logger.info(f"Marked interrupts as resolved (action: {action}) for chat {chat_id}")

    if action == "reject":
        now = datetime.now(timezone.utc)
        await MessageRepository.create(
            session,
            chat_id=chat_id,
            user_id=user.user.id,
            role="user",
            content=f"[User rejected the action]: {data}",
        )
        resume_value = False
    else:
        if isinstance(data, str) and data.strip():
            await _persist_user_message(chat_id=chat_id, user_id=user.user.id, content=data.strip(), session=session)
        resume_value = data if data is not None else True

    return StreamingResponse(
        stream_agent_response(
            None,
            chat_id,
            user.user.id,
            user.organization.id,
            session,
            role=user.role,
            is_resume=True,
            resume_value=resume_value
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{chat_id}/interrupt-resolve-with-files")
async def resolve_chat_interrupt_with_files(
    chat_id: str,
    user: ChatUser,
    content: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    session = Depends(get_db_session),
):
    """Resolve a pending file-upload interrupt and resume the graph from the same checkpoint."""
    content = (content or "").strip()
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    chat = await ChatRepository.get_by_id(session, chat_id, user.organization.id, user.user.id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    await _ensure_chat_enabled(user.user.id, session)

    await MessageRepository.mark_interrupts_resolved(session, chat_id, "accept")
    logger.info("Marked interrupts as resolved via file upload for chat %s", chat_id)

    attachments = await _store_chat_attachments(chat_id=chat_id, user_id=user.user.id, files=files, session=session)
    upload_note = build_attachment_event_text(attachments)
    stored_content = content or upload_note
    await _persist_user_message(
        chat_id=chat_id,
        user_id=user.user.id,
        content=stored_content,
        attachments=attachments,
        session=session,
    )

    resume_value = {
        "message": stored_content,
        "uploaded_attachments": [
            {
                "id": a["id"],
                "filename": a["filename"],
                "content_type": a["content_type"],
            }
            for a in attachments
        ],
        "instruction": "Use chat attachment tools to inspect uploaded files if needed.",
    }

    return StreamingResponse(
        stream_agent_response(
            None,
            chat_id,
            user.user.id,
            user.organization.id,
            session,
            role=user.role,
            is_resume=True,
            resume_value=resume_value,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
