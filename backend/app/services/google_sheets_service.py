import base64
import hashlib
import hmac
import json
import logging
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

import httpx
from cryptography.fernet import Fernet

from app.config import get_settings
from app.repositories import OAuthConnectionRepository, OAuthStateRepository

logger = logging.getLogger(__name__)
settings = get_settings()

GOOGLE_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Minimum scopes required for Sheets CRUD
GOOGLE_SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]


class GoogleOAuthError(RuntimeError):
    pass


def _parse_grid_limit_error(message: str) -> tuple[int, int] | None:
    # Example:
    # Range (Expenses!A1004:E1004) exceeds grid limits. Max rows: 1003, max columns: 26
    import re

    m = re.search(r"Max rows:\s*(\d+),\s*max columns:\s*(\d+)", message or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _extract_sheet_title_from_range(range_a1: str) -> str | None:
    # A1 range formats we use are typically: SheetName!A1:Z
    if not range_a1 or "!" not in range_a1:
        return None
    return range_a1.split("!", 1)[0].strip().strip("'") or None


async def _ensure_sheet_row_capacity(*, user_id: str, organization_id: str, session: AsyncSession, spreadsheet_id: str, sheet_title: str, min_rows: int) -> None:
    meta = await get_spreadsheet_metadata(user_id=user_id, organization_id=organization_id, session=session, spreadsheet_id=spreadsheet_id)
    target_sheet_id: int | None = None
    current_rows: int | None = None

    for s in meta.get("sheets", []) or []:
        props = (s.get("properties") or {})
        if props.get("title") == sheet_title:
            target_sheet_id = props.get("sheetId")
            grid = props.get("gridProperties") or {}
            current_rows = grid.get("rowCount")
            break

    if target_sheet_id is None:
        raise GoogleOAuthError(f"Sheet tab '{sheet_title}' not found")

    # If API didn't return rowCount, just request a reasonable size.
    new_rows = max(int(current_rows or 0), int(min_rows), 2000)
    if current_rows and new_rows <= int(current_rows):
        return

    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate"
    body = {
        "requests": [
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": target_sheet_id, "gridProperties": {"rowCount": new_rows}},
                    "fields": "gridProperties.rowCount",
                }
            }
        ]
    }
    await _sheets_request(user_id, organization_id, session, "POST", url, json_body=body)


def _fernet() -> Fernet:
    if not settings.google_oauth_token_encryption_key:
        raise GoogleOAuthError(
            "GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY is not configured. "
            "Set it to a Fernet key (32 url-safe base64-encoded bytes)."
        )
    return Fernet(settings.google_oauth_token_encryption_key)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_state(state: str) -> str:
    # Store only a hash of the OAuth state to reduce risk if DB is leaked.
    digest = hmac.new(b"BizAssist", state.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8")


async def create_oauth_authorization_url(
    user_id: str,
    organization_id: str,
    session: AsyncSession,
    chat_id: str | None = None,
) -> dict:
    """Create an authorization URL and persist OAuth state for later verification."""
    if not settings.google_oauth_client_id or not settings.google_oauth_redirect_uri:
        raise GoogleOAuthError("Google OAuth client configuration is missing in .env")

    state = secrets.token_urlsafe(32)
    state_hash = _hash_state(state)

    await OAuthStateRepository.create(
        session,
        user_id=user_id,
        state_hash=state_hash,
        chat_id=chat_id,
        organization_id=organization_id,
    )

    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SHEETS_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }

    # Caller returns this URL to frontend to open in popup.
    auth_url = httpx.URL(GOOGLE_OAUTH_AUTH_URL).copy_merge_params(params)
    return {"auth_url": str(auth_url), "state": state}


async def _exchange_code_for_token(code: str) -> dict:
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


async def _refresh_access_token(refresh_token: str) -> dict:
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


