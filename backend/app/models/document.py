from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class DocumentInDB(BaseModel):
    id: Optional[str] = None
    user_id: str
    filename: str
    file_type: str
    chunk_count: int = 0
    chroma_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DocumentPublic(BaseModel):
    id: str
    filename: str
    file_type: str
    chunk_count: int
    created_at: datetime
