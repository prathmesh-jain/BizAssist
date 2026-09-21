import logging
import uuid
from typing import Annotated

import firebase_admin
from firebase_admin import auth, credentials
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.db.base import get_db_session
from app.models.user import UserInDB, Organization, CurrentUserContext
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


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session = Depends(get_db_session),
) -> CurrentUserContext:
    """Authenticate Firebase token and return user with organization context."""
    token = credentials.credentials

    try:
        _init_firebase_admin()
        decoded = auth.verify_id_token(token, clock_skew_seconds=5)

        firebase_uid = decoded.get("uid")
        if not firebase_uid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )

        email = decoded.get("email")
        full_name = decoded.get("name") or "User"

        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email address required",
            )

        # 1. Check if identity exists
        identity = await UserRepository.get_identity_by_provider(
            session, "firebase", firebase_uid
        )

        if identity:
            # Existing user - get user and organization
            user = await UserRepository.get_by_id(session, identity.user_id)
            if not user:
                logger.error(
                    "Identity found for %s but user %s is missing",
                    firebase_uid,
                    identity.user_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User record not found",
                )

            organization = await UserRepository.get_user_organization(session, user.id)
            if not organization:
                # This shouldn't happen, but create a default org if missing
                slug = f"{user.email.split('@')[0]}-workspace"
                organization = await UserRepository.create_organization(
                    session, f"{full_name}'s Workspace", slug
                )
                await UserRepository.create_organization_member(
                    session, organization.id, user.id, role="owner"
                )

            return CurrentUserContext(
                user=UserInDB(
                    id=user.id,
                    email=user.email,
                    full_name=user.full_name,
                    created_at=user.created_at,
                    is_active=user.is_active,
                ),
                organization=Organization(
                    id=organization.id,
                    name=organization.name,
                    slug=organization.slug,
                    is_active=organization.is_active,
                    created_at=organization.created_at,
                    updated_at=organization.updated_at,
                ),
                role="owner",  # For now, assume owner for single-org users
            )

        # 2. First-time login - create user + org + membership + AI settings atomically
        # Check if user exists by email (edge case)
        existing_user = await UserRepository.get_by_email(session, email)
        if existing_user:
            # Link identity to existing user
            await UserRepository.create_identity(
                session, existing_user.id, "firebase", firebase_uid
            )
            user = existing_user
        else:
            # Create new user
            user = await UserRepository.create(session, email, full_name)
            # Link identity
            await UserRepository.create_identity(
                session, user.id, "firebase", firebase_uid
            )

        # Create default organization
        slug = f"{email.split('@')[0]}-workspace"
        organization = await UserRepository.create_organization(
            session, f"{full_name}'s Workspace", slug
        )

        # Create owner membership
        await UserRepository.create_organization_member(
            session, organization.id, user.id, role="owner"
        )

        # Create default AI settings
        await UserRepository.create_ai_settings(session, user.id)

        return CurrentUserContext(
            user=UserInDB(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                created_at=user.created_at,
                is_active=user.is_active,
            ),
            organization=Organization(
                id=organization.id,
                name=organization.name,
                slug=organization.slug,
                is_active=organization.is_active,
                created_at=organization.created_at,
                updated_at=organization.updated_at,
            ),
            role="owner",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Token verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


CurrentUser = Annotated[CurrentUserContext, Depends(get_current_user)]
