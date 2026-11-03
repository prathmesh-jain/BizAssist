import hashlib
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import models

from app.config import get_settings
from app.repositories import DocumentRepository
from app.services.qdrant_service import ensure_qdrant_collection, get_qdrant_client, qdrant_filter, qdrant_match_filter
from app.services.user_settings_service import require_user_embedding_key

logger = logging.getLogger(__name__)
settings = get_settings()


def get_documents_collection_name() -> str:
    return settings.qdrant_documents_collection


def _ensure_documents_collection() -> None:
    ensure_qdrant_collection(
        get_documents_collection_name(),
        keyword_indexes=("organization_id", "document_id", "filename"),
    )


def build_document_point_id(*, organization_id: str, document_id: str, chunk_index: int, chunk_text: str) -> str:
    digest = hashlib.sha256(
        f"{organization_id}\n{document_id}\n{chunk_index}\n{chunk_text}".encode("utf-8")
    ).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"bizassist-doc:{digest}"))


def _get_embeddings_model(api_key: str) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=api_key,
    )


def _extract_text(file_bytes: bytes, file_type: str, filename: str) -> str:
    """Extract plain text from PDF, DOCX, or TXT."""
    if file_type == "application/pdf":
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if file_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        from docx import Document

        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs)

    return file_bytes.decode("utf-8", errors="replace")


async def ingest_document(
    file_bytes: bytes,
    filename: str,
    file_type: str,
    user_id: str,
    organization_id: str,
    session: AsyncSession,
) -> dict:
    """
    Extract text -> chunk -> embed -> store in Qdrant.
    Also records the document in PostgreSQL.
    """
    text = _extract_text(file_bytes, file_type, filename)
    if not text.strip():
        raise ValueError("Could not extract any text from the uploaded file.")

    splitter = RecursiveCharacterTextSplitter(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    chunks = splitter.split_text(text)

    api_key = await require_user_embedding_key(user_id, session)
    embeddings_model = _get_embeddings_model(api_key)
    embeddings = await embeddings_model.aembed_documents(chunks)

    # Create document record in PostgreSQL
    document = await DocumentRepository.create(
        session,
        organization_id=organization_id,
        uploaded_by_user_id=user_id,
        filename=filename,
        file_type=file_type,
        chunk_count=len(chunks),
        status="processing",
    )

    collection_name = get_documents_collection_name()
    _ensure_documents_collection()
    client = get_qdrant_client()

    points = [
        models.PointStruct(
            id=build_document_point_id(
                organization_id=organization_id,
                document_id=document.id,
                chunk_index=i,
                chunk_text=chunks[i],
            ),
            vector=embeddings[i],
            payload={
                "organization_id": organization_id,
                "document_id": document.id,
                "uploaded_by_user_id": user_id,
                "filename": filename,
                "chunk_index": i,
                "text": chunks[i],
            },
        )
        for i in range(len(chunks))
    ]
    client.upsert(
        collection_name=collection_name,
        points=points,
        wait=True,
    )

    # Update document status to ready
    await DocumentRepository.update_status(
        session,
        document.id,
        organization_id,
        status="ready",
        chunk_count=len(chunks),
    )

    logger.info("Ingested '%s' -> %s chunks for org %s", filename, len(chunks), organization_id)
    return {"id": document.id, "chunk_count": len(chunks)}


async def list_organization_documents(organization_id: str, session: AsyncSession) -> list[dict]:
    """List all RAG-ingested documents for an organization."""
    documents = await DocumentRepository.list_by_organization(session, organization_id)
    return [
        {
            "id": doc.id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "chunk_count": doc.chunk_count,
            "created_at": doc.created_at,
        }
        for doc in documents
    ]


def _build_query_filter(organization_id: str, filename: Optional[str] = None) -> models.Filter:
    conditions = [qdrant_match_filter("organization_id", organization_id)]
    if filename:
        conditions.append(qdrant_match_filter("filename", filename))
    return qdrant_filter(*conditions)


async def retrieve(query: str, organization_id: str, user_id: str, session: AsyncSession, k: int = 5, filename: Optional[str] = None) -> str:
    """Semantic search over the organization's documents. Returns concatenated passages."""
    collection_name = get_documents_collection_name()
    _ensure_documents_collection()
    client = get_qdrant_client()
    api_key = await require_user_embedding_key(user_id, session)
    embeddings_model = _get_embeddings_model(api_key)
    query_embedding = await embeddings_model.aembed_query(query)

    response = client.query_points(
        collection_name=collection_name,
        query=query_embedding,
        limit=int(k or 5),
        query_filter=_build_query_filter(organization_id=organization_id, filename=filename),
        with_payload=True,
        with_vectors=False,
    )

    passages: list[str] = []
    for point in response.points:
        payload = point.payload or {}
        text = str(payload.get("text") or "").strip()
        if not text:
            continue
        source = str(payload.get("filename") or "unknown")
        passages.append(f"[Source: {source}]\n{text}")

    return "\n\n---\n\n".join(passages)


async def retrieve_top_filenames(query: str, organization_id: str, user_id: str, session: AsyncSession, k: int = 5) -> list[str]:
    """Return the top-matching document filenames for a query (no passages)."""
    collection_name = get_documents_collection_name()
    _ensure_documents_collection()
    client = get_qdrant_client()
    api_key = await require_user_embedding_key(user_id, session)
    embeddings_model = _get_embeddings_model(api_key)
    query_embedding = await embeddings_model.aembed_query(query)

    response = client.query_points(
        collection_name=collection_name,
        query=query_embedding,
        limit=int(k or 5),
        query_filter=_build_query_filter(organization_id=organization_id),
        with_payload=True,
        with_vectors=False,
    )

    filenames: list[str] = []
    for point in response.points:
        payload = point.payload or {}
        filename = str(payload.get("filename") or "").strip()
        if filename and filename not in filenames:
            filenames.append(filename)
    return filenames


async def delete_document_chunks(document_id: str, organization_id: str):
    """Remove all vectors for a document from Qdrant."""
    collection_name = get_documents_collection_name()
    _ensure_documents_collection()
    client = get_qdrant_client()

    # Delete by document_id filter
    client.delete(
        collection_name=collection_name,
        points_selector=qdrant_filter(
            qdrant_match_filter("organization_id", organization_id),
            qdrant_match_filter("document_id", document_id),
        ),
        wait=True,
    )
    logger.info("Deleted vectors for document %s from Qdrant", document_id)
