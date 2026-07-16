from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Iterable, Protocol, Sequence

from app.agents.state import AgentState
from app.services.tool_catalog_service import query_tool_catalog

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolMetadata:
    id: str
    name: str
    description: str
    integration: str
    tags: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolSearchResult:
    metadata: ToolMetadata
    score: float


class ToolSearchBackend(Protocol):
    async def search(
        self,
        query: str,
        tools: Sequence[ToolMetadata],
        state: AgentState,
        *,
        limit: int = 5,
        exclude_ids: set[str] | None = None,
    ) -> list[ToolSearchResult]:
        ...


def _tokenize(value: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in value)
    return [token for token in cleaned.split() if token]


class MetadataToolSearchBackend:
    """Lexical fallback search over tool metadata."""

    async def search(
        self,
        query: str,
        tools: Sequence[ToolMetadata],
        state: AgentState,
        *,
        limit: int = 5,
        exclude_ids: set[str] | None = None,
    ) -> list[ToolSearchResult]:
        exclude_ids = exclude_ids or set()
        query_tokens = set(_tokenize(query))
        scored: list[ToolSearchResult] = []

        for metadata in tools:
            if metadata.id in exclude_ids:
                continue
            score = self._score(metadata, query_tokens)
            if score > 0:
                scored.append(ToolSearchResult(metadata=metadata, score=score))

        scored.sort(
            key=lambda item: (
                item.score,
                len(item.metadata.examples),
                len(item.metadata.tags),
                item.metadata.name,
            ),
            reverse=True,
        )
        return scored[:limit]

    def _score(self, metadata: ToolMetadata, query_tokens: set[str]) -> float:
        if not query_tokens:
            return 0.0

        name_tokens = set(_tokenize(metadata.name))
        desc_tokens = set(_tokenize(metadata.description))
        tag_tokens = set(token.lower() for token in metadata.tags)
        example_tokens = set()
        for example in metadata.examples:
            example_tokens.update(_tokenize(example))

        score = 0.0
        for token in query_tokens:
            if token in name_tokens:
                score += 6.0
            if token in tag_tokens:
                score += 4.0
            if token in desc_tokens:
                score += 2.5
            if token in example_tokens:
                score += 3.0

        return score


class PersistentToolCatalogSearchBackend:
    """Semantic tool search backed by the persistent Chroma tool catalog."""

    def __init__(self, fallback_backend: ToolSearchBackend | None = None):
        self._fallback_backend = fallback_backend or MetadataToolSearchBackend()

    async def search(
        self,
        query: str,
        tools: Sequence[ToolMetadata],
        state: AgentState,
        *,
        limit: int = 5,
        exclude_ids: set[str] | None = None,
    ) -> list[ToolSearchResult]:
        exclude_ids = exclude_ids or set()
        metadata_by_id = {metadata.id: metadata for metadata in tools}
        if not metadata_by_id:
            return []

        try:
            raw_results = await query_tool_catalog(
                query,
                limit=max(limit * 2, 8),
                exclude_ids=exclude_ids,
                user_id=state.get("user_id"),
            )
        except Exception as exc:
            logger.warning("Persistent tool catalog search failed, falling back to metadata search: %s", exc)
            return await self._fallback_backend.search(
                query,
                tools,
                state,
                limit=limit,
                exclude_ids=exclude_ids,
            )

        scored: list[ToolSearchResult] = []
        seen_ids: set[str] = set()
        for raw in raw_results:
            tool_id = str(raw.get("tool_id") or "")
            metadata = metadata_by_id.get(tool_id)
            if not metadata or tool_id in seen_ids:
                continue
            seen_ids.add(tool_id)
            scored.append(ToolSearchResult(metadata=metadata, score=float(raw.get("score") or 0.0)))
            if len(scored) >= limit:
                break

        if scored:
            return scored

        return await self._fallback_backend.search(
            query,
            tools,
            state,
            limit=limit,
            exclude_ids=exclude_ids,
        )


ToolLoader = Callable[[AgentState], list]


