"""
agent/tools/semantic_search.py
──────────────────────────────
Semantic search tool using ChromaDB + Sentence Transformers (optional RAG deps).
If deps are not installed, returns a graceful not-available message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent.tools.base import BaseTool, ToolResult, ToolSchema

if TYPE_CHECKING:
    from agent.config import Config
    from agent.context import RepoContext


class SemanticSearchTool(BaseTool):
    """Query the codebase by meaning rather than exact keyword match."""

    def __init__(self, config: "Config", context: "RepoContext | None" = None) -> None:
        self._config = config
        self._context = context

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="semantic_search",
            description=(
                "Search the codebase by *meaning* rather than exact keyword. "
                "Ask questions like 'where do we handle auth errors' or "
                "'how are tool results formatted' — returns the most relevant "
                "code chunks even if they contain none of the exact words. "
                "Use this before search_code when you don't know the exact symbol name. "
                "Requires chromadb and sentence-transformers to be installed."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A natural language description of what you're looking for.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 5, max: 20).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            required=["query"],
            sprint="Sprint 3",
        )

    async def execute(self, query: str, limit: int = 5) -> ToolResult:  # type: ignore[override]
        if not query.strip():
            return ToolResult("Error: query must not be empty.", is_error=True)

        if self._context is None or self._context.vector_store is None:
            return ToolResult(
                "Semantic search is not available — install chromadb and "
                "sentence-transformers to enable it:\n\n"
                "  pip install chromadb sentence-transformers",
                is_error=False,
            )

        limit = max(1, min(limit, 20))

        try:
            results = self._context.vector_store.search(query, n_results=limit)
        except Exception as e:
            return ToolResult(f"Semantic search error: {e}", is_error=True)

        if not results:
            return ToolResult("No results found for your query.", is_error=False)

        lines: list[str] = [f'Semantic search results for: "{query}"\n']
        for i, r in enumerate(results, 1):
            path = r.get("path", "?")
            chunk_id = r.get("chunk_id", "?")
            distance = r.get("distance", 0.0)
            snippet = r.get("snippet", "").strip()
            # Truncate long snippets
            if len(snippet) > 500:
                snippet = snippet[:500] + "\n  ..."
            # Indent snippet lines
            indented_snippet = "\n".join(f"   {line}" for line in snippet.splitlines())
            lines.append(
                f"{i}. {path} — {chunk_id} (distance: {distance:.2f})\n"
                f"{indented_snippet}\n"
            )

        return ToolResult("\n".join(lines), is_error=False)
