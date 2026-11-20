"""Long-term memory API: list, search, add, edit, pin, delete, undo, and the on/off switch."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.db.base import get_db_session
from app.dependencies import ChatUser
from app.repositories.memory_repository import MemoryRepository
from app.services import memory_service
from app.services.memory_service import MemoryActor, MemoryChangeError, can_write_shared, serialize

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _actor(user) -> MemoryActor:
    return MemoryActor(user.organization.id, user.user.id, user.role)


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=memory_service.MAX_CONTENT_CHARS)
    kind: Literal["fact", "preference", "decision", "contact"] = "fact"
    scope: Literal["shared", "personal"] = "shared"
    topic: str | None = None


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=memory_service.MAX_CONTENT_CHARS)
    kind: Literal["fact", "preference", "decision", "contact"] | None = None
    pinned: bool | None = None


class MemorySettings(BaseModel):
    enabled: bool


# Fixed paths first, so "settings" isn't taken for a memory id.
@router.get("/settings")
async def get_memory_settings(user: ChatUser, session = Depends(get_db_session, scope="function")):
    return {"enabled": await memory_service.is_memory_enabled(session, user.user.id)}


@router.patch("/settings")
async def patch_memory_settings(body: MemorySettings, user: ChatUser, session = Depends(get_db_session, scope="function")):
    try:
        return {"enabled": await memory_service.set_memory_enabled(session, user.user.id, body.enabled)}
    except MemoryChangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
async def list_memories(
    user: ChatUser,
    scope: Literal["shared", "personal"] | None = None,
    kind: Literal["fact", "preference", "decision", "contact", "activity"] | None = None,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session = Depends(get_db_session, scope="function"),
):
    actor = _actor(user)
    if q and q.strip():
        # Same hybrid search the assistant uses: meaning + keywords with an embedding key, keywords without.
        matches = await memory_service.find_relevant(
            session, actor, q, limit=100, scope=scope,
            kinds=(kind,) if kind else None, exclude_kinds=None if kind else ("activity",),
        )
        rows, total = matches[offset:offset + limit], len(matches)
    else:
        rows, total = await MemoryRepository.list_visible(
            session, actor.organization_id, actor.user_id,
            scope=scope, kinds=[kind] if kind else None,
            exclude_kinds=None if kind else ["activity"],
            limit=limit, offset=offset,
        )
    return {
        "memories": [serialize(m, actor, name) for m, name in rows],
        "total": total,
        "enabled": await memory_service.is_memory_enabled(session, actor.user_id),
        "can_write_shared": can_write_shared(actor.role),
        "vector_search": bool(await memory_service.embedding_key(session, actor.user_id)),
    }


@router.post("")
async def create_memory(body: MemoryCreate, user: ChatUser, session = Depends(get_db_session, scope="function")):
    actor = _actor(user)
    if body.scope == "shared" and body.kind != "preference" and not can_write_shared(actor.role):
        raise HTTPException(status_code=403, detail="Viewers can only save personal memories.")
    try:
        memory, action = await memory_service.remember(
            session, actor, content=body.content, kind=body.kind, scope=body.scope, topic=body.topic, source="manual",
        )
    except MemoryChangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"memory": serialize(memory, actor, user.user.full_name or user.user.email), "action": action}


@router.patch("/{memory_id}")
async def update_memory(memory_id: str, body: MemoryUpdate, user: ChatUser, session = Depends(get_db_session, scope="function")):
    actor = _actor(user)
    try:
        memory = await memory_service.update_memory(
            session, actor, memory_id, content=body.content, kind=body.kind, pinned=body.pinned,
        )
    except MemoryChangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # A text edit creates a new version (with a new id) that replaces this one.
    return {"memory": serialize(memory, actor), "replaced_id": memory_id if memory.id != memory_id else None}


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, user: ChatUser, session = Depends(get_db_session, scope="function")):
    try:
        await memory_service.forget(session, _actor(user), memory_id)
    except MemoryChangeError as exc:
        raise HTTPException(status_code=404 if "no longer exists" in str(exc) else 403, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/{memory_id}/undo")
async def undo_memory(memory_id: str, user: ChatUser, session = Depends(get_db_session, scope="function")):
    """Undo an automatic or chat save: remove it and restore whatever it replaced."""
    actor = _actor(user)
    try:
        restored = await memory_service.undo(session, actor, memory_id)
    except MemoryChangeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"ok": True, "restored": serialize(restored, actor) if restored else None}
