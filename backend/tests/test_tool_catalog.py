from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agents.tool_registry import (
    MetadataToolSearchBackend,
    PersistentToolCatalogSearchBackend,
    ToolMetadata,
)
from app.services.tool_catalog_service import build_tool_catalog_document, compute_tool_metadata_hash


class ToolCatalogHashingTests(unittest.TestCase):
    def test_hash_is_order_insensitive_for_tags_and_examples(self) -> None:
        left = ToolMetadata(
            id="sheet.append",
            name="append_rows",
            description="Append rows to a spreadsheet.",
            integration="google_sheets",
            tags=("spreadsheet", "append", "rows"),
            examples=("add invoice", "append payment"),
        )
        right = ToolMetadata(
            id="sheet.append",
            name="append_rows",
            description="Append rows to a spreadsheet.",
            integration="google_sheets",
            tags=("rows", "spreadsheet", "append"),
            examples=("append payment", "add invoice"),
        )

        self.assertEqual(compute_tool_metadata_hash(left), compute_tool_metadata_hash(right))

    def test_hash_changes_when_searchable_content_changes(self) -> None:
        left = ToolMetadata(
            id="sheet.append",
            name="append_rows",
            description="Append rows to a spreadsheet.",
            integration="google_sheets",
        )
        right = ToolMetadata(
            id="sheet.append",
            name="append_rows",
            description="Append invoice records to a spreadsheet.",
            integration="google_sheets",
        )

        self.assertNotEqual(compute_tool_metadata_hash(left), compute_tool_metadata_hash(right))

    def test_document_contains_normalized_search_fields(self) -> None:
        metadata = ToolMetadata(
            id="rag.retrieve",
            name="rag_retrieve",
            description="Search indexed documents.",
            integration="rag",
            tags=("documents", "search"),
            examples=("find invoice",),
        )

        document = build_tool_catalog_document(metadata)

        self.assertIn("rag_retrieve", document)
        self.assertIn("Integration: rag", document)
        self.assertIn("Tags: documents, search", document)
        self.assertIn("Examples: find invoice", document)


class PersistentToolSearchBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_stale_catalog_ids(self) -> None:
        tools = [
            ToolMetadata(
                id="sheets_read_range",
                name="sheets_read_range",
                description="Read cells.",
                integration="google_sheets",
            )
        ]
        backend = PersistentToolCatalogSearchBackend()

        with patch(
            "app.agents.tool_registry.query_tool_catalog",
            return_value=[
                {"tool_id": "stale_tool", "score": 0.95},
                {"tool_id": "sheets_read_range", "score": 0.82},
            ],
        ):
            results = await backend.search("read spreadsheet rows", tools, state={}, limit=5, exclude_ids=set())

        self.assertEqual([item.metadata.id for item in results], ["sheets_read_range"])

    async def test_falls_back_to_metadata_search_when_catalog_query_fails(self) -> None:
        tools = [
            ToolMetadata(
                id="rag_retrieve",
                name="rag_retrieve",
                description="Search indexed business documents and return passages.",
                integration="rag",
                tags=("documents", "search"),
            )
        ]
        backend = PersistentToolCatalogSearchBackend(fallback_backend=MetadataToolSearchBackend())

        with patch(
            "app.agents.tool_registry.query_tool_catalog",
            side_effect=RuntimeError("catalog unavailable"),
        ):
            results = await backend.search("search documents", tools, state={}, limit=5, exclude_ids=set())

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metadata.id, "rag_retrieve")


if __name__ == "__main__":
    unittest.main()
