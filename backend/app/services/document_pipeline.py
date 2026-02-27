import asyncio
import io
import json
import logging
from datetime import datetime
from typing import Any, Optional

from app.config import get_settings
from app.database import financial_docs_col
from app.services.llm_service import get_llm

logger = logging.getLogger(__name__)
settings = get_settings()


def analyze_file_size(file_bytes: bytes, content_type: str) -> dict:
    """Return size metrics: bytes, pages (if applicable), and characters (if text extractable)."""
    content_type = (content_type or "application/octet-stream").lower()
    size_bytes = len(file_bytes or b"")

    pages: Optional[int] = None
    chars: Optional[int] = None

    if content_type == "application/pdf":
        try:
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            pages = len(reader.pages)
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
            chars = len(text)
        except Exception:
            pages = None
            chars = None

    elif content_type == "text/plain":
        try:
            text = file_bytes.decode("utf-8", errors="replace")
            chars = len(text)
        except Exception:
            chars = None

    elif content_type.startswith("image/"):
        pages = 1
        chars = None

    return {"bytes": size_bytes, "pages": pages, "characters": chars}


async def _extract_invoice_chunked(
    *,
    file_bytes: bytes,
    content_type: str,
    filename: str,
    chunk_size: int = 4000,
    chunk_overlap: int = 300,
    max_chunks: int = 10,
) -> dict:
    """Chunk-and-merge invoice extraction for large text-based invoices."""
    from langchain_core.messages import SystemMessage, HumanMessage
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    ctype = (content_type or "application/octet-stream").lower()
    if ctype not in {"application/pdf", "text/plain"}:
        return {}

    if ctype == "application/pdf":
        try:
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception:
            text = ""
    else:
        try:
            text = file_bytes.decode("utf-8", errors="replace")
        except Exception:
            text = ""

    text = (text or "").strip()
    if not text:
        return {}

    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks = splitter.split_text(text)[:max_chunks]

    llm = get_llm(
        model_name=settings.primary_model,
        temperature=0,
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    system = (
        "You are an invoice data extraction assistant. Return VALID JSON only. "
        "Extract: vendor (string|null), amount (number|null), currency (3-letter ISO|null), "
        "date (YYYY-MM-DD|null), category (string|null), notes (string|null)."
    )

    partials: list[dict] = []
    for i, c in enumerate(chunks):
        try:
            resp = await llm.ainvoke([
                SystemMessage(content=system),
                HumanMessage(content=f"Filename: {filename}\nChunk {i+1}/{len(chunks)}:\n{c}"),
            ])
            partials.append(json.loads(resp.content or "{}"))
        except Exception:
            logger.exception("Invoice chunk extraction failed")

    merged: dict[str, Any] = {}
    for p in partials:
        if not isinstance(p, dict):
            continue
        for k, v in p.items():
            if k not in merged or merged[k] in (None, "", [], {}):
                merged[k] = v

    merged["_chunked"] = True
    merged["_chunks_used"] = len(chunks)
    return merged


async def _extract_receipt_or_statement(
    *,
    file_bytes: bytes,
    content_type: str,
    doc_type: str,
    filename: str,
    max_chars: int = 12000,
) -> dict:
    """LLM extraction for receipts and bank statements.

    - For PDFs and TXT we extract text and send it.
    - For images we send as vision input.

    Returns a JSON dict.
    """
    from langchain_core.messages import SystemMessage, HumanMessage

    doc_type = (doc_type or "other").strip().lower()
    if doc_type not in {"receipt", "bank_statement"}:
        doc_type = "receipt"

    llm = get_llm(
        model_name=settings.primary_model,
        temperature=0,
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    if doc_type == "receipt":
        system = (
            "You are a receipt extraction assistant. Return VALID JSON only. "
            "Extract: vendor (string|null), date (YYYY-MM-DD|null), total_amount (number|null), "
            "currency (3-letter ISO|null), payment_method (string|null), items (array of {name, quantity, price} optional)."
        )
    else:
        system = (
            "You are a bank statement extraction assistant. Return VALID JSON only. "
            "Extract: bank_name (string|null), account_holder (string|null), account_number_last4 (string|null), "
            "period_start (YYYY-MM-DD|null), period_end (YYYY-MM-DD|null), currency (3-letter ISO|null), "
            "transactions (array of {date, description, amount, balance optional})."
        )

    ctype = (content_type or "application/octet-stream").lower()

    if ctype == "application/pdf":
        try:
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception:
            text = ""
        text = (text or "")[:max_chars]
        resp = await llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=f"Filename: {filename}\n\nText:\n{text}"),
        ])
        return json.loads(resp.content or "{}")

    if ctype == "text/plain":
        try:
            text = file_bytes.decode("utf-8", errors="replace")
        except Exception:
            text = ""
        text = (text or "")[:max_chars]
        resp = await llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=f"Filename: {filename}\n\nText:\n{text}"),
        ])
        return json.loads(resp.content or "{}")

    # image/*
    import base64

    b64 = base64.b64encode(file_bytes).decode("utf-8")
    resp = await llm.ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=[
            {"type": "text", "text": f"Filename: {filename}\nExtract from this image:"},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{ctype};base64,{b64}", "detail": "high"},
            },
        ]),
    ])
    return json.loads(resp.content or "{}")


