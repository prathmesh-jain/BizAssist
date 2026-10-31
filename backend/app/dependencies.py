import logging
import uuid
from typing import Annotated

import firebase_admin
from firebase_admin import auth, credentials
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.authz import can
from app.config import get_settings
from app.db.base import get_db_session
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


async def _resolve_user(session, decoded: dict):
    """Map a verified Firebase identity to an application user, provisioning on first login."""
    firebase_uid = decoded["uid"]
    email = decoded["email"]
    full_name = decoded.get("name") or "User"

    identity = await UserRepository.get_identity_by_provider(session, "firebase", firebase_uid)
    if identity:
        user = await UserRepository.get_by_id(session, identity.user_id)
        if not user:
            logger.error("Identity found for %s but user %s is missing", firebase_uid, identity.user_id)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User record not found")
        return user

    existing_user = await UserRepository.get_by_email(session, email)
    if existing_user:
        # Linking a new identity to an existing account by email is only safe when the
        # provider has verified that the caller owns the address.
        if not decoded.get("email_verified"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Verify your email address to sign in to this existing account.",
            )
        await UserRepository.create_identity(session, existing_user.id, "firebase", firebase_uid)
        return existing_user

    user = await UserRepository.create(session, email, full_name)
    await UserRepository.create_identity(session, user.id, "firebase", firebase_uid)
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

    if await UserRepository.list_memberships(session, user.id):
        # Memberships exist but all are suspended/invited or their orgs are inactive.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You have no active organization membership.",
        )

    # First login (or never had one): give the user a personal workspace they own.
    organization = await UserRepository.create_organization(
        session, f"{user.full_name or 'User'}'s Workspace", _workspace_slug(user.email)
    )
    member = await UserRepository.create_organization_member(session, organization.id, user.id, role="owner")
    return member, organization


async def get_authenticated_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session = Depends(get_db_session),
) -> AuthenticatedUser:
    """Authenticate the caller only (no organization context).

    Used by endpoints that must work before an organization is chosen, such as
    accepting an invitation.
    """
    decoded = _verify_firebase_token(credentials.credentials)
    user = await _resolve_user(session, decoded)
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled.")

    if not await UserRepository.get_ai_settings(session, user.id):
        await UserRepository.create_ai_settings(session, user.id)

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
    session = Depends(get_db_session),
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
