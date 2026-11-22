"""Qdrant index for long-term memory: hybrid dense (meaning) + BM25 (keyword) search.

Postgres (`memories` table) is the source of truth; this index mirrors active memories so they
can be found by meaning and by exact words.

Each point has:
  * "bm25"  sparse vector: always present; keyword search works for every user, no key needed.
  * "dense" vector: the organization's shared embedding model (settings.embedding_model) via the
    writer's own OpenAI key. Missing when the writer had no key; filled in later by `backfill_dense`
    when someone in the organization with a key saves a memory.

Search fuses both with Reciprocal Rank Fusion when the searcher has an embedding key, so a memory
found only by an exact word (an invoice number, a GSTIN, a rare name) still comes back; without a
key it is BM25 only. Queries can include the last few conversation turns (see `search`).
All Qdrant calls run in a worker thread, and every function here degrades to
"no results" rather than raising, so memory problems never break a chat.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Iterable, Sequence

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.config import get_settings
from app.services import bm25

logger = logging.getLogger(__name__)

DENSE = "dense"
SPARSE = "bm25"
# Cosine similarity below this is treated as unrelated for the meaning-based prefetch.
DENSE_MIN_SCORE = 0.3
PREFETCH_LIMIT = 50

_collection_ready = False


@dataclass(frozen=True)
class IndexedMemory:
    id: str
    organization_id: str
    scope: str
    user_id: str | None
    kind: str
    content: str


def _settings():
    return get_settings()


def collection_name() -> str:
    return _settings().qdrant_memory_collection


def _client() -> QdrantClient:
    from app.services.qdrant_service import get_qdrant_client

    return get_qdrant_client()


def _ensure_collection_sync() -> None:
    global _collection_ready
    if _collection_ready:
        return
    client, name = _client(), collection_name()
    try:
        client.get_collection(collection_name=name)
    except (UnexpectedResponse, ValueError) as exc:
        if isinstance(exc, UnexpectedResponse) and exc.status_code != 404:
            raise
        client.create_collection(
            collection_name=name,
            vectors_config={
                DENSE: models.VectorParams(size=int(_settings().embedding_vector_size), distance=models.Distance.COSINE)
            },
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
    for field in ("organization_id", "scope", "user_id", "kind"):
        try:
            client.create_payload_index(name, field_name=field, field_schema=models.PayloadSchemaType.KEYWORD, wait=True)
        except Exception:
            pass  # already exists, or the local test client ignores payload indexes
    _collection_ready = True


async def _run(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


# ---------- embeddings ----------

async def embed(texts: Sequence[str], api_key: str | None) -> list[list[float]] | None:
    """Embed texts with the shared model on this user's key; None when they have no key or it fails."""
    if not api_key or not texts:
        return None
    from langchain_openai import OpenAIEmbeddings

    try:
        model = OpenAIEmbeddings(model=_settings().embedding_model, api_key=api_key)
        return await model.aembed_documents(list(texts))
    except Exception:
        logger.warning("memory_index.embed_failed", exc_info=True)
        return None


# ---------- writes ----------

def _point(memory: IndexedMemory, dense: list[float] | None) -> models.PointStruct:
    vectors: dict = {SPARSE: bm25.document_vector(memory.content)}
    if dense is not None:
        vectors[DENSE] = dense
    return models.PointStruct(
        id=memory.id,
        vector=vectors,
        payload={
            "organization_id": memory.organization_id,
            "scope": memory.scope,
            "user_id": memory.user_id,
            "kind": memory.kind,
            "content": memory.content,
            "has_dense": dense is not None,
        },
    )


async def upsert(memories: Sequence[IndexedMemory], *, api_key: str | None) -> bool:
    if not memories:
        return True
    vectors = await embed([m.content for m in memories], api_key)
    points = [_point(m, vectors[i] if vectors else None) for i, m in enumerate(memories)]
    try:
        await _run(_ensure_collection_sync)
        await _run(_client().upsert, collection_name=collection_name(), points=points, wait=True)
        return True
    except Exception:
        logger.warning("memory_index.upsert_failed ids=%s", [m.id for m in memories], exc_info=True)
        return False


async def delete(memory_ids: Iterable[str]) -> None:
    ids = [i for i in memory_ids if i]
    if not ids:
        return
    try:
        await _run(_ensure_collection_sync)
        await _run(_client().delete, collection_name=collection_name(),
                   points_selector=models.PointIdsList(points=ids), wait=True)
    except Exception:
        logger.warning("memory_index.delete_failed ids=%s", ids, exc_info=True)


