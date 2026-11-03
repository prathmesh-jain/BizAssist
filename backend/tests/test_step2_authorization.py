"""Step 2: organization context, membership roles, and resource ownership."""
import pytest
from sqlalchemy import update


async def _join(make_user, owner_ctx, uid: str, email: str, role: str):
    """Create a user and add them to owner_ctx's organization with `role`; return that org context."""
    from app.db.base import session_scope
    from app.repositories import UserRepository

    personal = await make_user(uid, email)
    async with session_scope() as session:
        await UserRepository.create_organization_member(
            session, owner_ctx.organization.id, personal.user.id, role=role
        )
    return await make_user(uid, email, organization_id=owner_ctx.organization.id)


async def _set(model, where, **values):
    from app.db.base import session_scope

    async with session_scope() as session:
        await session.execute(update(model).where(where).values(**values))


async def _create_document(ctx, filename="report.pdf"):
    from app.db.base import session_scope
    from app.repositories import DocumentRepository

    async with session_scope() as session:
        doc = await DocumentRepository.create(
            session,
            organization_id=ctx.organization.id,
            uploaded_by_user_id=ctx.user.id,
            filename=filename,
            file_type="application/pdf",
            status="ready",
        )
        return doc.id


@pytest.fixture
def no_qdrant(monkeypatch):
    from app.routers import documents

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(documents, "delete_document_chunks", _noop)


async def test_role_comes_from_membership_and_header_selects_org(make_user, client_for):
    owner = await make_user("uid-o", "owner@acme.com")
    assert owner.role == "owner"

    viewer = await _join(make_user, owner, "uid-v", "viewer@acme.com", "viewer")
    assert viewer.role == "viewer"
    assert viewer.organization.id == owner.organization.id

    # Without the header the user lands in their own (oldest) workspace as owner.
    default = await make_user("uid-v", "viewer@acme.com")
    assert default.organization.id != owner.organization.id
    assert default.role == "owner"

    me = (await client_for(viewer).get("/api/me")).json()
    assert me["role"] == "viewer"
    assert "document.upload" not in me["permissions"]
    assert {m["organization_id"] for m in me["memberships"]} == {
        owner.organization.id,
        default.organization.id,
    }


async def test_non_member_suspended_and_inactive_org_are_rejected(make_user):
    from fastapi import HTTPException

    from app.db.models import Organization, OrganizationMember

    owner = await make_user("uid-o", "owner@acme.com")
    outsider = await make_user("uid-x", "x@other.com")

    with pytest.raises(HTTPException) as exc:
        await make_user("uid-x", "x@other.com", organization_id=owner.organization.id)
    assert exc.value.status_code == 403

    member = await _join(make_user, owner, "uid-m", "member@acme.com", "member")
    await _set(
        OrganizationMember,
        (OrganizationMember.user_id == member.user.id)
        & (OrganizationMember.organization_id == owner.organization.id),
        status="suspended",
    )
    with pytest.raises(HTTPException) as exc:
        await make_user("uid-m", "member@acme.com", organization_id=owner.organization.id)
    assert exc.value.status_code == 403

    await _set(Organization, Organization.id == outsider.organization.id, is_active=False)
    with pytest.raises(HTTPException) as exc:
        await make_user("uid-x", "x@other.com")
    assert exc.value.status_code == 403


async def test_unverified_email_cannot_take_over_existing_account(make_user):
    from fastapi import HTTPException

    original = await make_user("uid-real", "victim@acme.com")

    with pytest.raises(HTTPException) as exc:
        await make_user("uid-attacker", "victim@acme.com", email_verified=False)
    assert exc.value.status_code == 403

    linked = await make_user("uid-second-login", "victim@acme.com", email_verified=True)
    assert linked.user.id == original.user.id

    # A brand-new account doesn't need verification to get started.
    fresh = await make_user("uid-new", "new@acme.com", email_verified=False)
    assert fresh.role == "owner"


async def test_chats_are_private_to_their_creator(make_user, client_for):
    alice_ctx = await make_user("uid-a", "alice@acme.com")
    bob_ctx = await _join(make_user, alice_ctx, "uid-b", "bob@acme.com", "admin")
    alice, bob = client_for(alice_ctx), client_for(bob_ctx)

    chat_id = (await alice.post("/api/chat", json={"title": "Payroll"})).json()["id"]

    assert (await bob.get("/api/chat")).json() == []
    assert (await bob.get(f"/api/chat/{chat_id}/messages")).status_code == 404
    assert (await bob.patch(f"/api/chat/{chat_id}", json={"title": "x"})).status_code == 404
    assert (await bob.delete(f"/api/chat/{chat_id}")).status_code == 404
    assert (
        await bob.post(f"/api/chat/{chat_id}/interrupt-resolve", json={"action": "accept"})
    ).status_code == 404
    assert [c["id"] for c in (await alice.get("/api/chat")).json()] == [chat_id]