class ToolRegistry:
    def __init__(self, search_backend: ToolSearchBackend | None = None):
        self._search_backend = search_backend or MetadataToolSearchBackend()
        self._metadata: dict[str, ToolMetadata] = {}
        self._loaders: dict[str, ToolLoader] = {}

    def register(self, metadata: ToolMetadata, loader: ToolLoader) -> None:
        self._metadata[metadata.id] = metadata
        self._loaders[metadata.id] = loader

    async def search(
        self,
        query: str,
        state: AgentState,
        *,
        limit: int = 5,
        exclude_ids: Iterable[str] | None = None,
    ) -> list[ToolSearchResult]:
        return await self._search_backend.search(
            query,
            list(self._metadata.values()),
            state,
            limit=limit,
            exclude_ids=set(exclude_ids or []),
        )

    def load(self, tool_ids: Sequence[str], state: AgentState) -> list:
        loaded_tools: list = []
        seen_names: set[str] = set()
        for tool_id in tool_ids:
            metadata = self._metadata.get(tool_id)
            loader = self._loaders.get(tool_id)
            if not loader or not metadata:
                continue
            for tool in loader(state):
                tool_name = getattr(tool, "name", None)
                if tool_name != metadata.name:
                    continue
                if tool_name in seen_names:
                    continue
                seen_names.add(tool_name)
                loaded_tools.append(tool)
        return loaded_tools

    def get_metadata(self, tool_id: str) -> ToolMetadata | None:
        return self._metadata.get(tool_id)

    def list_metadata(self) -> list[ToolMetadata]:
        return list(self._metadata.values())

    def describe(self, tool_ids: Sequence[str]) -> list[dict[str, object]]:
        described: list[dict[str, object]] = []
        for tool_id in tool_ids:
            metadata = self.get_metadata(tool_id)
            if not metadata:
                continue
            described.append(
                {
                    "id": metadata.id,
                    "name": metadata.name,
                    "description": metadata.description,
                    "integration": metadata.integration,
                    "tags": list(metadata.tags),
                    "examples": list(metadata.examples),
                }
            )
        return described


def _register_metadata(
    registry: ToolRegistry,
    entries: Sequence[ToolMetadata],
    loader: ToolLoader,
) -> None:
    for entry in entries:
        registry.register(entry, loader)


