import logging
import uuid
from typing import Annotated

import firebase_admin
from firebase_admin import auth, credentials
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.authz import can
from app.config import get_settings
from sqlalchemy import text

from app.db.base import get_db_session, session_scope
from app.models.user import AuthenticatedUser, UserInDB, Organization, CurrentUserContext
from app.repositories import UserRepository

logger = logging.getLogger(__name__)
settings = get_settings()

security = HTTPBearer()


def _service_account_info_from_env() -> dict | None:
    if not settings.firebase_client_email or not settings.firebase_private_key:
        return None

    private_key = settings.firebase_private_key
    if "\\n" in private_key:
        private_key = private_key.replace("\\n", "\n")

    info: dict = {
        "type": settings.firebase_type or "service_account",
        "project_id": settings.firebase_project_id or "",
        "private_key_id": settings.firebase_private_key_id or "",
        "private_key": private_key,
        "client_email": settings.firebase_client_email,
        "client_id": settings.firebase_client_id or "",
        "auth_uri": settings.firebase_auth_uri or "https://accounts.google.com/o/oauth2/auth",
        "token_uri": settings.firebase_token_uri or "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": settings.firebase_auth_provider_x509_cert_url
        or "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": settings.firebase_client_x509_cert_url or "",
    }

    if settings.firebase_universe_domain:
        info["universe_domain"] = settings.firebase_universe_domain

    return info


def _workspace_slug(email: str) -> str:
    # Suffix keeps slugs unique when two emails share a local part (john@a.com, john@b.com).
    return f"{email.split('@')[0].lower()}-{uuid.uuid4().hex[:8]}"


def _init_firebase_admin() -> None:
    if firebase_admin._apps:
        return

    service_account_info = _service_account_info_from_env()
    if service_account_info is None:
        logger.error(
            "Firebase credentials missing. Set FIREBASE_CLIENT_EMAIL and FIREBASE_PRIVATE_KEY."
        )
        raise RuntimeError("Missing Firebase service account credentials")

    cred = credentials.Certificate(service_account_info)
    opts = {}
    if settings.firebase_project_id:
        opts["projectId"] = settings.firebase_project_id
    firebase_admin.initialize_app(cred, opts or None)


def _verify_firebase_token(token: str) -> dict:
    try:
        _init_firebase_admin()
        decoded = auth.verify_id_token(token, clock_skew_seconds=5)
    except Exception as e:
        logger.error("Token verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    if not decoded.get("uid"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    if not decoded.get("email"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email address required")
    return decoded


async def _advisory_lock(session, key: str) -> None:
    """Transaction-scoped Postgres lock: concurrent holders of the same key run one at a time."""
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})


