import uuid
from typing import Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, delete, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OAuthConnection, OAuthState


class OAuthConnectionRepository:
    """Repository for OAuth connection operations."""

    @staticmethod
    async def get_by_organization_and_provider(
        session: AsyncSession,
        organization_id: str,
        provider: str,
    ) -> Optional[OAuthConnection]:
        """Get OAuth connection by organization and provider."""
        result = await session.execute(
            select(OAuthConnection).where(
                OAuthConnection.organization_id == organization_id,
                OAuthConnection.provider == provider,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_user_and_provider(
        session: AsyncSession,
        user_id: str,
        provider: str,
    ) -> Optional[OAuthConnection]:
        """Get OAuth connection by user and provider."""
        result = await session.execute(
            select(OAuthConnection).where(
                OAuthConnection.user_id == user_id,
                OAuthConnection.provider == provider,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_or_update(
        session: AsyncSession,
        organization_id: str,
        user_id: str,
        provider: str,
        access_token_encrypted: str,
        refresh_token_encrypted: Optional[str] = None,
        token_expires_at: Optional[datetime] = None,
        scopes: Optional[dict] = None,
        connection_metadata: Optional[dict] = None,
        provider_account_id: Optional[str] = None,
    ) -> OAuthConnection:
        """Create or update OAuth connection."""
        result = await session.execute(
            select(OAuthConnection).where(
                OAuthConnection.organization_id == organization_id,
                OAuthConnection.provider == provider,
            )
        )
        connection = result.scalar_one_or_none()

        if connection:
            # Update existing
            connection.access_token_encrypted = access_token_encrypted
            connection.refresh_token_encrypted = refresh_token_encrypted
            connection.token_expires_at = token_expires_at
            connection.scopes = scopes
            connection.connection_metadata = connection_metadata
            connection.provider_account_id = provider_account_id
        else:
            # Create new
            connection = OAuthConnection(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                user_id=user_id,
                provider=provider,
                provider_account_id=provider_account_id,
                access_token_encrypted=access_token_encrypted,
                refresh_token_encrypted=refresh_token_encrypted,
                token_expires_at=token_expires_at,
                scopes=scopes,
                connection_metadata=connection_metadata,
            )
            session.add(connection)

        await session.flush()
        return connection

    @staticmethod
    async def update_tokens(
        session: AsyncSession,
        connection_id: str,
        access_token_encrypted: str,
        token_expires_at: datetime,
    ) -> Optional[OAuthConnection]:
        """Update access token and expiration."""
        result = await session.execute(
            select(OAuthConnection).where(OAuthConnection.id == connection_id)
        )
        connection = result.scalar_one_or_none()
        if connection:
            connection.access_token_encrypted = access_token_encrypted
            connection.token_expires_at = token_expires_at
            await session.flush()
        return connection

    @staticmethod
    async def delete(
        session: AsyncSession,
        connection_id: str,
        organization_id: str,
    ) -> bool:
        """Delete OAuth connection."""
        result = await session.execute(
            delete(OAuthConnection).where(
                OAuthConnection.id == connection_id,
                OAuthConnection.organization_id == organization_id,
            )
        )
        await session.flush()
        return result.rowcount > 0


class OAuthStateRepository:
    """Repository for OAuth state operations."""

    @staticmethod
    async def create(
        session: AsyncSession,
        user_id: str,
        state_hash: str,
        chat_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        expires_in_minutes: int = 15,
    ) -> OAuthState:
        """Create a new OAuth state."""
        state = OAuthState(
            id=str(uuid.uuid4()),
            user_id=user_id,
            organization_id=organization_id,
            state_hash=state_hash,
            chat_id=chat_id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
            used=False,
        )
        session.add(state)
        await session.flush()
        return state

    @staticmethod
    async def get_valid_state(
        session: AsyncSession,
        user_id: str,
        organization_id: str,
        state_hash: str,
    ) -> Optional[OAuthState]:
        """Get a valid, unused, non-expired OAuth state issued to this user in this organization."""
        now = datetime.now(timezone.utc)
        result = await session.execute(
            select(OAuthState).where(
                OAuthState.user_id == user_id,
                OAuthState.organization_id == organization_id,
                OAuthState.state_hash == state_hash,
                OAuthState.used == False,
                OAuthState.expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def mark_used(
        session: AsyncSession,
        state_id: str,
    ) -> bool:
        """Mark an OAuth state as used."""
        result = await session.execute(
            select(OAuthState).where(OAuthState.id == state_id)
        )
        state = result.scalar_one_or_none()
        if state:
            state.used = True
            await session.flush()
            return True
        return False

    @staticmethod
    async def clear_chat_reference(
        session: AsyncSession,
        chat_id: str,
    ) -> None:
        """Detach OAuth states from a chat that is about to be deleted."""
        await session.execute(
            update(OAuthState).where(OAuthState.chat_id == chat_id).values(chat_id=None)
        )

    @staticmethod
    async def cleanup_expired(
        session: AsyncSession,
        older_than_hours: int = 24,
    ) -> int:
        """Delete expired OAuth states older than specified hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        result = await session.execute(
            delete(OAuthState).where(OAuthState.expires_at < cutoff)
        )
        await session.flush()
        return result.rowcount
