from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import Any

from langchain_openai import OpenAIEmbeddings
from qdrant_client import models

from app.config import get_settings
from app.services.qdrant_service import ensure_qdrant_collection, get_qdrant_client
from app.services.user_settings_service import get_user_openai_api_key

logger = logging.getLogger(__name__)
settings = get_settings()


def get_tool_catalog_collection_name() -> str:
    return settings.qdrant_tool_catalog_collection


def build_tool_catalog_point_id(tool_id: str) -> str:
    normalized_tool_id = tool_id.strip()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"bizassist-tool:{normalized_tool_id}"))


def _normalize_metadata_parts(metadata: Any) -> dict[str, Any]:
    tags = sorted({str(tag).strip() for tag in (getattr(metadata, "tags", ()) or ()) if str(tag).strip()})
    examples = sorted(
        {str(example).strip() for example in (getattr(metadata, "examples", ()) or ()) if str(example).strip()}
    )
    return {
        "id": str(getattr(metadata, "id", "") or "").strip(),
        "name": str(getattr(metadata, "name", "") or "").strip(),
        "description": str(getattr(metadata, "description", "") or "").strip(),
        "integration": str(getattr(metadata, "integration", "") or "").strip(),
        "tags": tags,
        "examples": examples,
    }


def build_tool_catalog_document(metadata: Any) -> str:
    normalized = _normalize_metadata_parts(metadata)
    parts = [
        normalized["name"],
        normalized["description"],
        f"Integration: {normalized['integration']}",
    ]
    if normalized["tags"]:
        parts.append("Tags: " + ", ".join(normalized["tags"]))
    if normalized["examples"]:
        parts.append("Examples: " + "; ".join(normalized["examples"]))
    return "\n".join(part for part in parts if part).strip()


def compute_tool_metadata_hash(metadata: Any) -> str:
    normalized = _normalize_metadata_parts(metadata)
    serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def resolve_embedding_api_key(user_id: str | None = None) -> str:
    if user_id:
        user_key = await get_user_openai_api_key(user_id)
        if user_key:
            return user_key
    if settings.openai_api_key:
        return settings.openai_api_key
    raise RuntimeError("An OpenAI API key is required to query or build the tool catalog.")


async def get_tool_catalog_embeddings_model(user_id: str | None = None) -> OpenAIEmbeddings:
    api_key = await resolve_embedding_api_key(user_id=user_id)
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=api_key,
    )


def build_tool_catalog_payload(metadata: Any) -> dict[str, str]:
    normalized = _normalize_metadata_parts(metadata)
    return {
        "tool_id": normalized["id"],
        "name": normalized["name"],
        "integration": normalized["integration"],
        "content_hash": compute_tool_metadata_hash(metadata),
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "tags_text": " | ".join(normalized["tags"]),
        "examples_text": " | ".join(normalized["examples"]),
        "document": build_tool_catalog_document(metadata),
    }


def get_tool_catalog_snapshot() -> dict[str, dict[str, Any]]:
    collection_name = get_tool_catalog_collection_name()
    ensure_qdrant_collection(collection_name)
    client = get_qdrant_client()

    snapshot: dict[str, dict[str, Any]] = {}
    next_offset: Any = None

    while True:
        points, next_offset = client.scroll(
            collection_name=collection_name,
            limit=256,
            offset=next_offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            tool_id = str(payload.get("tool_id") or "").strip()
            if not tool_id:
                continue
            snapshot[tool_id] = {
                "point_id": str(point.id),
                "payload": payload,
            }
        if next_offset is None:
            break

    return snapshot


async def upsert_tool_catalog_entries(
    metadatas: Sequence[Any],
    *,
    force: bool = False,
) -> dict[str, int]:
    collection_name = get_tool_catalog_collection_name()
    ensure_qdrant_collection(collection_name)
    client = get_qdrant_client()
    snapshot = get_tool_catalog_snapshot()
    embeddings_model = await get_tool_catalog_embeddings_model(user_id=None)

    to_upsert: list[Any] = []
    skipped = 0

    for metadata in metadatas:
        tool_id = str(getattr(metadata, "id", "") or "").strip()
        current_hash = compute_tool_metadata_hash(metadata)
        existing = snapshot.get(tool_id, {})
        existing_hash = str((existing.get("payload") or {}).get("content_hash") or "")

        if not force and existing_hash == current_hash:
            skipped += 1
            continue
        to_upsert.append(metadata)

    if to_upsert:
        documents = [build_tool_catalog_document(metadata) for metadata in to_upsert]
        embeddings = await embeddings_model.aembed_documents(documents)
        points = [
            models.PointStruct(
                id=build_tool_catalog_point_id(str(getattr(metadata, "id", "") or "")),
                vector=embedding,
                payload=build_tool_catalog_payload(metadata),
            )
            for metadata, embedding in zip(to_upsert, embeddings)
        ]
        client.upsert(
            collection_name=collection_name,
            points=points,
            wait=True,
        )

    return {
        "upserted": len(to_upsert),
        "skipped": skipped,
    }


def prune_stale_tool_catalog_entries(active_tool_ids: Iterable[str]) -> int:
    collection_name = get_tool_catalog_collection_name()
    ensure_qdrant_collection(collection_name)
    client = get_qdrant_client()

    active_tool_ids_set = {str(tool_id).strip() for tool_id in active_tool_ids if str(tool_id).strip()}
    snapshot = get_tool_catalog_snapshot()
    stale_point_ids = sorted(
        str(record.get("point_id"))
        for tool_id, record in snapshot.items()
        if tool_id not in active_tool_ids_set and record.get("point_id")
    )
    if stale_point_ids:
        client.delete(
            collection_name=collection_name,
            points_selector=models.PointIdsList(points=stale_point_ids),
            wait=True,
        )
    return len(stale_point_ids)


async def query_tool_catalog(
    query: str,
    *,
    limit: int = 5,
    exclude_ids: set[str] | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    normalized_query = query.strip()
    if not normalized_query:
        return []

    collection_name = get_tool_catalog_collection_name()
    ensure_qdrant_collection(collection_name)
    client = get_qdrant_client()
    embeddings_model = await get_tool_catalog_embeddings_model(user_id=user_id)
    query_embedding = await embeddings_model.aembed_query(normalized_query)

    response = client.query_points(
        collection_name=collection_name,
        query=query_embedding,
        limit=max(int(limit or 5) + len(exclude_ids or set()) + 5, int(limit or 5)),
        with_payload=True,
        with_vectors=False,
    )

    exclude_tool_ids = {str(tool_id).strip() for tool_id in (exclude_ids or set())}
    matches: list[dict[str, Any]] = []
    for point in response.points:
        payload = point.payload or {}
        tool_id = str(payload.get("tool_id") or "")
        if not tool_id or tool_id in exclude_tool_ids:
            continue
        matches.append(
            {
                "tool_id": tool_id,
                "score": float(point.score or 0.0),
                "payload": payload,
            }
        )
        if len(matches) >= limit:
            break
    return matches
