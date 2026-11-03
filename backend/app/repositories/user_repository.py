import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User, UserIdentity, Organization, OrganizationMember, UserAISettings


class UserRepository:
    """Repository for user-related operations."""

    @staticmethod
    async def get_by_id(session: AsyncSession, user_id: str) -> Optional[User]:
        """Get user by ID."""
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_email(session: AsyncSession, email: str) -> Optional[User]:
        """Get user by email (case-insensitive)."""
        result = await session.execute(
            select(User).where(User.email == email.lower())
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession,
        email: str,
        full_name: Optional[str],
    ) -> User:
        """Create a new user."""
        user = User(
            id=str(uuid.uuid4()),
            email=email.lower(),
            full_name=full_name,
            is_active=True,
        )
        session.add(user)
        await session.flush()
        return user

    @staticmethod
    async def get_identity_by_provider(
        session: AsyncSession,
        provider: str,
        provider_user_id: str,
    ) -> Optional[UserIdentity]:
        """Get user identity by provider and provider user ID."""
        result = await session.execute(
            select(UserIdentity).where(
                UserIdentity.provider == provider,
                UserIdentity.provider_user_id == provider_user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_identity(
        session: AsyncSession,
        user_id: str,
        provider: str,
        provider_user_id: str,
    ) -> UserIdentity:
        """Create a new user identity."""
        identity = UserIdentity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
        )
        session.add(identity)
        await session.flush()
        return identity

    @staticmethod
    async def get_active_membership(
        session: AsyncSession,
        user_id: str,
        organization_id: Optional[str] = None,
    ) -> Optional[tuple[OrganizationMember, Organization]]:
        """Active membership in an active organization.

        With organization_id, returns that membership; otherwise the user's default
        (oldest) one. Returns None when there is no usable membership.
        """
        query = (
            select(OrganizationMember, Organization)
            .join(Organization, Organization.id == OrganizationMember.organization_id)
            .where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.status == "active",
                Organization.is_active == True,
            )
        )
        if organization_id:
            query = query.where(OrganizationMember.organization_id == organization_id)
        result = await session.execute(
            query.order_by(OrganizationMember.created_at.asc(), OrganizationMember.id.asc()).limit(1)
        )
        row = result.first()
        return (row[0], row[1]) if row else None

    @staticmethod
    async def list_memberships(
        session: AsyncSession,
        user_id: str,
    ) -> List[tuple[OrganizationMember, Organization]]:
        """All of a user's memberships with their organizations, oldest first."""
        result = await session.execute(
            select(OrganizationMember, Organization)
            .join(Organization, Organization.id == OrganizationMember.organization_id)
            .where(OrganizationMember.user_id == user_id)
            .order_by(OrganizationMember.created_at.asc(), OrganizationMember.id.asc())
        )
        return [(row[0], row[1]) for row in result.all()]

    @staticmethod
    async def get_organization(session: AsyncSession, organization_id: str) -> Optional[Organization]:
        result = await session.execute(select(Organization).where(Organization.id == organization_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def create_organization(
        session: AsyncSession,
        name: str,
        slug: str,
    ) -> Organization:
        """Create a new organization."""
        org = Organization(
            id=str(uuid.uuid4()),
            name=name,
            slug=slug,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        return org

    @staticmethod
    async def create_organization_member(
        session: AsyncSession,
        organization_id: str,
        user_id: str,
        role: str = "owner",
    ) -> OrganizationMember:
        """Create a new organization member."""
        member = OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            user_id=user_id,
            role=role,
            status="active",
        )
        session.add(member)
        await session.flush()
        return member

    @staticmethod
    async def get_ai_settings(
        session: AsyncSession,
        user_id: str,
    ) -> Optional[UserAISettings]:
        """Get user AI settings."""
        result = await session.execute(
            select(UserAISettings).where(UserAISettings.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_ai_settings(
        session: AsyncSession,
        user_id: str,
        provider: str = "openai",
        primary_model: Optional[str] = None,
        fast_model: Optional[str] = None,
        nano_model: Optional[str] = None,
    ) -> UserAISettings:
        """Create AI settings for a user; models default to the server's configured ones."""
        defaults = get_settings()
        settings = UserAISettings(
            id=str(uuid.uuid4()),
            user_id=user_id,
            provider=provider,
            primary_model=primary_model or defaults.primary_model,
            fast_model=fast_model or defaults.fast_model,
            nano_model=nano_model or defaults.nano_model,
            guardrail_enabled=False,
        )
        session.add(settings)
        await session.flush()
        return settings

    @staticmethod
    async def update_ai_settings(
        session: AsyncSession,
        user_id: str,
        **updates,
    ) -> UserAISettings:
        """Update user AI settings."""
        result = await session.execute(
            select(UserAISettings).where(UserAISettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        if settings:
            for key, value in updates.items():
                if hasattr(settings, key) and value is not None:
                    setattr(settings, key, value)
        else:
            # Create if doesn't exist
            settings = await UserRepository.create_ai_settings(session, user_id)
            for key, value in updates.items():
                if hasattr(settings, key) and value is not None:
                    setattr(settings, key, value)
        await session.flush()
        return settings
