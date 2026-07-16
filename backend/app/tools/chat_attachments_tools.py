from __future__ import annotations

import difflib
import io
import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.database import messages_col

logger = logging.getLogger(__name__)


class ChatReadAttachmentInput(BaseModel):
    attachment_id: str | None = Field(
        default=None,
        description="Attachment ID returned by the document listing tool.",
    )
    filename: str | None = Field(
        default=None,
        description="Optional filename or partial filename when the attachment ID is not known.",
    )
    start_page: int = Field(default=1, ge=1, description="1-based start page for PDFs.")
    end_page: int = Field(default=2, ge=1, description="1-based end page for PDFs.")
    start_char: int = Field(default=0, ge=0, description="0-based character offset for text artifacts.")
    max_chars: int = Field(default=12000, ge=1, le=50000, description="Maximum characters to return.")


async def list_chat_attachments_metadata(*, user_id: str, chat_id: str | None) -> list[dict[str, Any]]:
    if not chat_id:
        return []

    cursor = messages_col().find(
        {"chat_id": chat_id, "user_id": user_id, "attachments": {"$ne": None}},
        projection={"attachments": 1, "created_at": 1},
    )
    docs = await cursor.to_list(length=100)

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for d in docs:
        atts = d.get("attachments") or []
        if not isinstance(atts, list):
            continue
        for a in atts:
            if not isinstance(a, dict):
                continue
            att_id = a.get("id")
            if not att_id or att_id in seen:
                continue
            seen.add(str(att_id))
            out.append(
                {
                    "id": str(att_id),
                    "filename": a.get("filename"),
                    "content_type": a.get("content_type"),
                    "size": a.get("size"),
                }
            )
    return out


