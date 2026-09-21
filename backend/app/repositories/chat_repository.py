import uuid
from typing import Optional, List
from sqlalchemy import select, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from app.db.models import Chat, Message


class ChatRepository:
    """Repository for chat-related operations."""

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        chat_id: str,
        organization_id: str,
    ) -> Optional[Chat]:
        """Get chat by ID with organization scoping."""
        result = await session.execute(
            select(Chat).where(
                Chat.id == chat_id,
                Chat.organization_id == organization_id,
                Chat.is_deleted == False,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession,
        organization_id: str,
        created_by_user_id: str,
        title: str = "New Chat",
    ) -> Chat:
        """Create a new chat."""
        chat = Chat(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            created_by_user_id=created_by_user_id,
            title=title,
            is_deleted=False,
        )
        session.add(chat)
        await session.flush()
        return chat

    @staticmethod
    async def list_by_organization(
        session: AsyncSession,
        organization_id: str,
        limit: int = 100,
    ) -> List[Chat]:
        """List chats for an organization."""
        result = await session.execute(
            select(Chat)
            .where(
                Chat.organization_id == organization_id,
                Chat.is_deleted == False,
            )
            .order_by(Chat.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def update_title(
        session: AsyncSession,
        chat_id: str,
        organization_id: str,
        title: str,
    ) -> Optional[Chat]:
        """Update chat title."""
        result = await session.execute(
            select(Chat).where(
                Chat.id == chat_id,
                Chat.organization_id == organization_id,
            )
        )
        chat = result.scalar_one_or_none()
        if chat:
            chat.title = title
            chat.updated_at = datetime.now(timezone.utc)
            await session.flush()
        return chat

    @staticmethod
    async def soft_delete(
        session: AsyncSession,
        chat_id: str,
        organization_id: str,
    ) -> bool:
        """Soft delete a chat."""
        result = await session.execute(
            select(Chat).where(
                Chat.id == chat_id,
                Chat.organization_id == organization_id,
            )
        )
        chat = result.scalar_one_or_none()
        if chat:
            chat.is_deleted = True
            chat.updated_at = datetime.now(timezone.utc)
            await session.flush()
            return True
        return False

    @staticmethod
    async def hard_delete(
        session: AsyncSession,
        chat_id: str,
        organization_id: str,
    ) -> bool:
        """Hard delete a chat and its messages."""
        result = await session.execute(
            delete(Chat).where(
                Chat.id == chat_id,
                Chat.organization_id == organization_id,
            )
        )
        await session.flush()
        return result.rowcount > 0

    @staticmethod
    async def update_timestamp(
        session: AsyncSession,
        chat_id: str,
    ) -> None:
        """Update chat's updated_at timestamp."""
        result = await session.execute(
            select(Chat).where(Chat.id == chat_id)
        )
        chat = result.scalar_one_or_none()
        if chat:
            chat.updated_at = datetime.now(timezone.utc)
            await session.flush()


class MessageRepository:
    """Repository for message-related operations."""

    @staticmethod
    async def create(
        session: AsyncSession,
        chat_id: str,
        user_id: Optional[str],
        role: str,
        content: str,
        tool_calls: Optional[dict] = None,
        attachments: Optional[dict] = None,
        interrupt: Optional[dict] = None,
    ) -> Message:
        """Create a new message."""
        message = Message(
            id=str(uuid.uuid4()),
            chat_id=chat_id,
            user_id=user_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            attachments=attachments,
            interrupt=interrupt,
        )
        session.add(message)
        await session.flush()
        return message

    @staticmethod
    async def list_by_chat(
        session: AsyncSession,
        chat_id: str,
        limit: int = 100,
        before_id: Optional[str] = None,
    ) -> List[Message]:
        """List messages for a chat with pagination."""
        query = select(Message).where(Message.chat_id == chat_id)

        if before_id:
            # Get the timestamp of the before_id message
            before_result = await session.execute(
                select(Message.created_at).where(Message.id == before_id)
            )
            before_timestamp = before_result.scalar_one_or_none()
            if before_timestamp:
                query = query.where(Message.created_at < before_timestamp)

        result = await session.execute(
            query.order_by(Message.created_at.desc()).limit(limit + 1)
        )
        messages = list(result.scalars().all())
        return messages

    @staticmethod
    async def mark_interrupts_resolved(
        session: AsyncSession,
        chat_id: str,
        resolution: str,
    ) -> int:
        """Mark all pending interrupts in a chat as resolved."""
        result = await session.execute(
            select(Message).where(
                Message.chat_id == chat_id,
                Message.interrupt.isnot(None),
            )
        )
        messages = result.scalars().all()
        count = 0
        for msg in messages:
            if msg.interrupt and msg.interrupt.get("is_pending"):
                msg.interrupt["is_pending"] = False
                msg.interrupt["resolution"] = resolution
                msg.interrupt["resolved_at"] = datetime.now(timezone.utc).isoformat()
                count += 1
        await session.flush()
        return count

    @staticmethod
    async def delete_by_chat(
        session: AsyncSession,
        chat_id: str,
    ) -> int:
        """Delete all messages for a chat."""
        result = await session.execute(
            delete(Message).where(Message.chat_id == chat_id)
        )
        await session.flush()
        return result.rowcount
