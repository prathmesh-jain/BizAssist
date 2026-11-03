import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OrganizationInvitation, OrganizationMember, User


class MembershipRepository:
    """Queries for an organization's members and invitations."""

    @staticmethod
    async def list_members(
        session: AsyncSession,
        organization_id: str,
    ) -> List[tuple[OrganizationMember, User]]:
        result = await session.execute(
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == organization_id)
            .order_by(OrganizationMember.created_at.asc(), OrganizationMember.id.asc())
        )
        return [(row[0], row[1]) for row in result.all()]

    @staticmethod
    async def get_member(
        session: AsyncSession,
        organization_id: str,
        user_id: str,
    ) -> Optional[OrganizationMember]:
        result = await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_member_by_email(
        session: AsyncSession,
        organization_id: str,
        email: str,
    ) -> Optional[OrganizationMember]:
        result = await session.execute(
            select(OrganizationMember)
            .join(User, User.id == OrganizationMember.user_id)
            .where(
                OrganizationMember.organization_id == organization_id,
                User.email == email.lower(),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def count_active_owners(
        session: AsyncSession,
        organization_id: str,
    ) -> int:
        # Lock the owner rows so two concurrent demotions can't both see "another owner exists".
        result = await session.execute(
            select(OrganizationMember.id)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.role == "owner",
                OrganizationMember.status == "active",
            )
            .with_for_update()
        )
        return len(result.scalars().all())

    @staticmethod
    async def delete_member(
        session: AsyncSession,
        organization_id: str,
        user_id: str,
    ) -> bool:
        result = await session.execute(
            delete(OrganizationMember).where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            )
        )
        await session.flush()
        return result.rowcount > 0

    @staticmethod
    async def create_invitation(
        session: AsyncSession,
        *,
        organization_id: str,
        email: str,
        role: str,
        token_hash: str,
        invited_by_user_id: str,
        expires_at: datetime,
    ) -> OrganizationInvitation:
        invitation = OrganizationInvitation(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            email=email.lower(),
            role=role,
            token_hash=token_hash,
            status="pending",
            invited_by_user_id=invited_by_user_id,
            expires_at=expires_at,
        )
        session.add(invitation)
        await session.flush()
        return invitation

    @staticmethod
    async def list_pending_invitations(
        session: AsyncSession,
        organization_id: str,
    ) -> List[OrganizationInvitation]:
        result = await session.execute(
            select(OrganizationInvitation)
            .where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.status == "pending",
            )
            .order_by(OrganizationInvitation.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_pending_invitation(
        session: AsyncSession,
        organization_id: str,
        invitation_id: str,
    ) -> Optional[OrganizationInvitation]:
        result = await session.execute(
            select(OrganizationInvitation).where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.id == invitation_id,
                OrganizationInvitation.status == "pending",
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_pending_invitation_for_email(
        session: AsyncSession,
        organization_id: str,
        email: str,
    ) -> Optional[OrganizationInvitation]:
        result = await session.execute(
            select(OrganizationInvitation).where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.email == email.lower(),
                OrganizationInvitation.status == "pending",
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_invitation_by_token_hash(
        session: AsyncSession,
        token_hash: str,
        *,
        for_update: bool = False,
    ) -> Optional[OrganizationInvitation]:
        query = select(OrganizationInvitation).where(OrganizationInvitation.token_hash == token_hash)
        if for_update:
            query = query.with_for_update()
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    def is_expired(invitation: OrganizationInvitation) -> bool:
        return invitation.expires_at <= datetime.now(timezone.utc)
