from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.tool_registry import get_tool_registry
from app.services.tool_catalog_service import prune_stale_tool_catalog_entries, upsert_tool_catalog_entries


async def _main() -> None:
    registry = get_tool_registry()
    metadatas = registry.list_metadata()
    tool_ids = [metadata.id for metadata in metadatas]

    upsert_result = await upsert_tool_catalog_entries(metadatas)
    removed = prune_stale_tool_catalog_entries(tool_ids)

    print(
        "Tool catalog sync complete:",
        f"added_or_updated={upsert_result['upserted']}",
        f"skipped={upsert_result['skipped']}",
        f"removed={removed}",
    )


if __name__ == "__main__":
    asyncio.run(_main())
