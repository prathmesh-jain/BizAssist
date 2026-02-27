import logging
from fastapi import APIRouter, HTTPException
from app.dependencies import CurrentUser

from app.services.google_sheets_service import (
    GoogleOAuthError,
    create_oauth_authorization_url,
    get_default_spreadsheet_id,
    handle_oauth_callback,
    is_connected,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/integrations", tags=["integrations"])


@router.get("/google-sheets/status")
async def google_sheets_status(user: CurrentUser):
    """
    Check whether the current user has Google Sheets connected.
    """
    try:
        connected = await is_connected(user.id)
        spreadsheet_id = await get_default_spreadsheet_id(user.id) if connected else None
        return {"connected": connected, "spreadsheet_id": spreadsheet_id}
    except Exception as e:
        logger.warning(f"Error checking Sheets status for {user.id}: {e}")
        return {"connected": False}


@router.post("/google-sheets/connect")
async def google_sheets_connect(user: CurrentUser, body: dict = {}):
    """
    Create a Google OAuth authorization URL for Sheets.
    The frontend should open this URL in a popup.
    """
    try:
        chat_id = body.get("chat_id")
        result = await create_oauth_authorization_url(user_id=user.id, chat_id=chat_id)
        logger.info(f"Initiated Google Sheets OAuth for user {user.id}")
        return {"auth_url": result["auth_url"]}

    except HTTPException:
        raise
    except GoogleOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to initiate Google Sheets connection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/google-sheets/callback")
async def google_sheets_callback(user: CurrentUser, body: dict):
    """Handle OAuth callback by exchanging `code` and persisting tokens."""
    code = (body.get("code") or "").strip()
    state = (body.get("state") or "").strip()
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth code/state")

    try:
        result = await handle_oauth_callback(user_id=user.id, code=code, state=state)
        return result
    except GoogleOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