async def handle_oauth_callback(
    user_id: str,
    organization_id: str,
    session: AsyncSession,
    code: str,
    state: str,
) -> dict:
    """Validate OAuth state then exchange code and persist encrypted tokens."""
    state_hash = _hash_state(state)

    oauth_state = await OAuthStateRepository.get_valid_state(session, user_id, state_hash)
    if not oauth_state:
        raise GoogleOAuthError("Invalid or expired OAuth state")

    token_payload = await _exchange_code_for_token(code)

    # Mark state used (one-time)
    await OAuthStateRepository.mark_used(session, oauth_state.id)

    access_token = token_payload.get("access_token")
    refresh_token = token_payload.get("refresh_token")
    expires_in = int(token_payload.get("expires_in") or 0)

    if not access_token:
        raise GoogleOAuthError("OAuth callback did not return an access_token")

    # Store full payload encrypted for forward compatibility.
    encrypted = _fernet().encrypt(json.dumps(token_payload).encode("utf-8")).decode("utf-8")

    expires_at = _utcnow() + timedelta(seconds=max(expires_in - 60, 0))  # 60s buffer

    # Persist the connection
    await OAuthConnectionRepository.create_or_update(
        session,
        organization_id=organization_id,
        user_id=user_id,
        provider="google",
        access_token_encrypted=encrypted,
        refresh_token_encrypted=_fernet().encrypt(refresh_token.encode("utf-8")).decode("utf-8") if refresh_token else None,
        token_expires_at=expires_at,
        scopes={"scopes": GOOGLE_SHEETS_SCOPES},
        connection_metadata={"app": "sheets"},
    )

    # Ensure default spreadsheet exists
    default_spreadsheet_id = await ensure_default_spreadsheet(user_id, organization_id, session)

    # Update connection metadata with spreadsheet_id
    connection = await OAuthConnectionRepository.get_by_organization_and_provider(session, organization_id, "google")
    if connection and connection.connection_metadata:
        connection.connection_metadata["default_spreadsheet_id"] = default_spreadsheet_id

    return {"connected": True, "spreadsheet_id": default_spreadsheet_id}


async def get_default_spreadsheet_id(
    user_id: str,
    organization_id: str,
    session: AsyncSession,
) -> str | None:
    """Get the default spreadsheet ID from OAuth connection metadata."""
    connection = await OAuthConnectionRepository.get_by_organization_and_provider(session, organization_id, "google")
    if connection and connection.connection_metadata:
        return connection.connection_metadata.get("default_spreadsheet_id")
    return None


async def set_default_spreadsheet_id(
    user_id: str,
    organization_id: str,
    session: AsyncSession,
    spreadsheet_id: str,
) -> None:
    """Set the default spreadsheet ID in OAuth connection metadata."""
    connection = await OAuthConnectionRepository.get_by_organization_and_provider(session, organization_id, "google")
    if connection:
        if not connection.connection_metadata:
            connection.connection_metadata = {}
        connection.connection_metadata["default_spreadsheet_id"] = spreadsheet_id


async def ensure_default_spreadsheet(
    user_id: str,
    organization_id: str,
    session: AsyncSession,
) -> str:
    """Ensure a default spreadsheet exists for the organization."""
    existing = await get_default_spreadsheet_id(user_id, organization_id, session)
    if existing:
        try:
            await get_spreadsheet_metadata(user_id=user_id, organization_id=organization_id, session=session, spreadsheet_id=str(existing))
            return str(existing)
        except GoogleOAuthError as e:
            if "404" not in str(e) and "NOT_FOUND" not in str(e):
                raise

    created = await create_spreadsheet(user_id=user_id, organization_id=organization_id, session=session, title="BizAssist Expenses")
    spreadsheet_id = created.get("spreadsheetId")
    if not spreadsheet_id:
        raise GoogleOAuthError("Failed to create default spreadsheet")

    await set_default_spreadsheet_id(user_id, organization_id, session, str(spreadsheet_id))
    return str(spreadsheet_id)


async def is_connected(
    user_id: str,
    organization_id: str,
    session: AsyncSession,
) -> bool:
    """Check if Google Sheets is connected for the organization."""
    connection = await OAuthConnectionRepository.get_by_organization_and_provider(session, organization_id, "google")
    return bool(connection)


