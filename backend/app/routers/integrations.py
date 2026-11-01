import logging
from fastapi import APIRouter, Depends, HTTPException
from app.authz import can
from app.dependencies import ChatUser, IntegrationManager, IntegrationReader
from app.repositories import ChatRepository, OAuthStateRepository
from app.services import google_calendar_service as calendar_service
from app.services.google_oauth import hash_state
from app.db.base import get_db_session

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
async def google_sheets_status(user: IntegrationReader, session = Depends(get_db_session, scope="function")):
    """
    Check whether the current user's organization has Google Sheets connected.
    """
    try:
        connected = await is_connected(user.user.id, user.organization.id, session)
        spreadsheet_id = await get_default_spreadsheet_id(user.user.id, user.organization.id, session) if connected else None
        return {"connected": connected, "spreadsheet_id": spreadsheet_id}
    except Exception as e:
        logger.warning(f"Error checking Sheets status for org {user.organization.id}: {e}")
        return {"connected": False}


@router.post("/google-sheets/connect")
async def google_sheets_connect(user: IntegrationManager, body: dict = {}, session = Depends(get_db_session, scope="function")):
    """
    Create a Google OAuth authorization URL for Sheets.
    The frontend should open this URL in a popup.
    """
    try:
        chat_id = body.get("chat_id")
        if chat_id and not await ChatRepository.get_by_id(session, chat_id, user.organization.id, user.user.id):
            raise HTTPException(status_code=404, detail="Chat not found")
        result = await create_oauth_authorization_url(
            user_id=user.user.id,
            organization_id=user.organization.id,
            session=session,
            chat_id=chat_id,
        )
        logger.info(f"Initiated Google Sheets OAuth for org {user.organization.id}")
        return {"auth_url": result["auth_url"]}

    except HTTPException:
        raise
    except GoogleOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to initiate Google Sheets connection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/google-sheets/callback")
async def google_sheets_callback(user: IntegrationManager, body: dict, session = Depends(get_db_session, scope="function")):
    """Handle OAuth callback by exchanging `code` and persisting tokens."""
    code = (body.get("code") or "").strip()
    state = (body.get("state") or "").strip()
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth code/state")

    try:
        result = await handle_oauth_callback(
            user_id=user.user.id,
            organization_id=user.organization.id,
            session=session,
            code=code,
            state=state,
        )
        return result
    except GoogleOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------- Google Calendar (per member: each user connects their own calendar) ----------

@router.get("/google-calendar/status")
async def google_calendar_status(user: ChatUser, session = Depends(get_db_session, scope="function")):
    return await calendar_service.connection_status(session, user_id=user.user.id, organization_id=user.organization.id)


@router.post("/google-calendar/connect")
async def google_calendar_connect(user: ChatUser, session = Depends(get_db_session, scope="function")):
    try:
        auth_url = await calendar_service.create_authorization_url(
            session, user_id=user.user.id, organization_id=user.organization.id
        )
    except GoogleOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"auth_url": auth_url}


@router.delete("/google-calendar")
async def google_calendar_disconnect(user: ChatUser, session = Depends(get_db_session, scope="function")):
    removed = await calendar_service.disconnect(session, user_id=user.user.id, organization_id=user.organization.id)
    return {"ok": True, "removed": removed}


@router.post("/google/callback")
async def google_oauth_callback(user: ChatUser, body: dict, session = Depends(get_db_session, scope="function")):
    """One OAuth redirect for every Google integration: route by the integration that issued the state."""
    code = (body.get("code") or "").strip()
    state = (body.get("state") or "").strip()
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth code/state")
    oauth_state = await OAuthStateRepository.get_valid_state(
        session, user.user.id, user.organization.id, hash_state(state)
    )
    if oauth_state is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    try:
        if oauth_state.integration == "google_calendar":
            result = await calendar_service.handle_oauth_callback(
                session, user_id=user.user.id, organization_id=user.organization.id, code=code, state=state
            )
            return {"integration": "google_calendar", **result}
        if not can(user.role, "integration.manage"):
            raise HTTPException(status_code=403, detail=f"Your role ({user.role}) does not allow this action.")
        result = await handle_oauth_callback(
            user_id=user.user.id, organization_id=user.organization.id, session=session, code=code, state=state
        )
        return {"integration": "google_sheets", **result}
    except GoogleOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
