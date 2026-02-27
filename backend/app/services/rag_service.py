import logging
import io
from datetime import datetime
from typing import Optional

import chromadb
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings
from app.database import documents_col

logger = logging.getLogger(__name__)
settings = get_settings()

# Singleton Chroma client
_chroma_client: Optional[chromadb.PersistentClient] = None
_collection: Optional[chromadb.Collection] = None


def get_chroma_collection() -> chromadb.Collection:
    global _chroma_client, _collection
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=settings.chroma_path)
    if _collection is None:
        _collection = _chroma_client.get_or_create_collection(
            name="business_docs",
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def _extract_text(file_bytes: bytes, file_type: str, filename: str) -> str:
    """Extract plain text from PDF, DOCX, or TXT."""
    if file_type == "application/pdf":
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    elif file_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs)

    else:  # plain text
        return file_bytes.decode("utf-8", errors="replace")


async def ingest_document(
    file_bytes: bytes,
    filename: str,
    file_type: str,
    user_id: str,
) -> dict:
    """
    Extract text → chunk → embed → store in ChromaDB.
    Also records the document in MongoDB.
    """
    text = _extract_text(file_bytes, file_type, filename)
    if not text.strip():
        raise ValueError("Could not extract any text from the uploaded file.")

    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    chunks = splitter.split_text(text)

    embeddings_model = OpenAIEmbeddings(
        model="text-embedding-3-small",
        openai_api_key=settings.openai_api_key,
    )
    embeddings = await embeddings_model.aembed_documents(chunks)

    collection = get_chroma_collection()
    now_str = datetime.utcnow().isoformat()

    # Use deterministic chunk ids: doc_filename_chunk_N
    import hashlib
    base_id = hashlib.md5(f"{user_id}{filename}{now_str}".encode()).hexdigest()[:8]
    chunk_ids = [f"{base_id}_chunk_{i}" for i in range(len(chunks))]

    collection.add(
        ids=chunk_ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=[{"user_id": user_id, "filename": filename, "chunk_index": i} for i in range(len(chunks))],
    )

    # Persist metadata to MongoDB
    doc_record = {
        "user_id": user_id,
        "filename": filename,
        "file_type": file_type,
        "chunk_count": len(chunks),
        "chroma_ids": chunk_ids,
        "created_at": datetime.utcnow(),
    }
    result = await documents_col().insert_one(doc_record)

    logger.info(f"Ingested '{filename}' → {len(chunks)} chunks for user {user_id}")
    return {"id": str(result.inserted_id), "chunk_count": len(chunks)}


async def retrieve(query: str, user_id: str, k: int = 5) -> str:
    """Semantic search over the user's documents. Returns concatenated passages."""
    collection = get_chroma_collection()
    embeddings_model = OpenAIEmbeddings(
        model="text-embedding-3-small",
        openai_api_key=settings.openai_api_key,
    )
    query_embedding = await embeddings_model.aembed_query(query)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=k,
        where={"user_id": user_id},
        include=["documents", "metadatas"],
    )

    passages = results.get("documents", [[]])[0]
    if not passages:
        return ""

    formatted = []
    for i, (text, meta) in enumerate(zip(passages, results["metadatas"][0])):
        formatted.append(f"[Source: {meta.get('filename', 'unknown')}]\n{text}")

    return "\n\n---\n\n".join(formatted)


async def retrieve_top_filenames(query: str, user_id: str, k: int = 5) -> list[str]:
    """Return the top-matching document filenames for a query (no passages).

    This is intended as a cheap relevance hint for agents so they can decide
    whether to use RAG retrieval first.
    """
    collection = get_chroma_collection()
    embeddings_model = OpenAIEmbeddings(
        model="text-embedding-3-small",
        openai_api_key=settings.openai_api_key,
    )
    query_embedding = await embeddings_model.aembed_query(query)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=int(k or 5),
        where={"user_id": user_id},
        include=["metadatas"],
    )

    metas = results.get("metadatas", [[]])[0] or []
    filenames: list[str] = []
    for meta in metas:
        if not isinstance(meta, dict):
            continue
        fn = (meta.get("filename") or "").strip()
        if fn and fn not in filenames:
            filenames.append(fn)
    return filenames


async def delete_document_chunks(chroma_ids: list[str]):
    """Remove specific chunk IDs from ChromaDB."""
    if not chroma_ids:
        return
    collection = get_chroma_collection()
    collection.delete(ids=chroma_ids)
    logger.info(f"Deleted {len(chroma_ids)} chunks from Chroma")
