import logging
from pathlib import Path
from uuid import uuid4
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, FileResponse
from bson import ObjectId

from app.dependencies import CurrentUser
from app.database import chats_col, messages_col
from app.models.chat import ChatCreate, ChatPublic
from app.models.message import MessagePublic
from app.services.chat_service import stream_agent_response, _build_attachments_prompt_context

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


def _chat_doc_to_public(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "title": doc.get("title", "New Chat"),
        "created_at": doc["created_at"],
        "updated_at": doc["updated_at"],
    }


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

    return {
        "messages": [
            MessagePublic(
                id=str(m["_id"]),
                role=m["role"],
                content=m["content"],
                tool_calls=m.get("tool_calls"),
                attachments=m.get("attachments"),
                created_at=m["created_at"],
            )
            for m in msgs
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

    # Persist user message
    now = datetime.utcnow()
    user_msg = {
        "chat_id": chat_id,
        "user_id": user.id,
        "role": "user",
        "content": content,
        "tool_calls": None,
        "created_at": now,
    }
    await messages_col().insert_one(user_msg)
    # Update chat timestamp
    await chats_col().update_one(
        {"_id": ObjectId(chat_id)},
        {"$set": {"updated_at": now}},
    )

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

    attachments: list[dict] = []
    tmp_dir = _chat_tmp_dir(chat_id)

    logger.info("chat.upload.start chat_id=%s user_id=%s files=%s has_text=%s", chat_id, user.id, len(files or []), bool(content))

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

        # Persist only extracted text artifacts in tmp.
        extracted_text = ""
        if ctype == "application/pdf":
            extracted_text = _extract_text_from_pdf_bytes(raw)
        elif ctype == "text/plain":
            try:
                extracted_text = raw.decode("utf-8", errors="replace")
            except Exception:
                extracted_text = ""
        else:
            # For images, run LLM extraction and store the extracted text artifact.
            try:
                from app.services.chat_service import extract_text_from_image_bytes
                extracted_text = await extract_text_from_image_bytes(raw, original_content_type)
            except Exception:
                extracted_text = ""

        stored_name = f"{att_id}.txt"
        path = tmp_dir / stored_name
        try:
            path.write_text(extracted_text or "", encoding="utf-8", errors="replace")
        except Exception as e:
            logger.exception(f"Failed to persist extracted text for attachment {fname} for chat {chat_id}: {e}")
            continue

        # All persisted artifacts are text/plain.
        ctype = "text/plain"

        logger.info(
            "chat.upload.saved chat_id=%s attachment_id=%s filename=%s content_type=%s bytes=%s path=%s",
            chat_id,
            att_id,
            fname,
            ctype,
            len(extracted_text or ""),
            str(path),
        )

        attachments.append(
            {
                "id": att_id,
                "filename": fname,
                "content_type": ctype,
                "size": len(raw),
                "original_content_type": original_content_type,
                "url": f"/api/chat/{chat_id}/attachments/{att_id}",
                "stored_path": str(path),
            }
        )

    # Persist user message (attachments metadata only; no blobs)
    now = datetime.utcnow()
    user_msg = {
        "chat_id": chat_id,
        "user_id": user.id,
        "role": "user",
        "content": content,
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
            for a in attachments
        ]
        or None,
        "created_at": now,
    }
    await messages_col().insert_one(user_msg)

    # Update chat timestamp
    await chats_col().update_one(
        {"_id": ObjectId(chat_id)},
        {"$set": {"updated_at": now}},
    )

    # Build attachment context ONCE (avoid duplicate extraction)
    attachment_files = [
        {k: a[k] for k in ("stored_path", "filename", "content_type") if k in a}
        for a in attachments
    ]
    attachments_context, _samples = await _build_attachments_prompt_context(attachment_files)

    # Stream agent response, reusing the prebuilt attachments context (avoid duplicate LLM calls)
    return StreamingResponse(
        stream_agent_response(
            content,
            chat_id,
            user.id,
            attachment_files=attachment_files,
            attachments_context_override=attachments_context,
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


@router.patch("/{chat_id}")
async def rename_chat(chat_id: str, body: dict, user: CurrentUser):
    """Rename a chat session."""
    new_title = body.get("title", "").strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="Title is required")
    
    result = await chats_col().update_one(
        {"_id": ObjectId(chat_id), "user_id": user.id},
        {"$set": {"title": new_title, "updated_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    chat = await chats_col().find_one({"_id": ObjectId(chat_id)})
    return ChatPublic(**_chat_doc_to_public(chat))
