import base64
import hashlib
import hmac
import json
import logging
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from cryptography.fernet import Fernet
from bson import ObjectId

from app.config import get_settings
from app.database import oauth_states_col, oauth_tokens_col, users_col

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


async def _ensure_sheet_row_capacity(*, user_id: str, spreadsheet_id: str, sheet_title: str, min_rows: int) -> None:
    meta = await get_spreadsheet_metadata(user_id=user_id, spreadsheet_id=spreadsheet_id)
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
    await _sheets_request(user_id, "POST", url, json_body=body)


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


async def create_oauth_authorization_url(user_id: str, chat_id: str | None = None) -> dict:
    """Create an authorization URL and persist OAuth state for later verification."""
    if not settings.google_oauth_client_id or not settings.google_oauth_redirect_uri:
        raise GoogleOAuthError("Google OAuth client configuration is missing in .env")

    state = secrets.token_urlsafe(32)
    state_hash = _hash_state(state)

    await oauth_states_col().insert_one({
        "user_id": user_id,
        "state_hash": state_hash,
        "chat_id": chat_id,
        "created_at": _utcnow(),
        "expires_at": _utcnow() + timedelta(minutes=15),
        "used": False,
    })

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


async def handle_oauth_callback(user_id: str, code: str, state: str) -> dict:
    """Validate OAuth state then exchange code and persist encrypted tokens."""
    state_hash = _hash_state(state)

    state_doc = await oauth_states_col().find_one({
        "user_id": user_id,
        "state_hash": state_hash,
        "used": False,
        "expires_at": {"$gt": _utcnow()},
    })
    if not state_doc:
        raise GoogleOAuthError("Invalid or expired OAuth state")

    token_payload = await _exchange_code_for_token(code)

    # Mark state used (one-time)
    await oauth_states_col().update_one(
        {"_id": state_doc["_id"]},
        {"$set": {"used": True, "used_at": _utcnow()}},
    )

    access_token = token_payload.get("access_token")
    refresh_token = token_payload.get("refresh_token")
    expires_in = int(token_payload.get("expires_in") or 0)

    if not access_token:
        raise GoogleOAuthError("OAuth callback did not return an access_token")

    # Store full payload encrypted for forward compatibility.
    encrypted = _fernet().encrypt(json.dumps(token_payload).encode("utf-8")).decode("utf-8")

    expires_at = _utcnow() + timedelta(seconds=max(expires_in - 60, 0))  # 60s buffer

    # 1. First, persist the tokens
    await oauth_tokens_col().update_one(
        {"user_id": user_id, "provider": "google", "app": "sheets"},
        {
            "$set": {
                "user_id": user_id,
                "provider": "google",
                "app": "sheets",
                "encrypted_payload": encrypted,
                "has_refresh_token": bool(refresh_token),
                "expires_at": expires_at,
                "updated_at": _utcnow(),
                "created_at": state_doc.get("created_at", _utcnow()),
            }
        },
        upsert=True,
    )

    # 2. Ensure default spreadsheet exists (this calls create_spreadsheet)
    default_spreadsheet_id = await ensure_default_spreadsheet(user_id)

    # 3. Explicitly update the token doc WITH the spreadsheet_id to ensure persistence
    await oauth_tokens_col().update_one(
        {"user_id": user_id, "provider": "google", "app": "sheets"},
        {"$set": {"default_spreadsheet_id": default_spreadsheet_id}}
    )

    return {"connected": True, "spreadsheet_id": default_spreadsheet_id}


async def get_default_spreadsheet_id(user_id: str) -> str | None:
    # Prefer storing this on oauth_tokens because that document is guaranteed to exist
    # after OAuth callback (upsert). Users doc may not always be writable/visible depending
    # on how users are created.
    tok = await oauth_tokens_col().find_one(
        {"user_id": user_id, "provider": "google", "app": "sheets"},
        projection={"default_spreadsheet_id": 1},
    )
    if tok:
        v = (tok.get("default_spreadsheet_id") or "").strip()
        if v:
            return v

    # Fallback: users collection
    try:
        oid = ObjectId(user_id)
    except Exception:
        return None

    doc = await users_col().find_one({"_id": oid}, projection={"default_spreadsheet_id": 1})
    if not doc:
        return None
    v = (doc.get("default_spreadsheet_id") or "").strip()
    return v or None


