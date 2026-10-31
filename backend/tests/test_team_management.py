"""Invitations and member administration."""


def _token(invite_url: str) -> str:
    return invite_url.split("#token=", 1)[1]


async def _invite(client, email, role="member"):
    resp = await client.post("/api/organization/invitations", json={"email": email, "role": role})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _onboard(make_user, client_for, owner_client, owner_ctx, uid, email, role):
    """Invite + accept through the API; return the new member's context in the owner's org."""
    token = _token((await _invite(owner_client, email, role))["invite_url"])
    invitee = client_for(await make_user(uid, email))
    accepted = await invitee.post("/api/invitations/accept", json={"token": token})
    assert accepted.status_code == 200, accepted.text
    return await make_user(uid, email, organization_id=owner_ctx.organization.id)


async def test_invite_preview_accept_flow(make_user, client_for):
    owner_ctx = await make_user("uid-o", "owner@acme.com")
    owner = client_for(owner_ctx)

    created = await _invite(owner, "New.Hire@Acme.com", "member")
    assert created["invitation"]["email"] == "new.hire@acme.com"
    assert "#token=" in created["invite_url"]
    token = _token(created["invite_url"])

    pending = (await owner.get("/api/organization/invitations")).json()["invitations"]
    assert [i["email"] for i in pending] == ["new.hire@acme.com"]

    invitee_ctx = await make_user("uid-n", "new.hire@acme.com")
    invitee = client_for(invitee_ctx)
    preview = (await invitee.post("/api/invitations/preview", json={"token": token})).json()
    assert preview["organization_id"] == owner_ctx.organization.id
    assert preview["role"] == "member" and preview["email_matches"] is True

    accepted = await invitee.post("/api/invitations/accept", json={"token": token})
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "member"

    # The link is single-use, and the invitation no longer shows as pending.
    assert (await invitee.post("/api/invitations/accept", json={"token": token})).status_code == 404
    assert (await owner.get("/api/organization/invitations")).json()["invitations"] == []

    in_org = await make_user("uid-n", "new.hire@acme.com", organization_id=owner_ctx.organization.id)
    assert in_org.role == "member"
    members = (await owner.get("/api/organization/members")).json()["members"]
    assert {m["email"]: m["role"] for m in members} == {"owner@acme.com": "owner", "new.hire@acme.com": "member"}


async def test_invitation_must_match_verified_email(make_user, client_for):
    owner = client_for(await make_user("uid-o", "owner@acme.com"))
    token = _token((await _invite(owner, "invitee@acme.com"))["invite_url"])

    stranger = client_for(await make_user("uid-s", "stranger@else.com"))
    assert (await stranger.post("/api/invitations/accept", json={"token": token})).status_code == 403

    unverified = client_for(await make_user("uid-i", "invitee@acme.com"), email_verified=False)
    assert (await unverified.post("/api/invitations/accept", json={"token": token})).status_code == 403

    assert (await stranger.post("/api/invitations/accept", json={"token": "garbage"})).status_code == 404


async def test_reinvite_and_revoke_invalidate_old_links(make_user, client_for):
    owner = client_for(await make_user("uid-o", "owner@acme.com"))
    first = _token((await _invite(owner, "x@acme.com"))["invite_url"])
    second_resp = await _invite(owner, "x@acme.com", "viewer")
    second = _token(second_resp["invite_url"])

    invitee = client_for(await make_user("uid-x", "x@acme.com"))
    assert (await invitee.post("/api/invitations/accept", json={"token": first})).status_code == 404

    invitation_id = second_resp["invitation"]["id"]
    assert (await owner.delete(f"/api/organization/invitations/{invitation_id}")).status_code == 200
    assert (await invitee.post("/api/invitations/accept", json={"token": second})).status_code == 404


async def test_expired_invitation_is_rejected(make_user, client_for):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from app.db.base import session_scope
    from app.db.models import OrganizationInvitation

    owner = client_for(await make_user("uid-o", "owner@acme.com"))
    token = _token((await _invite(owner, "late@acme.com"))["invite_url"])
    async with session_scope() as session:
        await session.execute(
            update(OrganizationInvitation).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )

    late = client_for(await make_user("uid-l", "late@acme.com"))
    resp = await late.post("/api/invitations/accept", json={"token": token})
    assert resp.status_code == 400 and "expired" in resp.json()["detail"]


