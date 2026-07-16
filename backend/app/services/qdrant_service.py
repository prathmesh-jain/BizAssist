from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Sequence
from urllib.parse import urlparse

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    if not settings.qdrant_url or not settings.qdrant_api_key:
        raise RuntimeError("QDRANT_URL and QDRANT_API_KEY must be configured to use the vector store.")
    normalized_url = settings.qdrant_url.rstrip("/")
    return QdrantClient(
        url=normalized_url,
        api_key=settings.qdrant_api_key,
        prefer_grpc=False,
        timeout=30,
    )


def ensure_qdrant_collection(
    collection_name: str,
    *,
    keyword_indexes: Sequence[str] | None = None,
) -> None:
    client = get_qdrant_client()
    try:
        client.get_collection(collection_name=collection_name)
        _ensure_keyword_indexes(client, collection_name, keyword_indexes or ())
        return
    except UnexpectedResponse as exc:
        if exc.status_code != 404:
            raise
        logger.info("Creating Qdrant collection %s", collection_name)
    except Exception:
        raise

    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(
            size=int(settings.embedding_vector_size or 1536),
            distance=models.Distance.COSINE,
        ),
    )
    _ensure_keyword_indexes(client, collection_name, keyword_indexes or ())


def _ensure_keyword_indexes(
    client: QdrantClient,
    collection_name: str,
    keyword_indexes: Sequence[str],
) -> None:
    for field_name in keyword_indexes:
        normalized = str(field_name or "").strip()
        if not normalized:
            continue
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=normalized,
                field_schema=models.PayloadSchemaType.KEYWORD,
                wait=True,
            )
        except UnexpectedResponse as exc:
            response_text = str(exc)
            if "already exists" in response_text.lower():
                continue
            raise


def qdrant_match_filter(key: str, value: Any) -> models.FieldCondition:
    return models.FieldCondition(
        key=key,
        match=models.MatchValue(value=value),
    )


def qdrant_filter(*conditions: models.FieldCondition) -> models.Filter | None:
    filtered_conditions = [condition for condition in conditions if condition is not None]
    if not filtered_conditions:
        return None
    return models.Filter(must=filtered_conditions)
