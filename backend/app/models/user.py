from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class User(BaseModel):
    id: Optional[str] = None
    email: EmailStr
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
    email: EmailStr
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
