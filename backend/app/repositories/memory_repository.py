"""Data access for long-term memories.

Every query is scoped to one organization, and personal memories are only ever returned
to their owner: `_visible_to` is the single place that rule lives.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.memory import Memory
from app.db.models.user import User

# Words too common to help find a memory.
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "do", "does", "for", "from", "has", "have",
    "how", "i", "if", "in", "is", "it", "its", "me", "my", "of", "on", "or", "our", "please", "so", "that",
    "the", "their", "them", "there", "this", "to", "us", "was", "we", "what", "when", "where", "which", "who",
    "why", "will", "with", "you", "your", "about", "any", "all", "tell", "show", "give", "get", "would", "could",
    "should", "hi", "hello", "thanks", "thank", "ok", "okay",
}


def search_terms(text: str, limit: int = 12) -> list[str]:
    """Distinct lowercase word tokens worth searching for."""
    seen: list[str] = []
    for token in re.findall(r"[\w@.\-]+", (text or "").lower()):
        token = token.strip(".-")
        if len(token) < 2 or token in _STOPWORDS or token in seen:
            continue
        seen.append(token)
        if len(seen) >= limit:
            break
    return seen


def _or_tsquery(terms: Sequence[str]):
    # Quote each term so punctuation can't change the query's meaning; prefix-match for plurals/typos.
    quoted = " | ".join("'" + t.replace("'", "") + "':*" for t in terms)
    return func.to_tsquery("simple", quoted)


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
        query: str | None = None,
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
        terms = search_terms(query or "")
        if query and terms:
            conditions.append(Memory.search_vector.op("@@")(_or_tsquery(terms)))
        elif query:
            conditions.append(Memory.content.ilike(f"%{query.strip()}%"))

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
    async def search(
        session: AsyncSession,
        organization_id: str,
        user_id: str,
        text: str,
        *,
        limit: int = 8,
        exclude_kinds: Iterable[str] = ("activity",),
    ) -> list[Memory]:
        """Most relevant active memories for a piece of text (full-text rank, then recency)."""
        terms = search_terms(text)
        if not terms:
            return []
        tsquery = _or_tsquery(terms)
        stmt = (
            select(Memory)
            .where(
                _visible_to(organization_id, user_id),
                Memory.status == "active",
                Memory.kind.not_in(list(exclude_kinds)),
                Memory.search_vector.op("@@")(tsquery),
            )
            .order_by(func.ts_rank(Memory.search_vector, tsquery).desc(), Memory.updated_at.desc())
            .limit(limit)
        )
        return list((await session.execute(stmt)).scalars())

    @staticmethod
    async def core(session: AsyncSession, organization_id: str, user_id: str, *, limit: int = 12) -> list[Memory]:
        """Memories worth having in every conversation: pinned, then most used, then newest."""
        stmt = (
            select(Memory)
            .where(_visible_to(organization_id, user_id), Memory.status == "active", Memory.kind != "activity")
            .order_by(Memory.pinned.desc(), Memory.use_count.desc(), Memory.updated_at.desc())
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
