import logging
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException

from app.authz import can
from app.dependencies import DocumentReader, DocumentUploader
from app.db.base import get_db_session
from app.models.document import DocumentPublic
from app.repositories import DocumentRepository
from app.services.rag_service import ingest_document, delete_document_chunks

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = logging.getLogger(__name__)

ALLOWED_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}


@router.post("/upload")
async def upload_document(user: DocumentUploader, file: UploadFile = File(...), session = Depends(get_db_session)):
    """Upload a business document and ingest it into the RAG vector store."""
    from app.services.user_settings_service import UserSettingsError

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported file type. Use PDF, DOCX, or TXT.")

    file_bytes = await file.read()
    try:
        doc_record = await ingest_document(
            file_bytes=file_bytes,
            filename=file.filename,
            file_type=file.content_type,
            user_id=user.user.id,
            organization_id=user.organization.id,
            session=session,
        )
    except UserSettingsError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Document ingestion failed")
        raise HTTPException(status_code=500, detail="Internal server error during ingestion.")

    return {"doc_id": doc_record["id"], "filename": file.filename, "chunks": doc_record["chunk_count"]}


@router.get("", response_model=list[DocumentPublic])
async def list_documents(user: DocumentReader, session = Depends(get_db_session)):
    """List all ingested documents for the current user's organization."""
    documents = await DocumentRepository.list_by_organization(session, user.organization.id)
    return [
        DocumentPublic(
            id=doc.id,
            filename=doc.filename,
            file_type=doc.file_type,
            chunk_count=doc.chunk_count,
            created_at=doc.created_at,
        )
        for doc in documents
    ]


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, user: DocumentReader, session = Depends(get_db_session)):
    """Remove a document from PostgreSQL and the vector store."""
    doc = await DocumentRepository.get_by_id(session, doc_id, user.organization.id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    own = doc.uploaded_by_user_id == user.user.id
    if not can(user.role, "document.delete_own" if own else "document.delete_any"):
        raise HTTPException(status_code=403, detail=f"Your role ({user.role}) can't delete this document.")
    await delete_document_chunks(doc_id, user.organization.id)
    await DocumentRepository.delete(session, doc_id, user.organization.id)
    return {"ok": True}