async def get_valid_access_token(
    user_id: str,
    organization_id: str,
    session: AsyncSession,
) -> str:
    """Return a valid access token; refresh automatically if expired."""
    connection = await OAuthConnectionRepository.get_by_organization_and_provider(session, organization_id, "google")
    if not connection:
        raise GoogleOAuthError("Google Sheets is not connected")

    payload_raw = _fernet().decrypt(connection.access_token_encrypted.encode("utf-8")).decode("utf-8")
    payload = json.loads(payload_raw)

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")

    expires_at = connection.token_expires_at
    if access_token and expires_at and expires_at > _utcnow():
        return access_token

    if not refresh_token:
        raise GoogleOAuthError("Access token expired and no refresh token is available. Reconnect Google Sheets.")

    refreshed = await _refresh_access_token(refresh_token)
    new_access = refreshed.get("access_token")
    expires_in = int(refreshed.get("expires_in") or 0)
    if not new_access:
        raise GoogleOAuthError("Refresh did not return an access_token")

    # Merge refreshed fields back into stored payload (keep refresh_token)
    payload.update(refreshed)
    payload["refresh_token"] = refresh_token

    encrypted = _fernet().encrypt(json.dumps(payload).encode("utf-8")).decode("utf-8")
    new_expires_at = _utcnow() + timedelta(seconds=max(expires_in - 60, 0))

    await OAuthConnectionRepository.update_tokens(
        session,
        connection.id,
        encrypted,
        new_expires_at,
    )

    return new_access


async def _sheets_request(
    user_id: str,
    organization_id: str,
    session: AsyncSession,
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json_body: Any | None = None,
) -> dict:
    token = await get_valid_access_token(user_id, organization_id, session)
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.request(method, url, headers=headers, params=params, json=json_body)
        if resp.status_code >= 400:
            # Attempt to auto-expand grid on common grid-limit failures for value updates.
            if resp.status_code == 400 and isinstance(resp.text, str) and "exceeds grid limits" in resp.text:
                try:
                    err = resp.json().get("error", {})
                    msg = err.get("message") or resp.text
                except Exception:
                    msg = resp.text

                limits = _parse_grid_limit_error(msg)
                if limits and isinstance(json_body, dict) and "/values/" in url:
                    max_rows, _max_cols = limits

                    # Derive spreadsheet_id from URL: .../spreadsheets/{id}/values/...
                    try:
                        parts = url.split("/spreadsheets/", 1)[1]
                        spreadsheet_id = parts.split("/", 1)[0]
                    except Exception:
                        spreadsheet_id = ""

                    # Derive sheet title from range (available in URL tail before :append or end)
                    # We can only reliably do this when caller supplied range_a1; append/update/clear always does.
                    # If we can't parse, just raise.
                    raise_hint = GoogleOAuthError(f"Google Sheets API error: {resp.status_code} {resp.text}")

                    # Best-effort: the URL contains the encoded range after /values/
                    try:
                        encoded_range = url.split("/values/", 1)[1]
                        encoded_range = encoded_range.split(":", 1)[0]
                        range_a1 = urllib.parse.unquote(encoded_range)
                    except Exception:
                        raise raise_hint

                    sheet_title = _extract_sheet_title_from_range(range_a1)
                    if not spreadsheet_id or not sheet_title:
                        raise raise_hint

                    await _ensure_sheet_row_capacity(
                        user_id=user_id,
                        organization_id=organization_id,
                        session=session,
                        spreadsheet_id=spreadsheet_id,
                        sheet_title=sheet_title,
                        min_rows=max_rows + 200,
                    )

                    # Retry once
                    resp2 = await client.request(method, url, headers=headers, params=params, json=json_body)
                    if resp2.status_code >= 400:
                        raise GoogleOAuthError(f"Google Sheets API error: {resp2.status_code} {resp2.text}")
                    return resp2.json()

            raise GoogleOAuthError(f"Google Sheets API error: {resp.status_code} {resp.text}")

        return resp.json()


async def create_spreadsheet(
    user_id: str,
    organization_id: str,
    session: AsyncSession,
    title: str,
) -> dict:
    url = "https://sheets.googleapis.com/v4/spreadsheets"
    body = {
        "properties": {"title": title},
    }
    return await _sheets_request(user_id, organization_id, session, "POST", url, json_body=body)


async def get_spreadsheet_metadata(
    user_id: str,
    organization_id: str,
    session: AsyncSession,
    spreadsheet_id: str,
) -> dict:
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
    params = {"fields": "spreadsheetId,properties.title,sheets(properties.sheetId,properties.title,properties.gridProperties)"}
    return await _sheets_request(user_id, organization_id, session, "GET", url, params=params)