async def test_invite_rules(make_user, client_for):
    owner_ctx = await make_user("uid-o", "owner@acme.com")
    owner = client_for(owner_ctx)
    admin_ctx = await _onboard(make_user, client_for, owner, owner_ctx, "uid-a", "admin@acme.com", "admin")
    member_ctx = await _onboard(make_user, client_for, owner, owner_ctx, "uid-m", "member@acme.com", "member")
    admin, member = client_for(admin_ctx), client_for(member_ctx)

    # Members can't invite; admins can invite below their own rank only.
    assert (await member.post("/api/organization/invitations", json={"email": "a@b.com"})).status_code == 403
    assert (await admin.post("/api/organization/invitations", json={"email": "a@b.com", "role": "member"})).status_code == 200
    assert (await admin.post("/api/organization/invitations", json={"email": "c@b.com", "role": "admin"})).status_code == 403
    assert (await owner.post("/api/organization/invitations", json={"email": "c@b.com", "role": "admin"})).status_code == 200

    # Inviting an existing active member is a conflict.
    assert (await owner.post("/api/organization/invitations", json={"email": "member@acme.com"})).status_code == 409
    assert (await owner.post("/api/organization/invitations", json={"email": "not-an-email"})).status_code == 422


async def test_role_changes_suspension_and_removal(make_user, client_for):
    from fastapi import HTTPException

    owner_ctx = await make_user("uid-o", "owner@acme.com")
    owner = client_for(owner_ctx)
    admin_ctx = await _onboard(make_user, client_for, owner, owner_ctx, "uid-a", "admin@acme.com", "admin")
    member_ctx = await _onboard(make_user, client_for, owner, owner_ctx, "uid-m", "member@acme.com", "member")
    admin = client_for(admin_ctx)
    m_id, a_id, o_id = member_ctx.user.id, admin_ctx.user.id, owner_ctx.user.id

    # Admins manage lower roles but can't promote to admin or touch admins/owners.
    assert (await admin.patch(f"/api/organization/members/{m_id}", json={"role": "viewer"})).status_code == 200
    assert (await admin.patch(f"/api/organization/members/{m_id}", json={"role": "admin"})).status_code == 403
    assert (await admin.patch(f"/api/organization/members/{o_id}", json={"status": "suspended"})).status_code == 403
    assert (await admin.patch(f"/api/organization/members/{a_id}", json={"role": "member"})).status_code == 400  # self

    # Suspension blocks access immediately and hides the member from non-managers.
    assert (await admin.patch(f"/api/organization/members/{m_id}", json={"status": "suspended"})).status_code == 200
    try:
        await make_user("uid-m", "member@acme.com", organization_id=owner_ctx.organization.id)
        raise AssertionError("suspended member was let in")
    except HTTPException as exc:
        assert exc.status_code == 403
    listed = (await admin.get("/api/organization/members")).json()["members"]
    assert {m["email"]: m["status"] for m in listed}["member@acme.com"] == "suspended"

    # Removal deletes the membership.
    assert (await admin.delete(f"/api/organization/members/{m_id}")).status_code == 200
    emails = {m["email"] for m in (await owner.get("/api/organization/members")).json()["members"]}
    assert emails == {"owner@acme.com", "admin@acme.com"}
    assert (await admin.delete(f"/api/organization/members/{m_id}")).status_code == 404


async def test_organization_always_keeps_an_owner(make_user, client_for):
    owner_ctx = await make_user("uid-o", "owner@acme.com")
    owner = client_for(owner_ctx)

    # The sole owner can't leave.
    assert (await owner.post("/api/organization/leave")).status_code == 409

    second_ctx = await _onboard(make_user, client_for, owner, owner_ctx, "uid-2", "two@acme.com", "owner")
    second = client_for(second_ctx)

    # With two owners one may demote the other, but not the last remaining one.
    assert (await second.patch(f"/api/organization/members/{owner_ctx.user.id}", json={"role": "admin"})).status_code == 200
    demoted = await make_user("uid-o", "owner@acme.com", organization_id=owner_ctx.organization.id)
    assert (await client_for(demoted).patch(
        f"/api/organization/members/{second_ctx.user.id}", json={"role": "admin"}
    )).status_code == 403
    assert (await second.post("/api/organization/leave")).status_code == 409

    # Once there's another owner again, leaving works.
    assert (await second.patch(f"/api/organization/members/{owner_ctx.user.id}", json={"role": "owner"})).status_code == 200
    assert (await second.post("/api/organization/leave")).status_code == 200


async def test_rename_requires_admin(make_user, client_for):
    owner_ctx = await make_user("uid-o", "owner@acme.com")
    owner = client_for(owner_ctx)
    viewer_ctx = await _onboard(make_user, client_for, owner, owner_ctx, "uid-v", "v@acme.com", "viewer")

    assert (await client_for(viewer_ctx).patch("/api/organization", json={"name": "Hijack"})).status_code == 403
    resp = await owner.patch("/api/organization", json={"name": "  Acme Ltd  "})
    assert resp.status_code == 200 and resp.json()["name"] == "Acme Ltd"
    assert (await owner.patch("/api/organization", json={"name": "   "})).status_code == 400
