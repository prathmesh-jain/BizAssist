import logging
from pathlib import Path
from uuid import uuid4
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, FileResponse
from bson import ObjectId
from pydantic import BaseModel
from typing import Literal,Optional,Any
from app.dependencies import CurrentUser
from app.database import chats_col, messages_col
from app.models.chat import ChatCreate, ChatPublic
from app.models.message import MessagePublic
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


async def _ensure_chat_enabled(user_id: str) -> None:
    try:
        await require_user_openai_api_key(user_id)
    except UserSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _store_chat_attachments(
    *,
    chat_id: str,
    user_id: str,
    files: list[UploadFile],
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
            extracted_text = await extract_text_from_image_bytes(raw, original_content_type, user_id)

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
) -> datetime:
    now = datetime.utcnow()
    stored_content = content.strip()
    if not stored_content and attachments:
        stored_content = build_attachment_event_text(attachments)

    await messages_col().insert_one({
        "chat_id": chat_id,
        "user_id": user_id,
        "role": "user",
        "content": stored_content,
        "tool_calls": None,
        "attachments": [
            {
                k: a[k]
                for k in (
                    "id",
                    "filename",
                    "content_type",
                    "size",
                    "url",
                    "stored_path",
                    "original_content_type",
                )
                if k in a
            }
            for a in (attachments or [])
        ] or None,
        "created_at": now,
    })

    await chats_col().update_one(
        {"_id": ObjectId(chat_id)},
        {"$set": {"updated_at": now}},
    )
    return now


def _chat_doc_to_public(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "title": doc.get("title", "New Chat"),
        "created_at": doc["created_at"],
        "updated_at": doc["updated_at"],
    }


def _should_expose_message(m: dict) -> bool:
    if m.get("role") == "tool":
        return False

    interrupt = m.get("interrupt") or {}
    if interrupt and not interrupt.get("is_pending"):
        return False

    content = str(m.get("content") or "").strip()
    attachments = m.get("attachments") or []
    tool_calls = m.get("tool_calls") or []
    is_tool_only_assistant = (
        m.get("role") == "assistant"
        and not content
        and not attachments
        and bool(tool_calls)
    )
    if is_tool_only_assistant:
        return False

    return True


@router.post("", response_model=ChatPublic)
async def create_chat(data: ChatCreate, user: CurrentUser):
    """Create a new chat session."""
    now = datetime.utcnow()
    doc = {
        "user_id": user.id,
        "title": data.title or "New Chat",
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
    }
    result = await chats_col().insert_one(doc)
    doc["_id"] = result.inserted_id
    return ChatPublic(**_chat_doc_to_public(doc))


@router.get("", response_model=list[ChatPublic])
async def list_chats(user: CurrentUser):
    """List all chats for the current user."""
    cursor = chats_col().find(
        {"user_id": user.id},
        sort=[("updated_at", -1)],
    )
    chats = await cursor.to_list(length=100)
    return [ChatPublic(**_chat_doc_to_public(c)) for c in chats]


@router.get("/{chat_id}/messages")
async def get_messages(
    chat_id: str,
    user: CurrentUser,
    limit: int = 10,
    before: str | None = None,
):
    """
    Retrieve messages in a chat session with pagination.
    - limit: number of messages to return (default 10)
    - before: message ID to fetch messages before (for infinite scroll)
    Returns: {"messages": [...], "has_more": bool}
    """
    chat = await chats_col().find_one({"_id": ObjectId(chat_id), "user_id": user.id})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    query = {"chat_id": chat_id}
    
    # If 'before' is provided, fetch older messages
    if before:
        try:
            before_msg = await messages_col().find_one({"_id": ObjectId(before)})
            if before_msg:
                query["created_at"] = {"$lt": before_msg["created_at"]}
        except Exception:
            pass

    cursor = messages_col().find(
        query,
        sort=[("created_at", -1)],  # newest first for pagination
        limit=limit + 1,  # fetch one extra to check if there are more
    )
    msgs = await cursor.to_list(length=limit + 1)

    # Check if there are more messages
    has_more = len(msgs) > limit
    if has_more:
        msgs = msgs[:limit]  # remove the extra one

    # Reverse to return oldest first for the UI
    msgs = list(reversed(msgs))

    # Filter: Only send 'pending' interrupts to the frontend
    # If a message has an 'interrupt' field that is no longer pending, we skip it
    return {
        "messages": [
            MessagePublic(
                id=str(m["_id"]),
                role=m["role"],
                content=m["content"],
                tool_calls=m.get("tool_calls"),
                attachments=m.get("attachments"),
                interrupt=m.get("interrupt"),
                created_at=m["created_at"],
            )
            for m in msgs
            if _should_expose_message(m)
        ],
        "has_more": has_more,
    }


