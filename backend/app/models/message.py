from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    content: str
    role: Literal["user", "assistant"] = "user"


class AttachmentPublic(BaseModel):
    id: str
    filename: str
    content_type: str
    size: int
    url: str


class MessageInDB(BaseModel):
    id: Optional[str] = None
    chat_id: str
    user_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    tool_calls: Optional[list[dict]] = None   # tracks which tools were used
    attachments: Optional[list[AttachmentPublic]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MessagePublic(BaseModel):
    id: str
    role: str
    content: str
    tool_calls: Optional[list[dict]] = None
    attachments: Optional[list[AttachmentPublic]] = None
    created_at: datetime
