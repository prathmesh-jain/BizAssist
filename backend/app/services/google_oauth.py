"""Google OAuth plumbing shared by the Google integrations (Sheets, Calendar).

Tokens are stored encrypted (Fernet) on OAuthConnection rows; only a hash of each
OAuth state is persisted. Integrations differ in scopes and in who owns the
connection: Sheets is shared by the organization, Calendar belongs to one user.
"""
import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import OAuthConnection
from app.repositories import OAuthConnectionRepository, OAuthStateRepository

settings = get_settings()

GOOGLE_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleOAuthError(RuntimeError):
    pass


def fernet() -> Fernet:
    if not settings.google_oauth_token_encryption_key:
        raise GoogleOAuthError(
            "GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY is not configured. "
            "Set it to a Fernet key (32 url-safe base64-encoded bytes)."
        )
    return Fernet(settings.google_oauth_token_encryption_key)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_state(state: str) -> str:
    # Store only a hash of the OAuth state to reduce risk if DB is leaked.
    digest = hmac.new(b"BizAssist", state.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8")


async def create_authorization_url(
    session: AsyncSession,
    *,
    user_id: str,
    organization_id: str,
    integration: str,
    scopes: list[str],
    chat_id: str | None = None,
) -> str:
    """Persist a one-time state for `integration` and return Google's consent URL."""
    if not settings.google_oauth_client_id or not settings.google_oauth_redirect_uri:
        raise GoogleOAuthError("Google OAuth client configuration is missing in .env")
    state = secrets.token_urlsafe(32)
    await OAuthStateRepository.create(
        session,
        user_id=user_id,
        state_hash=hash_state(state),
        chat_id=chat_id,
        organization_id=organization_id,
        integration=integration,
    )
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return str(httpx.URL(GOOGLE_OAUTH_AUTH_URL).copy_merge_params(params))


async def exchange_code_for_token(code: str) -> dict:
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise GoogleOAuthError("Google OAuth client configuration is missing in .env")
    data = {
        "code": code,
        "client_id": settings.google_oauth_client_id,
        "client_secret": settings.google_oauth_client_secret,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(GOOGLE_OAUTH_TOKEN_URL, data=data)
        if resp.status_code != 200:
            raise GoogleOAuthError(f"Token exchange failed: {resp.status_code} {resp.text}")
        return resp.json()


async def refresh_access_token(refresh_token: str) -> dict:
    data = {
        "client_id": settings.google_oauth_client_id,
        "client_secret": settings.google_oauth_client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(GOOGLE_OAUTH_TOKEN_URL, data=data)
        if resp.status_code != 200:
            raise GoogleOAuthError(f"Token refresh failed: {resp.status_code} {resp.text}")
        return resp.json()


def encrypt_payload(payload: dict) -> str:
    return fernet().encrypt(json.dumps(payload).encode("utf-8")).decode("utf-8")


def token_fields(token_payload: dict) -> dict:
    """Columns for OAuthConnectionRepository from a token endpoint response."""
    if not token_payload.get("access_token"):
        raise GoogleOAuthError("OAuth callback did not return an access_token")
    refresh = token_payload.get("refresh_token")
    expires_in = int(token_payload.get("expires_in") or 0)
    return {
        "access_token_encrypted": encrypt_payload(token_payload),
        "refresh_token_encrypted": fernet().encrypt(refresh.encode("utf-8")).decode("utf-8") if refresh else None,
        "token_expires_at": utcnow() + timedelta(seconds=max(expires_in - 60, 0)),  # 60s buffer
    }


async def valid_access_token(session: AsyncSession, connection: OAuthConnection, *, reconnect_hint: str) -> str:
    """Access token for a connection, refreshing (and persisting) it when expired."""
    payload = json.loads(fernet().decrypt(connection.access_token_encrypted.encode("utf-8")).decode("utf-8"))
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if access_token and connection.token_expires_at and connection.token_expires_at > utcnow():
        return access_token
    if not refresh_token:
        raise GoogleOAuthError(f"Access token expired and no refresh token is available. {reconnect_hint}")

    refreshed = await refresh_access_token(refresh_token)
    if not refreshed.get("access_token"):
        raise GoogleOAuthError("Refresh did not return an access_token")
    payload.update(refreshed)
    payload["refresh_token"] = refresh_token  # Google omits it on refresh
    expires_in = int(refreshed.get("expires_in") or 0)
    await OAuthConnectionRepository.update_tokens(
        session, connection.id, encrypt_payload(payload), utcnow() + timedelta(seconds=max(expires_in - 60, 0)),
    )
    return payload["access_token"]