@router.post("/{chat_id}/message")
async def send_message(chat_id: str, body: dict, user: CurrentUser):
    """
    Send a user message and stream back the AI response via SSE.
    Body: {"content": "..."}
    """
    content = body.get("content", "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message content is required")

    chat = await chats_col().find_one({"_id": ObjectId(chat_id), "user_id": user.id})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    await _ensure_chat_enabled(user.id)
    await _persist_user_message(chat_id=chat_id, user_id=user.id, content=content)

    return StreamingResponse(
        stream_agent_response(content, chat_id, user.id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{chat_id}/message_with_files")
async def send_message_with_files(
    chat_id: str,
    user: CurrentUser,
    content: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    """Send a user message with file attachments (multipart/form-data) and stream back the AI response via SSE."""
    content = (content or "").strip()
    if not content and not files:
        raise HTTPException(status_code=400, detail="Message content or files are required")

    chat = await chats_col().find_one({"_id": ObjectId(chat_id), "user_id": user.id})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    await _ensure_chat_enabled(user.id)
    attachments = await _store_chat_attachments(chat_id=chat_id, user_id=user.id, files=files)
    upload_note = build_attachment_event_text(attachments) if attachments else ""
    await _persist_user_message(
        chat_id=chat_id,
        user_id=user.id,
        content=content,
        attachments=attachments,
    )

    return StreamingResponse(
        stream_agent_response(
            content,
            chat_id,
            user.id,
            user_message_context=upload_note if attachments else None,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{chat_id}/attachments/{attachment_id}")
async def get_chat_attachment(chat_id: str, attachment_id: str, user: CurrentUser):
    """Serve an uploaded attachment for preview/download."""
    chat = await chats_col().find_one({"_id": ObjectId(chat_id), "user_id": user.id})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Find attachment metadata from messages
    doc = await messages_col().find_one(
        {
            "chat_id": chat_id,
            "user_id": user.id,
            "attachments.id": attachment_id,
        },
        projection={"attachments": 1},
    )
    atts = (doc or {}).get("attachments") or []
    att = next((a for a in atts if a.get("id") == attachment_id), None)
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
async def delete_chat(chat_id: str, user: CurrentUser):
    """Hard-delete a chat session."""
    result = await chats_col().delete_one({"_id": ObjectId(chat_id), "user_id": user.id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Also delete all messages belonging to this chat.
    try:
        await messages_col().delete_many({"chat_id": chat_id, "user_id": user.id})
    except Exception:
        logger.exception("Failed to delete messages for chat_id=%s", chat_id)

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
async def rename_chat(chat_id: str, body: RenameChatRequest, user: CurrentUser):
    """Rename a chat session."""
    new_title = body.title.strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="Title is required")
    
    result = await chats_col().update_one(
        {"_id": ObjectId(chat_id), "user_id": user.id},
        {"$set": {"title": new_title, "updated_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    chat = await chats_col().find_one({"_id": ObjectId(chat_id)})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat found but could not be retrieved")
    return ChatPublic(**_chat_doc_to_public(chat))

@router.post("/{chat_id}/interrupt-resolve")
async def resolve_chat_interrupt(chat_id: str, body: ResolveInterruptRequest, user: CurrentUser):
    """
    Resolve a pending interrupt and resume the graph.
    """
    action = body.action
    data = body.data
    
    chat = await chats_col().find_one({"_id": ObjectId(chat_id), "user_id": user.id})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    await _ensure_chat_enabled(user.id)
    
    # Mark any pending interrupt as resolved instead of deleting (Audit Log)
    update_result = await messages_col().update_many(
        {
            "chat_id": chat_id,
            "interrupt.is_pending": True
        },
        {
            "$set": {
                "interrupt.is_pending": False,
                "interrupt.resolution": action,
                "interrupt.resolved_at": datetime.utcnow()
            }
        }
    )
    logger.info(f"Marked {update_result.modified_count} interrupts as resolved (action: {action}) for chat {chat_id}")

    if action == "reject":
        now = datetime.utcnow()
        await messages_col().insert_one({
            "chat_id": chat_id,
            "user_id": user.id,
            "role": "user",
            "content": f"[User rejected the action]: {data}",
            "created_at": now,
        })
        resume_value = False
    else:
        if isinstance(data, str) and data.strip():
            await _persist_user_message(chat_id=chat_id, user_id=user.id, content=data.strip())
        resume_value = data if data is not None else True

    return StreamingResponse(
        stream_agent_response(
            None, 
            chat_id, 
            user.id, 
            is_resume=True, 
            resume_value=resume_value
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{chat_id}/interrupt-resolve-with-files")
async def resolve_chat_interrupt_with_files(
    chat_id: str,
    user: CurrentUser,
    content: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    """Resolve a pending file-upload interrupt and resume the graph from the same checkpoint."""
    content = (content or "").strip()
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    chat = await chats_col().find_one({"_id": ObjectId(chat_id), "user_id": user.id})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    await _ensure_chat_enabled(user.id)

    update_result = await messages_col().update_many(
        {
            "chat_id": chat_id,
            "interrupt.is_pending": True
        },
        {
            "$set": {
                "interrupt.is_pending": False,
                "interrupt.resolution": "accept",
                "interrupt.resolved_at": datetime.utcnow()
            }
        }
    )
    logger.info("Marked %s interrupts as resolved via file upload for chat %s", update_result.modified_count, chat_id)

    attachments = await _store_chat_attachments(chat_id=chat_id, user_id=user.id, files=files)
    upload_note = build_attachment_event_text(attachments)
    stored_content = content or upload_note
    await _persist_user_message(
        chat_id=chat_id,
        user_id=user.id,
        content=stored_content,
        attachments=attachments,
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
            user.id,
            is_resume=True,
            resume_value=resume_value,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
