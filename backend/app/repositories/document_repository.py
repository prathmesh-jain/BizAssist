import uuid
from typing import Optional, List
from sqlalchemy import select, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document


class DocumentRepository:
    """Repository for document-related operations."""

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        document_id: str,
        organization_id: str,
    ) -> Optional[Document]:
        """Get document by ID with organization scoping."""
        result = await session.execute(
            select(Document).where(
                Document.id == document_id,
                Document.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession,
        organization_id: str,
        uploaded_by_user_id: str,
        filename: str,
        file_type: str,
        chunk_count: int = 0,
        storage_key: Optional[str] = None,
        status: str = "pending",
    ) -> Document:
        """Create a new document."""
        document = Document(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            uploaded_by_user_id=uploaded_by_user_id,
            filename=filename,
            file_type=file_type,
            chunk_count=chunk_count,
            storage_key=storage_key,
            status=status,
        )
        session.add(document)
        await session.flush()
        return document

    @staticmethod
    async def list_by_organization(
        session: AsyncSession,
        organization_id: str,
        limit: int = 100,
    ) -> List[Document]:
        """List documents for an organization."""
        result = await session.execute(
            select(Document)
            .where(Document.organization_id == organization_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def update_status(
        session: AsyncSession,
        document_id: str,
        organization_id: str,
        status: str,
        chunk_count: Optional[int] = None,
    ) -> Optional[Document]:
        """Update document status and optionally chunk count."""
        result = await session.execute(
            select(Document).where(
                Document.id == document_id,
                Document.organization_id == organization_id,
            )
        )
        document = result.scalar_one_or_none()
        if document:
            document.status = status
            if chunk_count is not None:
                document.chunk_count = chunk_count
            await session.flush()
        return document

    @staticmethod
    async def delete(
        session: AsyncSession,
        document_id: str,
        organization_id: str,
    ) -> bool:
        """Delete a document."""
        result = await session.execute(
            delete(Document).where(
                Document.id == document_id,
                Document.organization_id == organization_id,
            )
        )
        await session.flush()
        return result.rowcount > 0