@lru_cache(maxsize=1)
def get_tool_registry() -> ToolRegistry:
    from app.agents.tooling import get_document_listing_tools
    from app.agents.tooling import get_core_tools
    from app.tools.chat_attachments_tools import get_chat_attachments_tools
    from app.tools.google_sheets_tools import get_sheets_tools

    registry = ToolRegistry(search_backend=PersistentToolCatalogSearchBackend())

    def core_loader(state: AgentState) -> list:
        return get_core_tools(state)

    def attachment_loader(state: AgentState) -> list:
        return get_chat_attachments_tools(
            user_id=state.get("user_id", ""),
            chat_id=state.get("chat_id"),
        )

    def document_listing_loader(state: AgentState) -> list:
        return get_document_listing_tools(state)

    def sheets_loader(state: AgentState) -> list:
        return get_sheets_tools(
            user_id=state.get("user_id", ""),
            chat_id=state.get("chat_id"),
        )

    _register_metadata(
        registry,
        [
            ToolMetadata(
                id="request_clarification",
                name="request_clarification",
                description="Ask the user for missing information or confirmation before proceeding.",
                integration="core",
                tags=("clarify", "confirm", "missing_info", "approval"),
                examples=("which sheet should I update", "please confirm this change"),
            ),
            ToolMetadata(
                id="rag_retrieve",
                name="rag_retrieve",
                description="Search indexed business documents and return relevant passages.",
                integration="rag",
                tags=("documents", "search", "knowledge_base", "retrieve"),
                examples=("find unpaid invoices in documents", "search contract terms"),
            ),
        ],
        core_loader,
    )

    _register_metadata(
        registry,
        [
            ToolMetadata(
                id="list_documents",
                name="list_documents",
                description="List available documents across chat uploads and indexed knowledge-base documents, with optional fuzzy filename matching.",
                integration="documents",
                tags=("documents", "files", "list", "search", "chat_upload", "knowledge_base"),
                examples=("find invoice pdf", "list uploaded and indexed documents"),
            ),
        ],
        document_listing_loader,
    )

    _register_metadata(
        registry,
        [
            ToolMetadata(
                id="chat_read_attachment_text",
                name="chat_read_attachment_text",
                description="Read text content from uploaded chat attachments, including PDFs and extracted text files.",
                integration="attachments",
                tags=("attachments", "files", "pdf", "text", "read"),
                examples=("read this pdf", "inspect uploaded invoice"),
            ),
        ],
        attachment_loader,
    )

    _register_metadata(
        registry,
        [
            ToolMetadata(
                id="sheets_list_tabs",
                name="sheets_list_tabs",
                description="List worksheet tabs in a spreadsheet.",
                integration="google_sheets",
                tags=("spreadsheet", "sheet", "tabs", "list"),
                examples=("show tabs", "list worksheets"),
            ),
            ToolMetadata(
                id="sheets_read_range",
                name="sheets_read_range",
                description="Read cell values from a spreadsheet range.",
                integration="google_sheets",
                tags=("spreadsheet", "sheet", "read", "cells", "range"),
                examples=("read transactions", "show spreadsheet rows"),
            ),
            ToolMetadata(
                id="sheets_get_headers",
                name="sheets_get_headers",
                description="Fetch column headers for a sheet before mapping writes.",
                integration="google_sheets",
                tags=("spreadsheet", "headers", "columns", "schema"),
                examples=("get headers", "show sheet columns"),
            ),
            ToolMetadata(
                id="sheets_get_metadata",
                name="sheets_get_metadata",
                description="Fetch spreadsheet metadata and structural details.",
                integration="google_sheets",
                tags=("spreadsheet", "metadata", "structure"),
                examples=("show spreadsheet info", "get sheet metadata"),
            ),
            ToolMetadata(
                id="sheets_append_values",
                name="sheets_append_values",
                description="Append rows or values to a spreadsheet.",
                integration="google_sheets",
                tags=("spreadsheet", "append", "rows", "insert", "write"),
                examples=("append invoice", "add transaction"),
            ),
            ToolMetadata(
                id="sheets_update_values",
                name="sheets_update_values",
                description="Update existing spreadsheet values in a target range.",
                integration="google_sheets",
                tags=("spreadsheet", "update", "edit", "write"),
                examples=("update payment status", "edit row values"),
            ),
            ToolMetadata(
                id="sheets_clear_values",
                name="sheets_clear_values",
                description="Clear values from a spreadsheet range.",
                integration="google_sheets",
                tags=("spreadsheet", "clear", "delete", "range"),
                examples=("clear old values", "wipe a range"),
            ),
            ToolMetadata(
                id="sheets_batch_update",
                name="sheets_batch_update",
                description="Perform advanced spreadsheet batch operations and formatting changes.",
                integration="google_sheets",
                tags=("spreadsheet", "batch", "formatting", "advanced"),
                examples=("merge cells", "format report"),
            ),
            ToolMetadata(
                id="sheets_create_tab",
                name="sheets_create_tab",
                description="Create a new worksheet tab.",
                integration="google_sheets",
                tags=("spreadsheet", "create", "tab", "worksheet"),
                examples=("create monthly sheet", "add tab"),
            ),
            ToolMetadata(
                id="sheets_rename_tab",
                name="sheets_rename_tab",
                description="Rename an existing worksheet tab.",
                integration="google_sheets",
                tags=("spreadsheet", "rename", "tab", "worksheet"),
                examples=("rename tab", "change worksheet name"),
            ),
            ToolMetadata(
                id="sheets_delete_tab",
                name="sheets_delete_tab",
                description="Delete a worksheet tab.",
                integration="google_sheets",
                tags=("spreadsheet", "delete", "tab", "worksheet"),
                examples=("delete tab", "remove worksheet"),
            ),
            ToolMetadata(
                id="sheets_resize_grid",
                name="sheets_resize_grid",
                description="Resize spreadsheet row and column limits.",
                integration="google_sheets",
                tags=("spreadsheet", "resize", "grid", "rows", "columns"),
                examples=("expand sheet", "resize grid"),
            ),
            ToolMetadata(
                id="sheets_insert_dimension",
                name="sheets_insert_dimension",
                description="Insert rows or columns into a sheet.",
                integration="google_sheets",
                tags=("spreadsheet", "insert", "rows", "columns"),
                examples=("insert rows", "add columns"),
            ),
            ToolMetadata(
                id="sheets_delete_dimension",
                name="sheets_delete_dimension",
                description="Delete rows or columns from a sheet.",
                integration="google_sheets",
                tags=("spreadsheet", "delete", "rows", "columns"),
                examples=("delete rows", "remove columns"),
            ),
        ],
        sheets_loader,
    )

    return registry
