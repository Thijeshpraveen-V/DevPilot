"""
agent/tools/search_code.py
──────────────────────────
Code search tool — search_code.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.tools.base import BaseTool, ToolResult, ToolSchema

if TYPE_CHECKING:
    from agent.config import Config


class SearchCodeTool(BaseTool):
    """Search for patterns across files in the working directory."""

    def __init__(self, config: "Config") -> None:
        self._config = config

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="search_code",
            description=(
                "Search for a pattern (regex supported) across files in the project. "
                "Returns matching lines with file paths and line numbers. "
                "Use this to find function definitions, usages, imports, etc."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex or literal pattern to search for.",
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "Glob pattern to filter files (e.g. '*.py', '*.ts').",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "Lines of context around each match (default: 2).",
                        "default": 2,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of matches to return (default: 50).",
                        "default": 50,
                    },
                },
                "required": ["pattern"],
            },
            required=["pattern"],
            sprint="Sprint 1",
        )

    async def execute(  # type: ignore[override]
        self,
        pattern: str,
        file_pattern: str | None = None,
        context_lines: int = 2,
        max_results: int = 50,
    ) -> ToolResult:
        if not pattern:
            return ToolResult("Error: 'pattern' parameter is required.", is_error=True)

        search_path = Path(self._config.workdir)
        glob = file_pattern or "*.*"

        try:
            # Use ripgrep if available
            rg_cmd = ["rg", "--no-heading", "--line-number", f"-C{context_lines}"]
            if file_pattern:
                rg_cmd.extend(["-g", file_pattern])
            rg_cmd.extend([pattern, str(search_path)])

            rg_result = subprocess.run(
                rg_cmd,
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
            )
            if rg_result.returncode in (0, 1):   # 0=matches found, 1=no matches
                output = rg_result.stdout.strip() or f"No matches for '{pattern}'."
                # Optionally cap output
                lines = output.splitlines()
                if len(lines) > max_results * (context_lines * 2 + 1):
                    output = "\n".join(lines[:max_results * (context_lines * 2 + 1)]) + "\n... (truncated)"
                return ToolResult(output, is_error=False)
        except (FileNotFoundError, OSError):
            pass  # ripgrep not available, fall back

        # Pure-Python fallback: glob + line scan (simple, no context)
        matches: list[str] = []
        for file_path in sorted(search_path.rglob(glob)):
            if not file_path.is_file():
                continue
            try:
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
                for i, line in enumerate(lines, start=1):
                    if pattern.lower() in line.lower():
                        matches.append(f"{file_path}:{i}: {line.rstrip()}")
            except OSError:
                continue

        if not matches:
            return ToolResult(f"No matches for '{pattern}' in {search_path}.", is_error=False)

        output = "\n".join(matches[:max_results])
        if len(matches) > max_results:
            output += f"\n... (truncated {len(matches) - max_results} more matches)"
            
        return ToolResult(output, is_error=False)
