"""Data access for long-term memories (the source of truth; search lives in services/memory_index.py).

Every query is scoped to one organization, and personal memories are only ever returned
to their owner: `_visible_to` is the single place that rule lives.
"""
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.memory import Memory
from app.db.models.user import User

def _visible_to(organization_id: str, user_id: str):
    return and_(
        Memory.organization_id == organization_id,
        or_(Memory.scope == "shared", and_(Memory.scope == "personal", Memory.user_id == user_id)),
    )


class MemoryRepository:
    @staticmethod
    async def create(session: AsyncSession, **fields) -> Memory:
        memory = Memory(**fields)
        session.add(memory)
        await session.flush()
        return memory

    @staticmethod
    async def get_visible(session: AsyncSession, organization_id: str, user_id: str, memory_id: str) -> Memory | None:
        result = await session.execute(
            select(Memory).where(Memory.id == memory_id, _visible_to(organization_id, user_id))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_visible(
        session: AsyncSession,
        organization_id: str,
        user_id: str,
        *,
        scope: str | None = None,
        kinds: Iterable[str] | None = None,
        exclude_kinds: Iterable[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[tuple[Memory, str | None]], int]:
        """Active memories this user may see, newest first (pinned on top), with the creator's name."""
        conditions = [_visible_to(organization_id, user_id), Memory.status == "active"]
        if scope:
            conditions.append(Memory.scope == scope)
        if kinds:
            conditions.append(Memory.kind.in_(list(kinds)))
        if exclude_kinds:
            conditions.append(Memory.kind.not_in(list(exclude_kinds)))
        total = await session.scalar(select(func.count()).select_from(Memory).where(*conditions))
        stmt = (
            select(Memory, func.coalesce(User.full_name, User.email))
            .outerjoin(User, User.id == Memory.created_by_user_id)
            .where(*conditions)
            .order_by(Memory.pinned.desc(), Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await session.execute(stmt)).all()
        return [(row[0], row[1]) for row in rows], int(total or 0)

    @staticmethod
    async def get_many_visible(
        session: AsyncSession, organization_id: str, user_id: str, memory_ids: Sequence[str]
    ) -> list[tuple[Memory, str | None]]:
        """Active, visible memories for these ids, in the given order (e.g. search ranking)."""
        if not memory_ids:
            return []
        stmt = (
            select(Memory, func.coalesce(User.full_name, User.email))
            .outerjoin(User, User.id == Memory.created_by_user_id)
            .where(Memory.id.in_(list(memory_ids)), _visible_to(organization_id, user_id), Memory.status == "active")
        )
        found = {row[0].id: (row[0], row[1]) for row in (await session.execute(stmt)).all()}
        return [found[i] for i in memory_ids if i in found]

    @staticmethod
    async def core(session: AsyncSession, organization_id: str, user_id: str, *, limit: int = 12) -> list[Memory]:
        """Memories worth having in every conversation: pinned first, then the most recently updated."""
        stmt = (
            select(Memory)
            .where(_visible_to(organization_id, user_id), Memory.status == "active", Memory.kind != "activity")
            .order_by(Memory.pinned.desc(), Memory.updated_at.desc())
            .limit(limit)
        )
        return list((await session.execute(stmt)).scalars())

    @staticmethod
    async def recent_activity(
        session: AsyncSession, organization_id: str, user_id: str, *, days: int = 14, limit: int = 8
    ) -> list[tuple[Memory, str | None]]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(Memory, func.coalesce(User.full_name, User.email))
            .outerjoin(User, User.id == Memory.created_by_user_id)
            .where(
                _visible_to(organization_id, user_id),
                Memory.status == "active",
                Memory.kind == "activity",
                Memory.created_at >= since,
            )
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]

    @staticmethod
    async def find_active_by_topic(
        session: AsyncSession, organization_id: str, *, scope: str, user_id: str | None, topic: str
    ) -> Memory | None:
        stmt = select(Memory).where(
            Memory.organization_id == organization_id,
            Memory.scope == scope,
            Memory.status == "active",
            Memory.topic == topic,
        )
        stmt = stmt.where(Memory.user_id == user_id) if scope == "personal" else stmt.where(Memory.user_id.is_(None))
        return (await session.execute(stmt.order_by(Memory.updated_at.desc()).limit(1))).scalar_one_or_none()

    @staticmethod
    async def find_active_duplicate(
        session: AsyncSession, organization_id: str, *, scope: str, user_id: str | None, content: str
    ) -> Memory | None:
        stmt = select(Memory).where(
            Memory.organization_id == organization_id,
            Memory.scope == scope,
            Memory.status == "active",
            func.lower(func.trim(Memory.content)) == content.strip().lower(),
        )
        stmt = stmt.where(Memory.user_id == user_id) if scope == "personal" else stmt.where(Memory.user_id.is_(None))
        return (await session.execute(stmt.limit(1))).scalar_one_or_none()

    @staticmethod
    async def get_by_id(session: AsyncSession, organization_id: str, memory_id: str) -> Memory | None:
        result = await session.execute(
            select(Memory).where(Memory.id == memory_id, Memory.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def mark_used(session: AsyncSession, memory_ids: Sequence[str]) -> None:
        if not memory_ids:
            return
        await session.execute(
            update(Memory)
            .where(Memory.id.in_(list(memory_ids)))
            .values(use_count=Memory.use_count + 1, last_used_at=datetime.now(timezone.utc))
            .execution_options(synchronize_session=False)
        )

    @staticmethod
    async def delete(session: AsyncSession, memory: Memory) -> None:
        await session.delete(memory)
        await session.flush()

    @staticmethod
    async def delete_personal_for_member(session: AsyncSession, organization_id: str, user_id: str) -> int:
        """When someone leaves or is removed: their personal memories in that organization go too."""
        # Rows that were superseded point at each other; clear links first so deletes don't trip FKs.
        await session.execute(
            update(Memory)
            .where(Memory.organization_id == organization_id, Memory.scope == "personal", Memory.user_id == user_id)
            .values(supersedes_id=None)
            .execution_options(synchronize_session=False)
        )
        result = await session.execute(
            delete(Memory).where(
                Memory.organization_id == organization_id, Memory.scope == "personal", Memory.user_id == user_id
            )
        )
        return result.rowcount or 0
