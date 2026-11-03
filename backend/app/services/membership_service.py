"""Organization membership rules: invitations, role changes, suspension, removal.

All checks live here so routers stay thin and every entry point applies the same
rules: who may manage whom, which roles may be granted, and that an organization
never loses its last active owner.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import ROLE_RANK, can, can_assign_role, can_manage_member
from app.config import get_settings
from app.db.models import OrganizationInvitation, OrganizationMember
from app.models.user import AuthenticatedUser, CurrentUserContext
from app.repositories import MembershipRepository, UserRepository

settings = get_settings()

MEMBER_STATUSES = {"active", "suspended"}


class MembershipError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class MembershipNotFound(MembershipError):
    status_code = 404


class MembershipForbidden(MembershipError):
    status_code = 403


class MembershipConflict(MembershipError):
    status_code = 409


def hash_invitation_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def build_invitation_url(token: str) -> str:
    # Token goes in the fragment so it never reaches server logs or Referer headers.
    return f"{settings.frontend_url.rstrip('/')}/invite#token={token}"


def _require(actor: CurrentUserContext, action: str) -> None:
    if not can(actor.role, action):
        raise MembershipForbidden(f"Your role ({actor.role}) does not allow this action.")


def _validate_role(role: str) -> None:
    if role not in ROLE_RANK:
        raise MembershipError(f"Unknown role '{role}'. Use one of: {', '.join(ROLE_RANK)}.")


async def _ensure_not_last_owner(session: AsyncSession, member: OrganizationMember) -> None:
    """Refuse a change that would leave the organization with no active owner."""
    if member.role != "owner" or member.status != "active":
        return
    if await MembershipRepository.count_active_owners(session, member.organization_id) <= 1:
        raise MembershipConflict(
            "An organization needs at least one active owner. Make someone else an owner first."
        )


async def _get_target(session: AsyncSession, actor: CurrentUserContext, user_id: str) -> OrganizationMember:
    if user_id == actor.user.id:
        raise MembershipError("You can't change your own membership here; use leave instead.")
    member = await MembershipRepository.get_member(session, actor.organization.id, user_id)
    if not member:
        raise MembershipNotFound("Member not found.")
    if not can_manage_member(actor.role, member.role):
        raise MembershipForbidden(f"Your role ({actor.role}) can't manage a member with role {member.role}.")
    return member


async def list_members(session: AsyncSession, actor: CurrentUserContext) -> list[dict]:
    _require(actor, "member.read")
    rows = await MembershipRepository.list_members(session, actor.organization.id)
    can_manage = can(actor.role, "member.manage")
    return [
        {
            "user_id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": member.role,
            "status": member.status,
            "joined_at": member.created_at,
            "is_you": user.id == actor.user.id,
            "can_manage": can_manage and user.id != actor.user.id and can_manage_member(actor.role, member.role),
        }
        for member, user in rows
        # Members only see who is active; managers also see suspended members.
        if member.status == "active" or can_manage
    ]


async def update_member(
    session: AsyncSession,
    actor: CurrentUserContext,
    user_id: str,
    *,
    role: str | None = None,
    status: str | None = None,
) -> OrganizationMember:
    _require(actor, "member.manage")
    member = await _get_target(session, actor, user_id)

    if role is not None:
        _validate_role(role)
        if not can_assign_role(actor.role, role):
            raise MembershipForbidden(f"Your role ({actor.role}) can't grant the {role} role.")
    if status is not None and status not in MEMBER_STATUSES:
        raise MembershipError(f"Status must be one of: {', '.join(sorted(MEMBER_STATUSES))}.")

    demoting_owner = role is not None and role != "owner"
    deactivating = status is not None and status != "active"
    if demoting_owner or deactivating:
        await _ensure_not_last_owner(session, member)

    if role is not None:
        member.role = role
    if status is not None:
        member.status = status
    await session.flush()
    return member


async def remove_member(session: AsyncSession, actor: CurrentUserContext, user_id: str) -> None:
    _require(actor, "member.manage")
    member = await _get_target(session, actor, user_id)
    await _ensure_not_last_owner(session, member)
    await MembershipRepository.delete_member(session, actor.organization.id, user_id)


async def leave_organization(session: AsyncSession, actor: CurrentUserContext) -> None:
    member = await MembershipRepository.get_member(session, actor.organization.id, actor.user.id)
    if not member:
        raise MembershipNotFound("You are not a member of this organization.")
    await _ensure_not_last_owner(session, member)
    await MembershipRepository.delete_member(session, actor.organization.id, actor.user.id)


async def rename_organization(session: AsyncSession, actor: CurrentUserContext, name: str):
    _require(actor, "organization.manage")
    name = (name or "").strip()
    if not name:
        raise MembershipError("Organization name is required.")
    if len(name) > 120:
        raise MembershipError("Organization name must be 120 characters or fewer.")
    organization = await UserRepository.get_organization(session, actor.organization.id)
    organization.name = name
    await session.flush()
    return organization


async def create_invitation(
    session: AsyncSession,
    actor: CurrentUserContext,
    *,
    email: str,
    role: str,
) -> tuple[OrganizationInvitation, str]:
    """Create (or re-issue) an invitation. Returns the invitation and its one-time raw token."""
    _require(actor, "member.manage")
    _validate_role(role)
    if not can_assign_role(actor.role, role):
        raise MembershipForbidden(f"Your role ({actor.role}) can't invite someone as {role}.")

    email = email.strip().lower()
    existing = await MembershipRepository.get_member_by_email(session, actor.organization.id, email)
    if existing and existing.status == "active":
        raise MembershipConflict(f"{email} is already a member of this organization.")

    # Re-inviting replaces the previous open invitation (and invalidates its link).
    previous = await MembershipRepository.get_pending_invitation_for_email(session, actor.organization.id, email)
    if previous:
        previous.status = "revoked"
        await session.flush()

    token = secrets.token_urlsafe(32)
    invitation = await MembershipRepository.create_invitation(
        session,
        organization_id=actor.organization.id,
        email=email,
        role=role,
        token_hash=hash_invitation_token(token),
        invited_by_user_id=actor.user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.invitation_ttl_days),
    )
    return invitation, token


async def list_invitations(session: AsyncSession, actor: CurrentUserContext) -> list[OrganizationInvitation]:
    _require(actor, "member.manage")
    return await MembershipRepository.list_pending_invitations(session, actor.organization.id)


async def revoke_invitation(session: AsyncSession, actor: CurrentUserContext, invitation_id: str) -> None:
    _require(actor, "member.manage")
    invitation = await MembershipRepository.get_pending_invitation(session, actor.organization.id, invitation_id)
    if not invitation:
        raise MembershipNotFound("Invitation not found.")
    invitation.status = "revoked"
    await session.flush()


async def _usable_invitation(session: AsyncSession, token: str, *, for_update: bool = False):
    invitation = await MembershipRepository.get_invitation_by_token_hash(
        session, hash_invitation_token(token or ""), for_update=for_update
    )
    if not invitation or invitation.status != "pending":
        raise MembershipNotFound("This invitation is invalid or has already been used.")
    if MembershipRepository.is_expired(invitation):
        raise MembershipError("This invitation has expired. Ask for a new one.")
    organization = await UserRepository.get_organization(session, invitation.organization_id)
    if not organization or not organization.is_active:
        raise MembershipNotFound("This organization is no longer available.")
    return invitation, organization


async def preview_invitation(session: AsyncSession, caller: AuthenticatedUser, token: str) -> dict:
    invitation, organization = await _usable_invitation(session, token)
    return {
        "organization_id": organization.id,
        "organization_name": organization.name,
        "role": invitation.role,
        "email": invitation.email,
        "email_matches": invitation.email == caller.user.email.lower(),
        "expires_at": invitation.expires_at,
    }


async def accept_invitation(session: AsyncSession, caller: AuthenticatedUser, token: str) -> dict:
    invitation, organization = await _usable_invitation(session, token, for_update=True)

    if invitation.email != caller.user.email.lower():
        raise MembershipForbidden(
            f"This invitation was sent to {invitation.email}. Sign in with that email to accept it."
        )
    if not caller.email_verified:
        raise MembershipForbidden("Verify your email address before accepting an invitation.")

    member = await MembershipRepository.get_member(session, organization.id, caller.user.id)
    if member is None:
        member = await UserRepository.create_organization_member(
            session, organization.id, caller.user.id, role=invitation.role
        )
    elif member.status != "active":
        # An explicit new invitation restores a suspended member with the invited role.
        member.status = "active"
        member.role = invitation.role

    invitation.status = "accepted"
    invitation.accepted_by_user_id = caller.user.id
    await session.flush()
    return {"organization_id": organization.id, "organization_name": organization.name, "role": member.role}