def get_chat_attachments_tools(*, user_id: str, chat_id: str | None):
    """Factory returning user+chat-scoped tools to access uploaded attachments.

    These tools let the LLM read the full content of files stored in `tmp/chats/{chat_id}`
    (via the persisted `stored_path` in message attachments).
    """

    async def _find_attachment_by_filename(*, filename: str) -> dict[str, Any] | None:
        if not chat_id:
            return None

        search_value = (filename or "").strip().lower()
        if not search_value:
            return None

        cursor = messages_col().find(
            {"chat_id": chat_id, "user_id": user_id, "attachments": {"$ne": None}},
            projection={"attachments": 1},
        )
        docs = await cursor.to_list(length=100)

        candidates: list[tuple[float, dict[str, Any]]] = []
        for doc in docs:
            for att in (doc.get("attachments") or []):
                if not isinstance(att, dict):
                    continue
                name = str(att.get("filename") or "").strip()
                if not name:
                    continue
                lowered_name = name.lower()
                score = difflib.SequenceMatcher(None, search_value, lowered_name).ratio()
                if search_value in lowered_name:
                    score += 0.4
                candidates.append((score, att))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], str(item[1].get("filename") or "")), reverse=True)
        best_score, best_attachment = candidates[0]
        if best_score <= 0:
            return None
        return best_attachment

    async def _resolve_attachment(*, attachment_id: str | None = None, filename: str | None = None) -> dict[str, Any] | None:
        if not chat_id:
            return None

        if attachment_id:
            doc = await messages_col().find_one(
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "attachments.id": attachment_id,
                },
                projection={"attachments": 1},
            )
            atts = (doc or {}).get("attachments") or []
            if isinstance(atts, list):
                att = next((a for a in atts if isinstance(a, dict) and a.get("id") == attachment_id), None)
                if att:
                    return att

        if filename:
            return await _find_attachment_by_filename(filename=filename)

        return None

    @tool("chat_read_attachment_text", args_schema=ChatReadAttachmentInput)
    async def chat_read_attachment_text(
        attachment_id: str | None = None,
        filename: str | None = None,
        start_page: int = 1,
        end_page: int = 2,
        start_char: int = 0,
        max_chars: int = 12000,
    ) -> dict:
        """Read text from a chat attachment.

        This tool is designed for text artifacts (recommended) and PDFs.

        If your system stores extracted text in `tmp/chats/{chat_id}` as `.txt`, use `start_char`
        to page through the content without truncation.

        Args:
            attachment_id: Required. The attachment ID returned by the document listing tool for a chat upload.
            start_page: Optional. 1-based start page for PDFs (inclusive). Defaults to 1.
            end_page: Optional. 1-based end page for PDFs (inclusive). Defaults to 2.
            start_char: Optional. 0-based character offset for text/plain artifacts. Defaults to 0.
            max_chars: Optional. Maximum characters to return.

        Returns:
            A dict with:
            - ok: bool
            - attachment_id: str
            - filename: str
            - content_type: str
            - page_range: {start_page:int, end_page:int} (PDF only)
            - total_pages: int (PDF only)
            - has_more: bool
            - next_start_char: int (text/plain only)
            - total_chars: int (text/plain only)
            - text: str
            - error: str (present only when ok=false)

        Notes:
            - For PDFs: call this tool multiple times with increasing page ranges until has_more=false.
            - For text/plain: call this tool repeatedly using next_start_char until has_more=false.
            - You may provide either `attachment_id` or `filename`. If only a filename is known, the tool will try to match it.
        """
        if not chat_id:
            return {"ok": False, "error": "No chat_id available for attachment tools."}

        if not attachment_id and not filename:
            return {"ok": False, "error": "Provide either attachment_id or filename."}

        att = await _resolve_attachment(attachment_id=attachment_id, filename=filename)
        if not att:
            return {
                "ok": False,
                "error": "Attachment not found in this chat.",
                "attachment_id": attachment_id,
                "filename": filename,
            }

        stored_path = att.get("stored_path")
        if not stored_path:
            return {"ok": False, "error": "Attachment stored_path not available."}

        try:
            raw = Path(stored_path).read_bytes()
        except Exception:
            raw = b""
        if not raw:
            return {"ok": False, "error": "Attachment file is missing or unreadable."}

        resolved_attachment_id = str(att.get("id") or attachment_id or "")
        resolved_filename = att.get("filename") or filename or "file"
        ctype = (att.get("content_type") or "application/octet-stream").lower()

        text = ""
        if ctype == "application/pdf":
            try:
                import pypdf

                reader = pypdf.PdfReader(io.BytesIO(raw))
                total_pages = len(reader.pages)

                sp = max(1, int(start_page or 1))
                ep = max(sp, int(end_page or sp))

                # Convert to 0-based indices (end exclusive)
                i0 = min(total_pages, sp) - 1
                i1 = min(total_pages, ep)

                texts: list[str] = []
                for p in reader.pages[i0:i1]:
                    texts.append(p.extract_text() or "")
                text = "\n".join(texts).strip()
            except Exception:
                logger.exception("chat.attachments.read_pdf_failed chat_id=%s user_id=%s attachment_id=%s", chat_id, user_id, attachment_id)
                text = ""

            text = (text or "")[: int(max_chars or 12000)]
            has_more = bool(int(end_page or 0) < int(total_pages or 0))
            logger.info(
                "chat.attachments.read chat_id=%s user_id=%s attachment_id=%s ctype=pdf pages=%s-%s chars=%s",
                chat_id,
                user_id,
                attachment_id,
                start_page,
                end_page,
                len(text),
            )
            return {
                "ok": True,
                "attachment_id": resolved_attachment_id,
                "filename": resolved_filename,
                "content_type": ctype,
                "page_range": {"start_page": int(start_page), "end_page": int(end_page)},
                "total_pages": int(total_pages),
                "has_more": has_more,
                "text": text,
            }

        if ctype == "text/plain":
            try:
                full_text = raw.decode("utf-8", errors="replace")
            except Exception:
                full_text = ""

            total_chars = len(full_text or "")
            sc = max(0, int(start_char or 0))
            mc = int(max_chars or 12000)
            text = (full_text or "")[sc : sc + mc]
            next_start_char = min(total_chars, sc + len(text))
            has_more = bool(next_start_char < total_chars)
            logger.info(
                "chat.attachments.read chat_id=%s user_id=%s attachment_id=%s ctype=txt chars=%s",
                chat_id,
                user_id,
                attachment_id,
                len(text),
            )
            return {
                "ok": True,
                "attachment_id": resolved_attachment_id,
                "filename": resolved_filename,
                "content_type": ctype,
                "has_more": has_more,
                "next_start_char": int(next_start_char),
                "total_chars": int(total_chars),
                "text": text,
            }

        return {"ok": False, "error": f"Unsupported content_type for text extraction: {ctype}"}

    return [chat_read_attachment_text]


def get_chat_attachment_read_tools(*, user_id: str, chat_id: str | None):
    return get_chat_attachments_tools(user_id=user_id, chat_id=chat_id)
