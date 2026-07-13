import hashlib
import io
import logging
import uuid
from datetime import datetime
from typing import Optional

from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import models

from app.config import get_settings
from app.database import documents_col
from app.services.qdrant_service import ensure_qdrant_collection, get_qdrant_client, qdrant_filter, qdrant_match_filter
from app.services.user_settings_service import require_user_openai_api_key

logger = logging.getLogger(__name__)
settings = get_settings()


def get_documents_collection_name() -> str:
    return settings.qdrant_documents_collection


def build_document_point_id(*, user_id: str, filename: str, chunk_index: int, chunk_text: str) -> str:
    digest = hashlib.sha256(
        f"{user_id}\n{filename}\n{chunk_index}\n{chunk_text}".encode("utf-8")
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
) -> dict:
    """
    Extract text -> chunk -> embed -> store in Qdrant.
    Also records the document in MongoDB.
    """
    text = _extract_text(file_bytes, file_type, filename)
    if not text.strip():
        raise ValueError("Could not extract any text from the uploaded file.")

    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    chunks = splitter.split_text(text)

    api_key = await require_user_openai_api_key(user_id)
    embeddings_model = _get_embeddings_model(api_key)
    embeddings = await embeddings_model.aembed_documents(chunks)

    collection_name = get_documents_collection_name()
    ensure_qdrant_collection(collection_name)
    client = get_qdrant_client()
    vector_ids = [
        build_document_point_id(
            user_id=user_id,
            filename=filename,
            chunk_index=i,
            chunk_text=chunks[i],
        )
        for i in range(len(chunks))
    ]
    points = [
        models.PointStruct(
            id=vector_ids[i],
            vector=embeddings[i],
            payload={
                "user_id": user_id,
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

    doc_record = {
        "user_id": user_id,
        "filename": filename,
        "file_type": file_type,
        "chunk_count": len(chunks),
        "vector_ids": vector_ids,
        "created_at": datetime.utcnow(),
    }
    result = await documents_col().insert_one(doc_record)

    logger.info("Ingested '%s' -> %s chunks for user %s", filename, len(chunks), user_id)
    return {"id": str(result.inserted_id), "chunk_count": len(chunks)}


async def list_user_documents(user_id: str) -> list[dict]:
    """List all RAG-ingested documents for a user."""
    cursor = documents_col().find({"user_id": user_id}, {"filename": 1, "_id": 1, "created_at": 1})
    docs = await cursor.to_list(length=100)
    return [{"id": str(d["_id"]), "filename": d["filename"], "created_at": d["created_at"]} for d in docs]


def _build_query_filter(user_id: str, filename: Optional[str] = None) -> models.Filter:
    conditions = [qdrant_match_filter("user_id", user_id)]
    if filename:
        conditions.append(qdrant_match_filter("filename", filename))
    return qdrant_filter(*conditions)


async def retrieve(query: str, user_id: str, k: int = 5, filename: Optional[str] = None) -> str:
    """Semantic search over the user's documents. Returns concatenated passages."""
    collection_name = get_documents_collection_name()
    ensure_qdrant_collection(collection_name)
    client = get_qdrant_client()
    api_key = await require_user_openai_api_key(user_id)
    embeddings_model = _get_embeddings_model(api_key)
    query_embedding = await embeddings_model.aembed_query(query)

    response = client.query_points(
        collection_name=collection_name,
        query=query_embedding,
        limit=int(k or 5),
        query_filter=_build_query_filter(user_id=user_id, filename=filename),
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


async def retrieve_top_filenames(query: str, user_id: str, k: int = 5) -> list[str]:
    """Return the top-matching document filenames for a query (no passages)."""
    collection_name = get_documents_collection_name()
    ensure_qdrant_collection(collection_name)
    client = get_qdrant_client()
    api_key = await require_user_openai_api_key(user_id)
    embeddings_model = _get_embeddings_model(api_key)
    query_embedding = await embeddings_model.aembed_query(query)

    response = client.query_points(
        collection_name=collection_name,
        query=query_embedding,
        limit=int(k or 5),
        query_filter=_build_query_filter(user_id=user_id),
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


async def delete_document_chunks(vector_ids: list[str]):
    """Remove specific vector IDs from Qdrant."""
    if not vector_ids:
        return
    collection_name = get_documents_collection_name()
    ensure_qdrant_collection(collection_name)
    client = get_qdrant_client()
    client.delete(
        collection_name=collection_name,
        points_selector=models.PointIdsList(
            points=vector_ids,
        ),
        wait=True,
    )
    logger.info("Deleted %s vectors from Qdrant", len(vector_ids))
