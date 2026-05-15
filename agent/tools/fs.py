"""
agent/tools/fs.py
─────────────────
Filesystem tools — read_file, write_file, list_files.

Improvements over original:
  - ReadFileTool: records reads into RepoContext for awareness tracking
  - WriteFileTool: computes and displays a syntax-highlighted unified diff
    before writing; records writes into RepoContext
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.tools.base import BaseTool, ToolResult, ToolSchema

if TYPE_CHECKING:
    from agent.config import Config
    from agent.context import RepoContext


def _safe_path(workdir: str, path: str) -> Path:
    """
    Resolve path relative to workdir and ensure it doesn't escape.
    Raises ValueError if the resolved path is outside workdir.
    """
    workdir_path = Path(workdir).resolve()
    candidate = Path(path) if Path(path).is_absolute() else workdir_path / path
    resolved = candidate.resolve()
    if not str(resolved).startswith(str(workdir_path)):
        raise ValueError(f"Path '{path}' escapes the working directory.")
    return resolved


def _unified_diff(old_text: str, new_text: str, path: str) -> str:
    """Return a unified diff string between old and new content."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    return "".join(diff)


class ReadFileTool(BaseTool):
    """Read any file inside the working directory."""

    def __init__(self, config: "Config", context: "RepoContext | None" = None) -> None:
        self._workdir = config.workdir
        self._context = context

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="read_file",
            description=(
                "Read the contents of a file. Path is relative to the working directory. "
                "Always read a file before modifying it. "
                "Check the session context — if the file is already listed as read and not "
                "marked stale, you can rely on your memory of it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file (e.g. 'src/main.py').",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Optional 1-based start line for partial reads.",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Optional 1-based end line for partial reads.",
                    },
                },
                "required": ["path"],
            },
            required=["path"],
            sprint="Sprint 1",
        )

    async def execute(  # type: ignore[override]
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> ToolResult:
        try:
            safe_p = _safe_path(self._workdir, path)
            if not safe_p.exists():
                return ToolResult(f"Error: File not found: {path}", is_error=True)
            if not safe_p.is_file():
                return ToolResult(f"Error: Path is not a file: {path}", is_error=True)

            content = safe_p.read_text(encoding="utf-8", errors="replace")

            # Record full content into context regardless of slice
            if self._context is not None:
                self._context.record_read(path, content)

            lines = content.splitlines()
            start_idx = max(0, start_line - 1) if start_line else 0
            end_idx = min(len(lines), end_line) if end_line else len(lines)
            sliced = lines[start_idx:end_idx]

            numbered = "\n".join(
                f"{i + start_idx + 1:>4}: {line}" for i, line in enumerate(sliced)
            )
            return ToolResult(
                f"Contents of {path} (lines {start_idx + 1}-{end_idx}):\n\n{numbered}",
                is_error=False,
            )
        except Exception as e:
            return ToolResult(f"Error reading {path}: {e}", is_error=True)


class WriteFileTool(BaseTool):
    """Write or overwrite a file. Renders a diff and asks permission before writing."""

    def __init__(self, config: "Config", context: "RepoContext | None" = None) -> None:
        self._config = config
        self._context = context

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="write_file",
            description=(
                "Write content to a file, creating it if it doesn't exist or "
                "overwriting it if it does. Always shows a diff before writing. "
                "CRITICAL: You MUST provide the ENTIRE full file content. "
                "NEVER use placeholders like '... existing code ...' or write short stubs. "
                "If modifying an existing file, you must include all unmodified lines exactly as they were."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full new content of the file.",
                    },
                },
                "required": ["path", "content"],
            },
            required=["path", "content"],
            is_destructive=True,
            sprint="Sprint 1",
        )

    async def execute(self, path: str, content: str) -> ToolResult:  # type: ignore[override]
        try:
            safe_p = _safe_path(self._config.workdir, path)

            # Compute and display diff before writing
            if safe_p.exists() and safe_p.is_file():
                old_content = safe_p.read_text(encoding="utf-8", errors="replace")
                diff = _unified_diff(old_content, content, path)
                if diff:
                    from agent.ui import UI
                    UI.print_diff(path, diff)
                else:
                    from agent.ui import UI
                    UI.print_info(f"No changes to {path} (content identical).")
                    return ToolResult(f"No changes written — content of {path} is identical.", is_error=False)
            else:
                # New file — show full content as a creation diff
                from agent.ui import UI
                diff = _unified_diff("", content, path)
                UI.print_diff(path, diff, is_new=True)

            safe_p.parent.mkdir(parents=True, exist_ok=True)
            safe_p.write_text(content, encoding="utf-8")

            # Record write in context
            if self._context is not None:
                self._context.record_write(path, content)

            return ToolResult(f"✓ Written {len(content)} characters to {path}", is_error=False)
        except Exception as e:
            return ToolResult(f"Error writing {path}: {e}", is_error=True)


class ListFilesTool(BaseTool):
    """List files and directories in the working directory."""

    def __init__(self, config: "Config", context: "RepoContext | None" = None) -> None:
        self._workdir = config.workdir

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="list_files",
            description=(
                "List files and directories. Use before read or write to "
                "confirm paths. Defaults to the working directory root."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to list (default: '.').",
                        "default": ".",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "If true, list all files recursively.",
                        "default": False,
                    },
                },
                "required": [],
            },
            sprint="Sprint 1",
        )

    async def execute(self, path: str = ".", recursive: bool = False) -> ToolResult:  # type: ignore[override]
        try:
            safe_p = _safe_path(self._workdir, path)
            if not safe_p.exists():
                return ToolResult(f"Error: Path not found: {path}", is_error=True)
            if not safe_p.is_dir():
                return ToolResult(f"Error: Not a directory: {path}", is_error=True)

            entries: list[str] = []

            def _scan(directory: Path, prefix: str = "") -> None:
                for entry in sorted(directory.iterdir()):
                    if entry.name.startswith(".") and entry.name != ".env":
                        continue
                    rel_path = prefix + entry.name
                    if entry.is_dir():
                        entries.append(f"  📁 {rel_path}/")
                        if recursive:
                            _scan(entry, prefix=rel_path + "/")
                    else:
                        size = entry.stat().st_size
                        entries.append(f"  📄 {rel_path}  ({size:,} bytes)")

            _scan(safe_p)

            if not entries:
                return ToolResult(f"Directory {path} is empty.", is_error=False)

            return ToolResult(f"Contents of {path}:\n" + "\n".join(entries), is_error=False)

        except Exception as e:
            return ToolResult(f"Error listing {path}: {e}", is_error=True)
