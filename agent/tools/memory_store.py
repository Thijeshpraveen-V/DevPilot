"""
agent/tools/memory_store.py
───────────────────────────
Long-term memory via ChromaDB.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.tools.base import BaseTool, ToolResult, ToolSchema

if TYPE_CHECKING:
    from agent.config import Config


_COLLECTION_NAME = "devpilot_memory"
_DB_PATH = os.path.join(os.path.expanduser("~"), ".devpilot", "memory")


def _get_client():
    """Lazily import and create the ChromaDB client."""
    import chromadb  # type: ignore[import]
    Path(_DB_PATH).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=_DB_PATH)


class MemoryStoreTool(BaseTool):
    """Store and retrieve information in persistent long-term memory."""

    def __init__(self, config: "Config") -> None:
        self._config = config

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="memory_store",
            description=(
                "Store or search your long-term memory. "
                "Use 'store' to remember important facts, snippets, or decisions. "
                "Use 'search' to recall things from past conversations. "
                "Use 'list' to see all stored memories. "
                "Use 'delete' to remove a memory by ID."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["store", "search", "list", "delete"],
                        "description": "Action to perform.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to store (required for 'store').",
                    },
                    "query": {
                        "type": "string",
                        "description": "Query to search memory (required for 'search').",
                    },
                    "memory_id": {
                        "type": "string",
                        "description": "Memory ID to delete (required for 'delete').",
                    },
                    "n_results": {
                        "type": "integer",
                        "description": "Number of memories to retrieve for 'search' (default: 5).",
                        "default": 5,
                    },
                },
                "required": ["action"],
            },
            required=["action"],
            sprint="Sprint 2",
        )

    async def execute(  # type: ignore[override]
        self,
        action: str,
        content: str | None = None,
        query: str | None = None,
        memory_id: str | None = None,
        n_results: int = 5,
    ) -> ToolResult:
        try:
            client = _get_client()
            collection = client.get_or_create_collection(_COLLECTION_NAME)
        except ImportError:
            return ToolResult(
                "Error: chromadb is not installed. Run: pip install chromadb",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(f"Memory store initialization error: {e}", is_error=True)

        if action == "store":
            if not content:
                return ToolResult("Error: 'content' is required for store action.", is_error=True)
            mem_id = hashlib.sha256(content.encode()).hexdigest()[:12]
            try:
                collection.upsert(
                    documents=[content],
                    ids=[mem_id],
                )
                return ToolResult(f"✓ Memory stored with ID: {mem_id}\n\n{content[:200]}", is_error=False)
            except Exception as e:
                return ToolResult(f"Error storing memory: {e}", is_error=True)

        elif action == "search":
            if not query:
                return ToolResult("Error: 'query' is required for search action.", is_error=True)
            try:
                results = collection.query(
                    query_texts=[query],
                    n_results=min(n_results, collection.count() or 1),
                )
                docs = results.get("documents", [[]])[0]
                ids = results.get("ids", [[]])[0]
                if not docs:
                    return ToolResult(f"No memories found for: {query}", is_error=False)

                lines = [f"Memory search results for: {query}\n"]
                for i, (doc, mid) in enumerate(zip(docs, ids), 1):
                    lines.append(f"[{i}] ID: {mid}")
                    lines.append(f"    {doc[:500]}")
                    lines.append("")
                return ToolResult("\n".join(lines), is_error=False)
            except Exception as e:
                return ToolResult(f"Error searching memory: {e}", is_error=True)

        elif action == "list":
            try:
                result = collection.get()
                docs = result.get("documents", [])
                ids = result.get("ids", [])
                if not docs:
                    return ToolResult("No memories stored yet.", is_error=False)
                lines = [f"All memories ({len(docs)} total):\n"]
                for mid, doc in zip(ids, docs):
                    lines.append(f"  [{mid}] {doc[:150]}{'...' if len(doc) > 150 else ''}")
                return ToolResult("\n".join(lines), is_error=False)
            except Exception as e:
                return ToolResult(f"Error listing memories: {e}", is_error=True)

        elif action == "delete":
            if not memory_id:
                return ToolResult("Error: 'memory_id' is required for delete action.", is_error=True)
            try:
                collection.delete(ids=[memory_id])
                return ToolResult(f"✓ Memory {memory_id} deleted.", is_error=False)
            except Exception as e:
                return ToolResult(f"Error deleting memory: {e}", is_error=True)

        else:
            return ToolResult(
                f"Error: Unknown action '{action}'. Use: store, search, list, delete.",
                is_error=True,
            )
