from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import Any

import chromadb
from langchain_openai import OpenAIEmbeddings

from app.config import get_settings
from app.services.user_settings_service import get_user_openai_api_key

logger = logging.getLogger(__name__)
settings = get_settings()

TOOL_CATALOG_COLLECTION_NAME = "tool_catalog"

_tool_catalog_client: chromadb.PersistentClient | None = None
_tool_catalog_collection: chromadb.Collection | None = None


def get_tool_catalog_collection() -> chromadb.Collection:
    global _tool_catalog_client, _tool_catalog_collection
    if _tool_catalog_client is None:
        _tool_catalog_client = chromadb.PersistentClient(path=settings.chroma_path)
    if _tool_catalog_collection is None:
        _tool_catalog_collection = _tool_catalog_client.get_or_create_collection(
            name=TOOL_CATALOG_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _tool_catalog_collection


def build_tool_catalog_id(tool_id: str) -> str:
    return f"tool:{tool_id.strip()}"


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
        model="text-embedding-3-small",
        api_key=api_key,
    )


def build_tool_catalog_metadata(metadata: Any) -> dict[str, str]:
    normalized = _normalize_metadata_parts(metadata)
    return {
        "tool_id": normalized["id"],
        "name": normalized["name"],
        "integration": normalized["integration"],
        "content_hash": compute_tool_metadata_hash(metadata),
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "tags_text": " | ".join(normalized["tags"]),
        "examples_text": " | ".join(normalized["examples"]),
    }


def get_tool_catalog_snapshot() -> dict[str, dict[str, Any]]:
    collection = get_tool_catalog_collection()
    records = collection.get(include=["metadatas", "documents"])
    snapshot: dict[str, dict[str, Any]] = {}
    ids = records.get("ids", []) or []
    metadatas = records.get("metadatas", []) or []
    documents = records.get("documents", []) or []

    for record_id, metadata, document in zip(ids, metadatas, documents):
        snapshot[str(record_id)] = {
            "metadata": metadata or {},
            "document": document or "",
        }
    return snapshot


async def upsert_tool_catalog_entries(
    metadatas: Sequence[Any],
    *,
    force: bool = False,
) -> dict[str, int]:
    collection = get_tool_catalog_collection()
    snapshot = get_tool_catalog_snapshot()
    embeddings_model = await get_tool_catalog_embeddings_model(user_id=None)

    to_upsert: list[Any] = []
    skipped = 0

    for metadata in metadatas:
        record_id = build_tool_catalog_id(str(getattr(metadata, "id", "") or ""))
        current_hash = compute_tool_metadata_hash(metadata)
        existing = snapshot.get(record_id, {})
        existing_hash = str((existing.get("metadata") or {}).get("content_hash") or "")

        if not force and existing_hash == current_hash:
            skipped += 1
            continue
        to_upsert.append(metadata)

    if to_upsert:
        documents = [build_tool_catalog_document(metadata) for metadata in to_upsert]
        embeddings = await embeddings_model.aembed_documents(documents)
        ids = [build_tool_catalog_id(str(getattr(metadata, "id", "") or "")) for metadata in to_upsert]
        chroma_metadatas = [build_tool_catalog_metadata(metadata) for metadata in to_upsert]
        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=chroma_metadatas,
        )

    return {
        "upserted": len(to_upsert),
        "skipped": skipped,
    }


def prune_stale_tool_catalog_entries(active_tool_ids: Iterable[str]) -> int:
    collection = get_tool_catalog_collection()
    active_record_ids = {build_tool_catalog_id(tool_id) for tool_id in active_tool_ids if str(tool_id).strip()}
    snapshot_ids = set(get_tool_catalog_snapshot().keys())
    stale_ids = sorted(snapshot_ids - active_record_ids)
    if stale_ids:
        collection.delete(ids=stale_ids)
    return len(stale_ids)


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

    collection = get_tool_catalog_collection()
    embeddings_model = await get_tool_catalog_embeddings_model(user_id=user_id)
    query_embedding = await embeddings_model.aembed_query(normalized_query)

    fetch_limit = max(int(limit or 5) + len(exclude_ids or set()) + 5, int(limit or 5))
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=fetch_limit,
        include=["metadatas", "distances"],
    )

    exclude_record_ids = {build_tool_catalog_id(tool_id) for tool_id in (exclude_ids or set())}
    record_ids = results.get("ids", [[]])[0] or []
    metadatas = results.get("metadatas", [[]])[0] or []
    distances = results.get("distances", [[]])[0] or []

    matches: list[dict[str, Any]] = []
    for record_id, metadata, distance in zip(record_ids, metadatas, distances):
        if record_id in exclude_record_ids:
            continue
        tool_id = str((metadata or {}).get("tool_id") or "")
        if not tool_id:
            continue
        score = 1.0 - float(distance or 0.0)
        matches.append(
            {
                "tool_id": tool_id,
                "score": score,
                "distance": float(distance or 0.0),
                "metadata": metadata or {},
            }
        )
        if len(matches) >= limit:
            break
    return matches