async def test_document_permissions(make_user, client_for, no_qdrant):
    owner_ctx = await make_user("uid-o", "owner@acme.com")
    viewer_ctx = await _join(make_user, owner_ctx, "uid-v", "viewer@acme.com", "viewer")
    member_ctx = await _join(make_user, owner_ctx, "uid-m", "member@acme.com", "member")
    viewer, member, owner = client_for(viewer_ctx), client_for(member_ctx), client_for(owner_ctx)

    upload = await viewer.post(
        "/api/documents/upload", files={"file": ("a.txt", b"hello", "text/plain")}
    )
    assert upload.status_code == 403

    owners_doc = await _create_document(owner_ctx, "owner.pdf")
    members_doc = await _create_document(member_ctx, "member.pdf")

    # Everyone in the org can read the shared document list.
    listed = {d["id"] for d in (await viewer.get("/api/documents")).json()}
    assert listed == {owners_doc, members_doc}

    assert (await viewer.delete(f"/api/documents/{members_doc}")).status_code == 403
    assert (await member.delete(f"/api/documents/{owners_doc}")).status_code == 403
    assert (await member.delete(f"/api/documents/{members_doc}")).status_code == 200
    assert (await owner.delete(f"/api/documents/{owners_doc}")).status_code == 200

    outsider = client_for(await make_user("uid-x", "x@other.com"))
    assert (await outsider.get("/api/documents")).json() == []


async def test_integration_management_requires_admin(make_user, client_for):
    owner_ctx = await make_user("uid-o", "owner@acme.com")
    member_ctx = await _join(make_user, owner_ctx, "uid-m", "member@acme.com", "member")
    member, owner = client_for(member_ctx), client_for(owner_ctx)

    assert (await member.get("/api/integrations/google-sheets/status")).status_code == 200
    assert (await member.post("/api/integrations/google-sheets/connect", json={})).status_code == 403
    assert (
        await member.post("/api/integrations/google-sheets/callback", json={"code": "c", "state": "s"})
    ).status_code == 403

    # An admin may connect, but not attach the OAuth flow to someone else's chat.
    members_chat = (await member.post("/api/chat", json={})).json()["id"]
    resp = await owner.post("/api/integrations/google-sheets/connect", json={"chat_id": members_chat})
    assert resp.status_code == 404


async def test_oauth_state_is_bound_to_its_organization(make_user):
    from app.db.base import session_scope
    from app.repositories import OAuthStateRepository

    owner = await make_user("uid-o", "owner@acme.com")
    other_org = await make_user("uid-o2", "owner2@other.com")
    async with session_scope() as session:
        await OAuthStateRepository.create(
            session, user_id=owner.user.id, state_hash="h", organization_id=owner.organization.id
        )
        assert await OAuthStateRepository.get_valid_state(session, owner.user.id, owner.organization.id, "h")
        assert not await OAuthStateRepository.get_valid_state(
            session, owner.user.id, other_org.organization.id, "h"
        )


async def test_sheets_write_tools_respect_role(make_user):
    from app.tools.google_sheets_tools import get_sheets_tools

    owner = await make_user("uid-o", "owner@acme.com")

    def tool(role, name):
        tools = get_sheets_tools(user_id=owner.user.id, organization_id=owner.organization.id, role=role)
        return next(t for t in tools if t.name == name)

    args = {"spreadsheet_id": "sid", "range_a1": "Sheet1!A1", "values": [["x"]]}

    blocked = await tool("viewer", "sheets_append_values").ainvoke(args)
    assert blocked["ok"] is False and "role (viewer)" in blocked["error"]

    # A member passes the role check and reaches the integration (not connected here).
    allowed = await tool("member", "sheets_append_values").ainvoke(args)
    assert allowed["ok"] is False and "not connected" in allowed["error"]

    # Reads are open to viewers.
    read = await tool("viewer", "sheets_read_range").ainvoke({"spreadsheet_id": "sid", "range_a1": "Sheet1!A1"})
    assert "role" not in read.get("error", "")