async def _chunked_extract_text_fields(
    *,
    file_bytes: bytes,
    content_type: str,
    doc_type: str,
    filename: str,
    chunk_size: int = 4000,
    chunk_overlap: int = 300,
    max_chunks: int = 12,
) -> dict:
    """Chunk-and-merge extraction for large financial docs.

    Implementation notes:
    - Uses text-only extraction (PDF/TXT). Images are treated as direct extraction.
    - Produces a merged JSON with best-effort.
    """
    from langchain_core.messages import SystemMessage, HumanMessage
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    ctype = (content_type or "application/octet-stream").lower()
    if ctype not in {"application/pdf", "text/plain"}:
        return {}

    if ctype == "application/pdf":
        try:
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception:
            text = ""
    else:
        try:
            text = file_bytes.decode("utf-8", errors="replace")
        except Exception:
            text = ""

    text = (text or "").strip()
    if not text:
        return {}

    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks = splitter.split_text(text)[:max_chunks]

    llm = get_llm(
        model_name=settings.primary_model,
        temperature=0,
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    doc_type = (doc_type or "other").strip().lower()

    if doc_type in {"invoice", "receipt"}:
        system = (
            "You are extracting a single receipt/invoice chunk. Return VALID JSON only. "
            "Extract fields if present: vendor, date, total_amount, currency, line_items optional. "
            "If unknown, return nulls."
        )
    else:
        system = (
            "You are extracting bank statement info from a chunk. Return VALID JSON only. "
            "Extract transactions if present: transactions: [{date, description, amount, balance optional}]."
        )

    partials: list[dict] = []
    for i, c in enumerate(chunks):
        try:
            resp = await llm.ainvoke([
                SystemMessage(content=system),
                HumanMessage(content=f"Filename: {filename}\nChunk {i+1}/{len(chunks)}:\n{c}"),
            ])
            partials.append(json.loads(resp.content or "{}"))
        except Exception:
            logger.exception("Chunk extraction failed")

    # Merge strategy: concat transactions, fill first non-null for header fields
    merged: dict[str, Any] = {}
    transactions: list[dict] = []

    for p in partials:
        if not isinstance(p, dict):
            continue
        for k, v in p.items():
            if k == "transactions" and isinstance(v, list):
                transactions.extend([t for t in v if isinstance(t, dict)])
            else:
                if k not in merged or merged[k] in (None, "", [], {}):
                    merged[k] = v

    if transactions:
        merged["transactions"] = transactions

    merged["_chunked"] = True
    merged["_chunks_used"] = len(chunks)
    return merged


async def process_uploaded_files(
    *,
    user_id: str,
    chat_id: str,
    files: list[dict],
    doc_type: str,
) -> None:
    """Process uploaded files based on doc_type.

    files: list of {file_bytes, filename, content_type, size_metrics}

    - invoice/receipt/bank_statement: extract + store to Mongo (financial_docs or invoices)
    - contract/report: ingest into RAG (Chroma + documents collection)
    """
    doc_type = (doc_type or "other").strip().lower()

    # Contract/report -> RAG
    if doc_type in {"contract", "report"}:
        try:
            from app.services.rag_service import ingest_document

            for f in files:
                ctype = (f.get("content_type") or "").lower()
                if ctype not in {"application/pdf", "text/plain"}:
                    continue
                await ingest_document(
                    file_bytes=f.get("file_bytes") or b"",
                    filename=f.get("filename") or "file",
                    file_type=ctype,
                    user_id=user_id,
                )
        except Exception:
            logger.exception("RAG ingest failed")
        return

    # Financial docs
    for f in files:
        filename = f.get("filename") or "file"
        ctype = (f.get("content_type") or "application/octet-stream").lower()
        raw = f.get("file_bytes") or b""
        metrics = f.get("size_metrics") or {}
        pages = metrics.get("pages")
        chars = metrics.get("characters")
        size_bytes = metrics.get("bytes")

        is_small = (
            (pages is not None and pages <= 2)
            or (chars is not None and chars <= 4000)
            or (size_bytes is not None and size_bytes <= 1_000_000)
        )

        try:
            if doc_type in {"receipt", "bank_statement"} and is_small:
                data = await _extract_receipt_or_statement(
                    file_bytes=raw,
                    content_type=ctype,
                    doc_type=doc_type,
                    filename=filename,
                )
            else:
                # Large financial document or invoice/receipt/statement that is big
                data = await _chunked_extract_text_fields(
                    file_bytes=raw,
                    content_type=ctype,
                    doc_type=doc_type,
                    filename=filename,
                )
                if (not data) and doc_type in {"receipt", "bank_statement"}:
                    data = await _extract_receipt_or_statement(
                        file_bytes=raw,
                        content_type=ctype,
                        doc_type=doc_type,
                        filename=filename,
                    )

            doc = {
                "user_id": user_id,
                "chat_id": chat_id,
                "doc_type": doc_type,
                "filename": filename,
                "content_type": ctype,
                "size_metrics": metrics,
                "data": data,
                "created_at": datetime.utcnow(),
            }
            await financial_docs_col().insert_one(doc)
        except Exception:
            logger.exception("Financial doc extraction failed")


def run_pipeline_async(*, user_id: str, chat_id: str, files: list[dict], doc_type: str) -> None:
    """Fire-and-forget wrapper for the document pipeline."""
    asyncio.create_task(process_uploaded_files(user_id=user_id, chat_id=chat_id, files=files, doc_type=doc_type))