async def set_default_spreadsheet_id(user_id: str, spreadsheet_id: str) -> None:
    # Always persist on oauth_tokens (reliable upsert target)
    await oauth_tokens_col().update_one(
        {"user_id": user_id, "provider": "google", "app": "sheets"},
        {"$set": {"default_spreadsheet_id": spreadsheet_id}},
        upsert=True,
    )

    # Best-effort persist on users as well (if the user doc exists)
    try:
        oid = ObjectId(user_id)
    except Exception:
        return

    await users_col().update_one(
        {"_id": oid},
        {"$set": {"default_spreadsheet_id": spreadsheet_id, "updated_at": _utcnow()}},
    )


async def ensure_default_spreadsheet(user_id: str) -> str:
    existing = await get_default_spreadsheet_id(user_id)
    if existing:
        try:
            await get_spreadsheet_metadata(user_id=user_id, spreadsheet_id=str(existing))
            return str(existing)
        except GoogleOAuthError as e:
            if "404" not in str(e) and "NOT_FOUND" not in str(e):
                raise

    created = await create_spreadsheet(user_id=user_id, title="BizAssist Expenses")
    spreadsheet_id = created.get("spreadsheetId")
    if not spreadsheet_id:
        raise GoogleOAuthError("Failed to create default spreadsheet")

    await set_default_spreadsheet_id(user_id, str(spreadsheet_id))
    return str(spreadsheet_id)


async def _get_token_doc(user_id: str) -> Optional[dict]:
    return await oauth_tokens_col().find_one({
        "user_id": user_id,
        "provider": "google",
        "app": "sheets",
    })


async def is_connected(user_id: str) -> bool:
    doc = await _get_token_doc(user_id)
    return bool(doc)


async def get_valid_access_token(user_id: str) -> str:
    """Return a valid access token; refresh automatically if expired."""
    doc = await _get_token_doc(user_id)
    if not doc:
        raise GoogleOAuthError("Google Sheets is not connected")

    payload_raw = _fernet().decrypt(doc["encrypted_payload"].encode("utf-8")).decode("utf-8")
    payload = json.loads(payload_raw)

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")

    expires_at = doc.get("expires_at")
    if isinstance(expires_at, datetime):
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

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

    await oauth_tokens_col().update_one(
        {"_id": doc["_id"]},
        {"$set": {"encrypted_payload": encrypted, "expires_at": new_expires_at, "updated_at": _utcnow()}},
    )

    return new_access


async def _sheets_request(user_id: str, method: str, url: str, *, params: dict | None = None, json_body: Any | None = None) -> dict:
    token = await get_valid_access_token(user_id)
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


async def create_spreadsheet(user_id: str, title: str) -> dict:
    url = "https://sheets.googleapis.com/v4/spreadsheets"
    body = {
        "properties": {"title": title},
    }
    return await _sheets_request(user_id, "POST", url, json_body=body)


async def get_spreadsheet_metadata(user_id: str, spreadsheet_id: str) -> dict:
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
    params = {"fields": "spreadsheetId,properties.title,sheets(properties.sheetId,properties.title,properties.gridProperties)"}
    return await _sheets_request(user_id, "GET", url, params=params)


async def get_spreadsheet_tabs_with_headers(
    *,
    user_id: str,
    spreadsheet_id: str,
    max_tabs: int = 20,
    header_range: str = "A1:Z1",
) -> dict:
    meta = await get_spreadsheet_metadata(user_id=user_id, spreadsheet_id=spreadsheet_id)
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


async def read_values(user_id: str, spreadsheet_id: str, range_a1: str) -> dict:
    encoded_range = urllib.parse.quote(range_a1, safe="!:'(),-._~")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{encoded_range}"
    return await _sheets_request(user_id, "GET", url)


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
    return await _sheets_request(user_id, "POST", url, params=params, json_body=body)


async def update_values(
    user_id: str,
    spreadsheet_id: str,
    range_a1: str,
    values: list[list[Any]],
    value_input_option: str = "USER_ENTERED",
) -> dict:
    encoded_range = urllib.parse.quote(range_a1, safe="!:'(),-._~")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{encoded_range}"
    params = {"valueInputOption": value_input_option}
    body = {"values": _normalize_values_2d(values)}
    return await _sheets_request(user_id, "PUT", url, params=params, json_body=body)


async def clear_values(user_id: str, spreadsheet_id: str, range_a1: str) -> dict:
    encoded_range = urllib.parse.quote(range_a1, safe="!:'(),-._~")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{encoded_range}:clear"
    return await _sheets_request(user_id, "POST", url)


async def _get_sheet_id_by_title(*, user_id: str, spreadsheet_id: str, sheet_title: str) -> int:
    meta = await get_spreadsheet_metadata(user_id=user_id, spreadsheet_id=spreadsheet_id)
    for s in meta.get("sheets", []) or []:
        props = (s.get("properties") or {}) if isinstance(s, dict) else {}
        if props.get("title") == sheet_title:
            sid = props.get("sheetId")
            if isinstance(sid, int):
                return sid
    raise GoogleOAuthError(f"Sheet tab '{sheet_title}' not found")


