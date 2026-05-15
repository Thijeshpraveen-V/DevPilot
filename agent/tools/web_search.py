"""
agent/tools/web_search.py
─────────────────────────
Web search tool using Tavily API.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from agent.tools.base import BaseTool, ToolResult, ToolSchema

if TYPE_CHECKING:
    from agent.config import Config


class WebSearchTool(BaseTool):
    """Search the web for current information using the Tavily API."""

    def __init__(self, config: "Config") -> None:
        self._config = config

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_search",
            description=(
                "Search the web for current information. Use when you need up-to-date "
                "documentation, library versions, recent news, or anything not in your "
                "training data. Returns a concise summary with source URLs."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max number of results to return (default: 5).",
                        "default": 5,
                    },
                    "include_raw_content": {
                        "type": "boolean",
                        "description": "If true, include raw page content for deeper analysis.",
                        "default": False,
                    },
                },
                "required": ["query"],
            },
            required=["query"],
            sprint="Sprint 2",
        )

    async def execute(  # type: ignore[override]
        self,
        query: str,
        max_results: int = 5,
        include_raw_content: bool = False,
    ) -> ToolResult:
        if not query:
            return ToolResult("Error: 'query' parameter is required.", is_error=True)

        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return ToolResult(
                "Error: TAVILY_API_KEY environment variable is not set. "
                "Get a free key at https://tavily.com and add it to your .env.",
                is_error=True,
            )

        try:
            from tavily import TavilyClient  # type: ignore[import]
            client = TavilyClient(api_key=api_key)

            response = client.search(
                query=query,
                max_results=max_results,
                include_raw_content=include_raw_content,
            )

            results = response.get("results", [])
            if not results:
                return ToolResult(f"No web results found for: {query}", is_error=False)

            lines: list[str] = [f"Web search results for: {query}\n"]
            for i, r in enumerate(results, 1):
                lines.append(f"[{i}] {r.get('title', 'Untitled')}")
                lines.append(f"    URL: {r.get('url', '')}")
                lines.append(f"    {r.get('content', '').strip()[:400]}")
                if include_raw_content and r.get("raw_content"):
                    lines.append(f"\n    Full content:\n{r['raw_content'][:2000]}")
                lines.append("")

            return ToolResult("\n".join(lines), is_error=False)

        except ImportError:
            return ToolResult(
                "Error: tavily-python is not installed. Run: pip install tavily-python",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(f"Web search error: {e}", is_error=True)
