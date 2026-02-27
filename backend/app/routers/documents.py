import logging
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.dependencies import CurrentUser
from app.database import documents_col
from app.models.document import DocumentPublic
from app.services.rag_service import ingest_document

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = logging.getLogger(__name__)

ALLOWED_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}


@router.post("/upload")
async def upload_document(user: CurrentUser, file: UploadFile = File(...)):
    """Upload a business document and ingest it into the RAG vector store."""
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported file type. Use PDF, DOCX, or TXT.")

    file_bytes = await file.read()
    doc_record = await ingest_document(
        file_bytes=file_bytes,
        filename=file.filename,
        file_type=file.content_type,
        user_id=user.id,
    )
    return {"doc_id": doc_record["id"], "filename": file.filename, "chunks": doc_record["chunk_count"]}


@router.get("", response_model=list[DocumentPublic])
async def list_documents(user: CurrentUser):
    """List all ingested documents for the current user."""
    cursor = documents_col().find({"user_id": user.id}, sort=[("created_at", -1)])
    docs = await cursor.to_list(length=100)
    return [
        DocumentPublic(
            id=str(d["_id"]),
            filename=d["filename"],
            file_type=d["file_type"],
            chunk_count=d["chunk_count"],
            created_at=d["created_at"],
        )
        for d in docs
    ]


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, user: CurrentUser):
    """Remove a document from MongoDB (and optionally from Chroma)."""
    from bson import ObjectId
    from app.services.rag_service import delete_document_chunks
    doc = await documents_col().find_one({"_id": ObjectId(doc_id), "user_id": user.id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await delete_document_chunks(doc.get("chroma_ids", []))
    await documents_col().delete_one({"_id": ObjectId(doc_id)})
    return {"ok": True}