async def get_spreadsheet_tabs_with_headers(
    *,
    user_id: str,
    organization_id: str,
    session: AsyncSession,
    spreadsheet_id: str,
    max_tabs: int = 20,
    header_range: str = "A1:Z1",
) -> dict:
    meta = await get_spreadsheet_metadata(user_id=user_id, organization_id=organization_id, session=session, spreadsheet_id=spreadsheet_id)
    tabs: list[str] = [
        (s.get("properties") or {}).get("title")
        for s in (meta.get("sheets") or [])
        if isinstance(s, dict)
    ]
    tabs = [t for t in tabs if isinstance(t, str) and t.strip()]
    tabs = tabs[: max(int(max_tabs or 0), 0) or 0] if max_tabs else tabs

    items: list[dict[str, Any]] = []
    for tab in tabs:
        headers: list[str] = []
        try:
            values_resp = await read_values(
                user_id=user_id,
                organization_id=organization_id,
                session=session,
                spreadsheet_id=spreadsheet_id,
                range_a1=f"{tab}!{header_range}",
            )
            values = (values_resp.get("values") or []) if isinstance(values_resp, dict) else []
            if values and isinstance(values, list) and values[0] and isinstance(values[0], list):
                headers = [str(h).strip() for h in values[0] if str(h).strip()]
        except Exception:
            headers = []

        items.append({"sheet": tab, "headers": headers})

    return {
        "ok": True,
        "spreadsheet_id": meta.get("spreadsheetId") or spreadsheet_id,
        "title": (meta.get("properties") or {}).get("title"),
        "items": items,
    }


async def read_values(
    user_id: str,
    organization_id: str,
    session: AsyncSession,
    spreadsheet_id: str,
    range_a1: str,
) -> dict:
    encoded_range = urllib.parse.quote(range_a1, safe="!:'(),-._~")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{encoded_range}"
    return await _sheets_request(user_id, organization_id, session, "GET", url)


def _normalize_values_2d(values: list[list[Any]]) -> list[list[Any]]:
    if not isinstance(values, list):
        return [[]]

    def norm_cell(v: Any) -> Any:
        if v is None:
            return ""
        if isinstance(v, (str, int, float, bool)):
            return v
        if isinstance(v, dict):
            if "formulaValue" in v and isinstance(v.get("formulaValue"), str):
                return v["formulaValue"]
            if "userEnteredValue" in v and isinstance(v.get("userEnteredValue"), str):
                return v["userEnteredValue"]
            if "stringValue" in v and isinstance(v.get("stringValue"), str):
                return v["stringValue"]
            if "numberValue" in v and isinstance(v.get("numberValue"), (int, float)):
                return v["numberValue"]
            if "boolValue" in v and isinstance(v.get("boolValue"), bool):
                return v["boolValue"]
            return str(v)
        return str(v)

    out: list[list[Any]] = []
    for row in values:
        if not isinstance(row, list):
            out.append([norm_cell(row)])
        else:
            out.append([norm_cell(c) for c in row])
    return out


async def append_values(
    user_id: str,
    organization_id: str,
    session: AsyncSession,
    spreadsheet_id: str,
    range_a1: str,
    values: list[list[Any]],
    value_input_option: str = "USER_ENTERED",
) -> dict:
    encoded_range = urllib.parse.quote(range_a1, safe="!:'(),-._~")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{encoded_range}:append"
    params = {
        "valueInputOption": value_input_option,
        "insertDataOption": "INSERT_ROWS",
    }
    body = {"values": _normalize_values_2d(values)}
    return await _sheets_request(user_id, organization_id, session, "POST", url, params=params, json_body=body)


async def update_values(
    user_id: str,
    organization_id: str,
    session: AsyncSession,
    spreadsheet_id: str,
    range_a1: str,
    values: list[list[Any]],
    value_input_option: str = "USER_ENTERED",
) -> dict:
    encoded_range = urllib.parse.quote(range_a1, safe="!:'(),-._~")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{encoded_range}"
    params = {"valueInputOption": value_input_option}
    body = {"values": _normalize_values_2d(values)}
    return await _sheets_request(user_id, organization_id, session, "POST", url, params=params, json_body=body)
