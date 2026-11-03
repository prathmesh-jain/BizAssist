from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class User(BaseModel):
    id: Optional[str] = None
    # Plain str: this comes from the identity provider's verified token, not user input.
    # Re-validating with EmailStr rejected valid provider emails (e.g. reserved TLDs) and
    # turned every authenticated request into a 500.
    email: str
    full_name: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True


class Identity(BaseModel):
    id: Optional[str] = None
    user_id: str  # Reference to User.id
    provider: str  # e.g., "firebase"
    provider_user_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserInDB(User):
    pass


class UserPublic(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    created_at: datetime


class Organization(BaseModel):
    id: str
    name: str
    slug: str
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class AuthenticatedUser(BaseModel):
    """Authenticated caller before any organization is resolved."""
    user: UserInDB
    email_verified: bool = False


class CurrentUserContext(BaseModel):
    """Extended user context including organization information."""
    user: UserInDB
    organization: Organization
    role: str  # owner, admin, member, viewer
