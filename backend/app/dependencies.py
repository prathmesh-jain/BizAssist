import logging
from typing import Annotated

import firebase_admin
from firebase_admin import auth, credentials
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.database import identities_col, users_col
from app.models.user import UserInDB

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

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> UserInDB:
    token = credentials.credentials

    try:
        _init_firebase_admin()
        decoded = auth.verify_id_token(token)

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
        identity = await identities_col().find_one(
            {
                "provider": "firebase",
                "provider_user_id": firebase_uid,
            }
        )

        if identity:
            user_doc = await users_col().find_one({"_id": identity["user_id"]})
            if not user_doc:
                logger.error(
                    "Identity found for %s but user %s is missing",
                    firebase_uid,
                    identity["user_id"],
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User record not found",
                )
            return UserInDB(**user_doc)

        # 2. Find or create user by email
        user_doc = await users_col().find_one({"email": email})

        if not user_doc:
            from datetime import datetime

            new_user = {
                "email": email,
                "full_name": full_name,
                "created_at": datetime.utcnow(),
                "is_active": True,
            }
            result = await users_col().insert_one(new_user)
            user_id = result.inserted_id
            user_doc = await users_col().find_one({"_id": user_id})
        else:
            user_id = user_doc["_id"]

        # 3. Link identity
        from datetime import datetime

        await identities_col().insert_one(
            {
                "user_id": user_id,
                "provider": "firebase",
                "provider_user_id": firebase_uid,
                "created_at": datetime.utcnow(),
            }
        )

        return UserInDB(**user_doc)

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error("Token verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

CurrentUser = Annotated[UserInDB, Depends(get_current_user)]
