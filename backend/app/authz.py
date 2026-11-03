"""Authorization rules: organization roles and what each role may do.

Authentication (who you are) lives in app.dependencies; this module only answers
"may this member do X in this organization". Keep business rules here rather
than scattered through routers or LLM prompts.
"""
from typing import Literal

Role = Literal["viewer", "member", "admin", "owner"]

ROLE_RANK: dict[str, int] = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}

# Minimum role for each organization-level action.
#  viewer  - chat with the assistant and read shared resources
#  member  - also change shared business data (documents, spreadsheet contents)
#  admin   - also manage integrations and other members' resources
#  owner   - everything (organization lifecycle, ownership transfer)
ACTION_MIN_ROLE: dict[str, Role] = {
    "chat.use": "viewer",
    "document.read": "viewer",
    "document.upload": "member",
    "document.delete_own": "member",
    "document.delete_any": "admin",
    "integration.read": "viewer",
    "integration.use_write": "member",
    "integration.manage": "admin",
    "member.read": "viewer",
    "member.manage": "admin",
    "organization.manage": "admin",
    "business.read": "viewer",
    "business.manage": "admin",
}


class AuthorizationError(PermissionError):
    """Raised when a member's role does not allow an action."""


def has_role(role: str | None, minimum: str) -> bool:
    return ROLE_RANK.get(role or "", -1) >= ROLE_RANK[minimum]


def can(role: str | None, action: str) -> bool:
    return has_role(role, ACTION_MIN_ROLE[action])


def ensure_can(role: str | None, action: str) -> None:
    if not can(role, action):
        raise AuthorizationError(
            f"Your role ({role or 'none'}) does not allow this action; "
            f"requires {ACTION_MIN_ROLE[action]} or higher."
        )


def can_manage_member(actor_role: str | None, target_role: str) -> bool:
    """Owners manage everyone; others only manage members ranked below themselves."""
    if actor_role == "owner":
        return True
    return ROLE_RANK.get(actor_role or "", -1) > ROLE_RANK[target_role]


def can_assign_role(actor_role: str | None, role: str) -> bool:
    """Owners grant any role; others only roles ranked below their own (admins can't mint admins)."""
    if actor_role == "owner":
        return True
    return ROLE_RANK.get(actor_role or "", -1) > ROLE_RANK[role]
