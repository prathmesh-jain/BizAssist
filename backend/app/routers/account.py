from fastapi import APIRouter, Depends

from app.authz import ACTION_MIN_ROLE, can
from app.db.base import get_db_session
from app.dependencies import CurrentUser
from app.repositories import UserRepository

router = APIRouter(prefix="/api", tags=["account"])


@router.get("/me")
async def get_me(user: CurrentUser, session = Depends(get_db_session, scope="function")):
    """Current user, the organization this request resolved to, and all memberships.

    Clients switch organizations by sending X-Organization-Id with one of the
    returned organization ids.
    """
    memberships = await UserRepository.list_memberships(session, user.user.id)
    return {
        "user": {
            "id": user.user.id,
            "email": user.user.email,
            "full_name": user.user.full_name,
        },
        "organization": {
            "id": user.organization.id,
            "name": user.organization.name,
            "slug": user.organization.slug,
        },
        "role": user.role,
        "permissions": sorted(action for action in ACTION_MIN_ROLE if can(user.role, action)),
        "memberships": [
            {
                "organization_id": org.id,
                "organization_name": org.name,
                "role": member.role,
                "status": member.status,
                "organization_active": org.is_active,
            }
            for member, org in memberships
        ],
    }