async def batch_update(
    *,
    user_id: str,
    spreadsheet_id: str,
    requests: list[dict[str, Any]],
    include_spreadsheet_in_response: bool = False,
    response_include_grid_data: bool = False,
) -> dict:
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate"
    body: dict[str, Any] = {
        "requests": requests,
        "includeSpreadsheetInResponse": include_spreadsheet_in_response,
        "responseIncludeGridData": response_include_grid_data,
    }
    return await _sheets_request(user_id, "POST", url, json_body=body)


async def create_sheet_tab(*, user_id: str, spreadsheet_id: str, title: str) -> dict:
    return await batch_update(
        user_id=user_id,
        spreadsheet_id=spreadsheet_id,
        requests=[{"addSheet": {"properties": {"title": title}}}],
    )


async def delete_sheet_tab(*, user_id: str, spreadsheet_id: str, sheet_title: str) -> dict:
    sheet_id = await _get_sheet_id_by_title(user_id=user_id, spreadsheet_id=spreadsheet_id, sheet_title=sheet_title)
    return await batch_update(
        user_id=user_id,
        spreadsheet_id=spreadsheet_id,
        requests=[{"deleteSheet": {"sheetId": sheet_id}}],
    )


async def rename_sheet_tab(*, user_id: str, spreadsheet_id: str, sheet_title: str, new_title: str) -> dict:
    sheet_id = await _get_sheet_id_by_title(user_id=user_id, spreadsheet_id=spreadsheet_id, sheet_title=sheet_title)
    return await batch_update(
        user_id=user_id,
        spreadsheet_id=spreadsheet_id,
        requests=[
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "title": new_title},
                    "fields": "title",
                }
            }
        ],
    )


async def resize_sheet_grid(
    *,
    user_id: str,
    spreadsheet_id: str,
    sheet_title: str,
    row_count: int | None = None,
    column_count: int | None = None,
) -> dict:
    sheet_id = await _get_sheet_id_by_title(user_id=user_id, spreadsheet_id=spreadsheet_id, sheet_title=sheet_title)

    grid_props: dict[str, Any] = {}
    fields: list[str] = []
    if row_count is not None:
        grid_props["rowCount"] = int(row_count)
        fields.append("gridProperties.rowCount")
    if column_count is not None:
        grid_props["columnCount"] = int(column_count)
        fields.append("gridProperties.columnCount")

    if not fields:
        raise GoogleOAuthError("resize_sheet_grid requires row_count and/or column_count")

    return await batch_update(
        user_id=user_id,
        spreadsheet_id=spreadsheet_id,
        requests=[
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "gridProperties": grid_props},
                    "fields": ",".join(fields),
                }
            }
        ],
    )


async def insert_dimension(
    *,
    user_id: str,
    spreadsheet_id: str,
    sheet_title: str,
    dimension: str,
    start_index: int,
    end_index: int,
    inherit_from_before: bool = False,
) -> dict:
    sheet_id = await _get_sheet_id_by_title(user_id=user_id, spreadsheet_id=spreadsheet_id, sheet_title=sheet_title)
    dim = (dimension or "").upper().strip()
    if dim not in {"ROWS", "COLUMNS"}:
        raise GoogleOAuthError("dimension must be 'ROWS' or 'COLUMNS'")

    return await batch_update(
        user_id=user_id,
        spreadsheet_id=spreadsheet_id,
        requests=[
            {
                "insertDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": dim,
                        "startIndex": int(start_index),
                        "endIndex": int(end_index),
                    },
                    "inheritFromBefore": bool(inherit_from_before),
                }
            }
        ],
    )


async def delete_dimension(
    *,
    user_id: str,
    spreadsheet_id: str,
    sheet_title: str,
    dimension: str,
    start_index: int,
    end_index: int,
) -> dict:
    sheet_id = await _get_sheet_id_by_title(user_id=user_id, spreadsheet_id=spreadsheet_id, sheet_title=sheet_title)
    dim = (dimension or "").upper().strip()
    if dim not in {"ROWS", "COLUMNS"}:
        raise GoogleOAuthError("dimension must be 'ROWS' or 'COLUMNS'")

    return await batch_update(
        user_id=user_id,
        spreadsheet_id=spreadsheet_id,
        requests=[
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": dim,
                        "startIndex": int(start_index),
                        "endIndex": int(end_index),
                    }
                }
            }
        ],
    )
