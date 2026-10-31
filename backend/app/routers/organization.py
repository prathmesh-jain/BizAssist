from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.db.base import get_db_session
from app.dependencies import (
    AuthenticatedCaller,
    CurrentUser,
    MemberManager,
    MemberReader,
    OrganizationManager,
)
from app.services import membership_service as svc

router = APIRouter(prefix="/api", tags=["organization"])

RoleName = Literal["viewer", "member", "admin", "owner"]


class RenameOrganizationRequest(BaseModel):
    name: str


class UpdateMemberRequest(BaseModel):
    role: Optional[RoleName] = None
    status: Optional[Literal["active", "suspended"]] = None


class CreateInvitationRequest(BaseModel):
    email: EmailStr
    role: RoleName = "member"


class InvitationTokenRequest(BaseModel):
    token: str


def _http(exc: svc.MembershipError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


def _invitation_public(invitation) -> dict:
    return {
        "id": invitation.id,
        "email": invitation.email,
        "role": invitation.role,
        "status": invitation.status,
        "expires_at": invitation.expires_at,
        "created_at": invitation.created_at,
    }


@router.patch("/organization")
async def rename_organization(body: RenameOrganizationRequest, user: OrganizationManager, session = Depends(get_db_session)):
    try:
        organization = await svc.rename_organization(session, user, body.name)
    except svc.MembershipError as exc:
        raise _http(exc) from exc
    return {"id": organization.id, "name": organization.name, "slug": organization.slug}


@router.get("/organization/members")
async def list_members(user: MemberReader, session = Depends(get_db_session)):
    return {"members": await svc.list_members(session, user)}


@router.patch("/organization/members/{user_id}")
async def update_member(user_id: str, body: UpdateMemberRequest, user: MemberManager, session = Depends(get_db_session)):
    if body.role is None and body.status is None:
        raise HTTPException(status_code=400, detail="Provide a role or status to change.")
    try:
        member = await svc.update_member(session, user, user_id, role=body.role, status=body.status)
    except svc.MembershipError as exc:
        raise _http(exc) from exc
    return {"user_id": member.user_id, "role": member.role, "status": member.status}


@router.delete("/organization/members/{user_id}")
async def remove_member(user_id: str, user: MemberManager, session = Depends(get_db_session)):
    try:
        await svc.remove_member(session, user, user_id)
    except svc.MembershipError as exc:
        raise _http(exc) from exc
    return {"ok": True}


@router.post("/organization/leave")
async def leave_organization(user: CurrentUser, session = Depends(get_db_session)):
    try:
        await svc.leave_organization(session, user)
    except svc.MembershipError as exc:
        raise _http(exc) from exc
    return {"ok": True}


@router.get("/organization/invitations")
async def list_invitations(user: MemberManager, session = Depends(get_db_session)):
    invitations = await svc.list_invitations(session, user)
    return {"invitations": [_invitation_public(i) for i in invitations]}


@router.post("/organization/invitations")
async def create_invitation(body: CreateInvitationRequest, user: MemberManager, session = Depends(get_db_session)):
    """Create an invitation. The link is returned once; only its hash is stored.

    There is no email delivery yet, so the inviter shares the link themselves.
    """
    try:
        invitation, token = await svc.create_invitation(session, user, email=body.email, role=body.role)
    except svc.MembershipError as exc:
        raise _http(exc) from exc
    return {"invitation": _invitation_public(invitation), "invite_url": svc.build_invitation_url(token)}


@router.delete("/organization/invitations/{invitation_id}")
async def revoke_invitation(invitation_id: str, user: MemberManager, session = Depends(get_db_session)):
    try:
        await svc.revoke_invitation(session, user, invitation_id)
    except svc.MembershipError as exc:
        raise _http(exc) from exc
    return {"ok": True}


# Invitation acceptance needs only an authenticated caller: the invitee may not
# have an active membership anywhere yet.
@router.post("/invitations/preview")
async def preview_invitation(body: InvitationTokenRequest, caller: AuthenticatedCaller, session = Depends(get_db_session)):
    try:
        return await svc.preview_invitation(session, caller, body.token)
    except svc.MembershipError as exc:
        raise _http(exc) from exc


@router.post("/invitations/accept")
async def accept_invitation(body: InvitationTokenRequest, caller: AuthenticatedCaller, session = Depends(get_db_session)):
    try:
        return await svc.accept_invitation(session, caller, body.token)
    except svc.MembershipError as exc:
        raise _http(exc) from exc