async def delete_personal(organization_id: str, user_id: str) -> None:
    try:
        await _run(_ensure_collection_sync)
        await _run(
            _client().delete,
            collection_name=collection_name(),
            points_selector=models.FilterSelector(filter=models.Filter(must=[
                _match("organization_id", organization_id), _match("scope", "personal"), _match("user_id", user_id),
            ])),
            wait=True,
        )
    except Exception:
        logger.warning("memory_index.delete_personal_failed org=%s user=%s", organization_id, user_id, exc_info=True)


async def backfill_dense(organization_id: str, api_key: str | None, *, limit: int = 32) -> int:
    """Add meaning vectors to this organization's memories saved by people without a key."""
    if not api_key:
        return 0
    try:
        await _run(_ensure_collection_sync)
        points, _ = await _run(
            _client().scroll,
            collection_name=collection_name(),
            scroll_filter=models.Filter(must=[_match("organization_id", organization_id), _match("has_dense", False)]),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
    except Exception:
        logger.warning("memory_index.backfill_scroll_failed org=%s", organization_id, exc_info=True)
        return 0
    if not points:
        return 0
    memories = [
        IndexedMemory(str(p.id), p.payload["organization_id"], p.payload["scope"], p.payload.get("user_id"),
                      p.payload["kind"], p.payload["content"])
        for p in points
    ]
    vectors = await embed([m.content for m in memories], api_key)
    if not vectors:
        return 0
    try:
        await _run(_client().upsert, collection_name=collection_name(),
                   points=[_point(m, vectors[i]) for i, m in enumerate(memories)], wait=True)
        return len(memories)
    except Exception:
        logger.warning("memory_index.backfill_upsert_failed org=%s", organization_id, exc_info=True)
        return 0


# ---------- search ----------

def _match(key: str, value) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


def visibility_filter(
    organization_id: str, user_id: str, *, kinds: Sequence[str] | None = None,
    exclude_kinds: Sequence[str] | None = None, scope: str | None = None,
) -> models.Filter:
    """This organization's shared memories plus this user's own personal ones."""
    must: list = [
        _match("organization_id", organization_id),
        models.Filter(should=[
            _match("scope", "shared"),
            models.Filter(must=[_match("scope", "personal"), _match("user_id", user_id)]),
        ]),
    ]
    if scope:
        must.append(_match("scope", scope))
    if kinds:
        must.append(models.FieldCondition(key="kind", match=models.MatchAny(any=list(kinds))))
    must_not = [models.FieldCondition(key="kind", match=models.MatchAny(any=list(exclude_kinds)))] if exclude_kinds else None
    return models.Filter(must=must, must_not=must_not)


async def search(
    text: str,
    *,
    organization_id: str,
    user_id: str,
    api_key: str | None,
    limit: int = 8,
    kinds: Sequence[str] | None = None,
    exclude_kinds: Sequence[str] | None = ("activity",),
    scope: str | None = None,
    context: str | None = None,
) -> list[tuple[str, float]]:
    """Memory ids ranked for `text`, optionally informed by recent conversation `context`.

    Up to four candidate lists are fused with Reciprocal Rank Fusion in one Qdrant query:
    BM25 for the current message and for message + context, and (with an embedding key) dense
    for the same two. The current-message lists keep a self-contained question from being
    diluted; the context lists resolve follow-ups like "what about him?" or "change it to Kumar".
    """
    current = (text or "").strip()
    recent = (context or "").strip()
    combined = f"{current}\n{recent}".strip() if recent else current
    if not combined:
        return []

    queries = [q for q in dict.fromkeys([current, combined]) if q]  # distinct, current first
    sparse = [v for v in (bm25.query_vector(q) for q in queries) if v.indices]
    dense = await embed(queries, api_key)
    if not sparse and not dense:
        return []
    flt = visibility_filter(organization_id, user_id, kinds=kinds, exclude_kinds=exclude_kinds, scope=scope)
    prefetch = [
        models.Prefetch(query=vector, using=DENSE, limit=PREFETCH_LIMIT, score_threshold=DENSE_MIN_SCORE, filter=flt)
        for vector in (dense or [])
    ] + [models.Prefetch(query=vector, using=SPARSE, limit=PREFETCH_LIMIT, filter=flt) for vector in sparse]
    try:
        await _run(_ensure_collection_sync)
        result = await _run(
            _client().query_points, collection_name=collection_name(), prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF), query_filter=flt, limit=limit,
        )
        return [(str(p.id), float(p.score)) for p in result.points]
    except Exception:
        logger.warning("memory_index.search_failed org=%s", organization_id, exc_info=True)
        return []


def reset_collection_cache() -> None:
    """For tests and the reindex script."""
    global _collection_ready
    _collection_ready = False