async def _resolve_user(session, decoded: dict):
    """Map a verified Firebase identity to an application user, provisioning on first login."""
    firebase_uid = decoded["uid"]
    email = decoded["email"]
    full_name = decoded.get("name") or None  # email/password sign-ups have no display name

    identity = await UserRepository.get_identity_by_provider(session, "firebase", firebase_uid)
    if not identity:
        # First login. A new client fires several requests at once, so provision in a short
        # transaction of its own, serialized per identity, and re-check under the lock.
        async with session_scope() as provisioning:
            await _advisory_lock(provisioning, f"identity:firebase:{firebase_uid}")
            identity = await UserRepository.get_identity_by_provider(provisioning, "firebase", firebase_uid)
            if identity:
                user_id = identity.user_id
            else:
                existing_user = await UserRepository.get_by_email(provisioning, email)
                if existing_user:
                    # Linking a new identity to an existing account by email is only safe when
                    # the provider has verified that the caller owns the address.
                    if not decoded.get("email_verified"):
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Verify your email address to sign in to this existing account.",
                        )
                    user_id = existing_user.id
                else:
                    user_id = (await UserRepository.create(provisioning, email, full_name)).id
                await UserRepository.create_identity(provisioning, user_id, "firebase", firebase_uid)
            if not await UserRepository.get_ai_settings(provisioning, user_id):
                await UserRepository.create_ai_settings(provisioning, user_id)
    else:
        user_id = identity.user_id

    user = await UserRepository.get_by_id(session, user_id)
    if not user:
        logger.error("Identity found for %s but user %s is missing", firebase_uid, user_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User record not found")
    return user


async def _resolve_membership(session, user, organization_id: str | None):
    """Pick the organization for this request and the user's membership in it."""
    if organization_id:
        found = await UserRepository.get_active_membership(session, user.id, organization_id)
        if not found:
            # Same response whether the org doesn't exist or the user isn't in it.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not an active member of this organization.",
            )
        return found

    found = await UserRepository.get_active_membership(session, user.id)
    if found:
        return found

    # No active membership. If the user has none at all (first login), give them a personal
    # workspace they own. Decide under a per-user lock so parallel first requests create only
    # one, and re-read afterwards rather than trusting a check made before another request
    # may have committed.
    async with session_scope() as provisioning:
        await _advisory_lock(provisioning, f"membership:{user.id}")
        if not await UserRepository.list_memberships(provisioning, user.id):
            organization = await UserRepository.create_organization(
                provisioning, f"{user.full_name or user.email.split('@')[0]}'s Workspace", _workspace_slug(user.email)
            )
            await UserRepository.create_organization_member(provisioning, organization.id, user.id, role="owner")

    found = await UserRepository.get_active_membership(session, user.id)
    if not found:
        # Memberships exist but all are suspended or their organizations are inactive.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You have no active organization membership.",
        )
    return found


async def get_authenticated_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session = Depends(get_db_session, scope="function"),
) -> AuthenticatedUser:
    """Authenticate the caller only (no organization context).

    Used by endpoints that must work before an organization is chosen, such as
    accepting an invitation.
    """
    decoded = _verify_firebase_token(credentials.credentials)
    user = await _resolve_user(session, decoded)
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled.")

    return AuthenticatedUser(
        user=UserInDB(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            created_at=user.created_at,
            is_active=user.is_active,
        ),
        email_verified=bool(decoded.get("email_verified")),
    )


AuthenticatedCaller = Annotated[AuthenticatedUser, Depends(get_authenticated_user)]


async def get_current_user(
    identity: AuthenticatedCaller,
    session = Depends(get_db_session, scope="function"),
    x_organization_id: str | None = Header(default=None),
) -> CurrentUserContext:
    """Resolve the authenticated caller's organization context and role.

    Clients may select an organization with the X-Organization-Id header; without it
    the user's default (oldest active) membership is used.
    """
    user = await UserRepository.get_by_id(session, identity.user.id)
    member, organization = await _resolve_membership(session, user, x_organization_id)

    return CurrentUserContext(
        user=identity.user,
        organization=Organization(
            id=organization.id,
            name=organization.name,
            slug=organization.slug,
            is_active=organization.is_active,
            created_at=organization.created_at,
            updated_at=organization.updated_at,
        ),
        role=member.role,
    )


CurrentUser = Annotated[CurrentUserContext, Depends(get_current_user)]


def require_action(action: str):
    """Dependency factory: the current member must be allowed to perform `action`."""

    async def _dependency(user: CurrentUser) -> CurrentUserContext:
        if not can(user.role, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your role ({user.role}) does not allow this action.",
            )
        return user

    return _dependency


ChatUser = Annotated[CurrentUserContext, Depends(require_action("chat.use"))]
DocumentReader = Annotated[CurrentUserContext, Depends(require_action("document.read"))]
DocumentUploader = Annotated[CurrentUserContext, Depends(require_action("document.upload"))]
IntegrationReader = Annotated[CurrentUserContext, Depends(require_action("integration.read"))]
IntegrationManager = Annotated[CurrentUserContext, Depends(require_action("integration.manage"))]
MemberReader = Annotated[CurrentUserContext, Depends(require_action("member.read"))]
MemberManager = Annotated[CurrentUserContext, Depends(require_action("member.manage"))]
OrganizationManager = Annotated[CurrentUserContext, Depends(require_action("organization.manage"))]
