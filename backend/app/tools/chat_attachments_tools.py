from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from app.database import messages_col

logger = logging.getLogger(__name__)


def get_chat_attachments_tools(*, user_id: str, chat_id: str | None):
    """Factory returning user+chat-scoped tools to access uploaded attachments.

    These tools let the LLM read the full content of files stored in `tmp/chats/{chat_id}`
    (via the persisted `stored_path` in message attachments).
    """

    async def _resolve_attachment(*, attachment_id: str) -> dict[str, Any] | None:
        if not chat_id:
            return None

        doc = await messages_col().find_one(
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "attachments.id": attachment_id,
            },
            projection={"attachments": 1},
        )
        atts = (doc or {}).get("attachments") or []
        if not isinstance(atts, list):
            return None
        att = next((a for a in atts if isinstance(a, dict) and a.get("id") == attachment_id), None)
        return att

    @tool("chat_list_attachments")
    async def chat_list_attachments() -> dict:
        """List uploaded attachments available in the current chat.

        When to use:
        - Use this first to discover available files and their attachment IDs.

        Returns:
            A dict with:
            - ok: bool
            - chat_id: str
            - attachments: list of {id, filename, content_type, size}
            - error: str (present only when ok=false)
        """
        if not chat_id:
            return {"ok": False, "error": "No chat_id available for attachment tools."}

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

        logger.info("chat.attachments.list chat_id=%s user_id=%s count=%s", chat_id, user_id, len(out))
        return {"ok": True, "chat_id": chat_id, "attachments": out}

    @tool("chat_read_attachment_text")
    async def chat_read_attachment_text(
        attachment_id: str,
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
            attachment_id: Required. The attachment ID (from chat_list_attachments).
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
        """
        if not chat_id:
            return {"ok": False, "error": "No chat_id available for attachment tools."}

        att = await _resolve_attachment(attachment_id=attachment_id)
        if not att:
            return {"ok": False, "error": "Attachment not found in this chat."}

        stored_path = att.get("stored_path")
        if not stored_path:
            return {"ok": False, "error": "Attachment stored_path not available."}

        try:
            raw = Path(stored_path).read_bytes()
        except Exception:
            raw = b""
        if not raw:
            return {"ok": False, "error": "Attachment file is missing or unreadable."}

        filename = att.get("filename") or "file"
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
                "attachment_id": str(attachment_id),
                "filename": filename,
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
                "attachment_id": str(attachment_id),
                "filename": filename,
                "content_type": ctype,
                "has_more": has_more,
                "next_start_char": int(next_start_char),
                "total_chars": int(total_chars),
                "text": text,
            }

        return {"ok": False, "error": f"Unsupported content_type for text extraction: {ctype}"}

    return [
        chat_list_attachments,
        chat_read_attachment_text,
    ]
