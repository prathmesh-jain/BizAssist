"""Rebuild the Qdrant memory index from Postgres (the source of truth).

Use after a first deploy, after restoring a database, or if the index got out of sync.

    cd backend
    python scripts/reindex_memories.py

Every active memory gets its BM25 vector. A memory also gets a meaning (dense) vector when the
person who saved it has an OpenAI key, the same rule as when it was first saved. Points for
memories that no longer exist or were replaced are removed.
"""
from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.db.base import session_scope  # noqa: E402
from app.db.models.memory import Memory  # noqa: E402
from app.services import memory_index  # noqa: E402
from app.services.memory_service import _indexed, embedding_key  # noqa: E402

BATCH = 64


async def _main() -> None:
    async with session_scope() as session:
        memories = list((await session.execute(select(Memory).where(Memory.status == "active"))).scalars())
        by_writer: dict[str | None, list[Memory]] = defaultdict(list)
        for memory in memories:
            by_writer[memory.created_by_user_id].append(memory)
        keys = {writer: (await embedding_key(session, writer) if writer else None) for writer in by_writer}

    indexed = with_dense = 0
    for writer, items in by_writer.items():
        for start in range(0, len(items), BATCH):
            batch = items[start:start + BATCH]
            if await memory_index.upsert([_indexed(m) for m in batch], api_key=keys[writer]):
                indexed += len(batch)
                with_dense += len(batch) if keys[writer] else 0

    # Remove points whose memory is gone or superseded.
    active = {m.id for m in memories}
    client, name = memory_index._client(), memory_index.collection_name()
    stale, offset = [], None
    while True:
        points, offset = client.scroll(collection_name=name, limit=256, offset=offset,
                                       with_payload=False, with_vectors=False)
        stale.extend(str(p.id) for p in points if str(p.id) not in active)
        if offset is None:
            break
    await memory_index.delete(stale)

    print(f"Memory index rebuilt: indexed={indexed} with_meaning_vectors={with_dense} removed_stale={len(stale)}")


if __name__ == "__main__":
    asyncio.run(_main())
