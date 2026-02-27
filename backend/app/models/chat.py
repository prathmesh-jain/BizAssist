from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ChatCreate(BaseModel):
    title: Optional[str] = "New Chat"


class ChatInDB(BaseModel):
    id: Optional[str] = None
    user_id: str
    title: str = "New Chat"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_deleted: bool = False


class ChatPublic(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
