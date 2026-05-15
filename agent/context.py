"""
agent/context.py
────────────────
RepoContext — tracks which files the model has read this session,
their content hashes, and the repo structure snapshot.

Injected into every system prompt so the model always knows:
  - What it has already read (no redundant re-reads)
  - Whether a file has changed since it last read it
  - The top-level directory structure of the project
"""

from __future__ import annotations

import hashlib
import ast
import re
from pathlib import Path


class RepoContext:
    """
    Lightweight repo awareness tracker.

    The loop calls record_read() after every successful read_file call.
    WriteFileTool calls record_write() after every successful write.
    build_context_block() returns a compact text block injected into
    the system prompt at the start of every chat() call.
    """

    def __init__(self, workdir: str) -> None:
        self._workdir = Path(workdir).resolve()
        # path (relative str) -> content hash at last read
        self._read_files: dict[str, str] = {}
        # path (relative str) -> content hash at write time
        self._written_files: dict[str, str] = {}

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_read(self, path: str, content: str) -> None:
        """Called by ReadFileTool after a successful read."""
        rel = self._rel(path)
        self._read_files[rel] = self._hash(content)

    def record_write(self, path: str, content: str) -> None:
        """Called by WriteFileTool after a successful write."""
        rel = self._rel(path)
        self._written_files[rel] = self._hash(content)
        # Also update read cache so model knows current on-disk state
        self._read_files[rel] = self._hash(content)

    # ── Stale detection ───────────────────────────────────────────────────────

    def is_stale(self, path: str) -> bool:
        """
        Returns True if the file on disk has changed since last read.
        Used to hint the model it should re-read before writing.
        """
        rel = self._rel(path)
        if rel not in self._read_files:
            return False
        try:
            full = self._workdir / rel
            current = self._hash(full.read_text(encoding="utf-8", errors="replace"))
            return current != self._read_files[rel]
        except OSError:
            return False

    # ── Context block for system prompt ──────────────────────────────────────

    def build_context_block(self) -> str:
        """
        Returns a compact text block describing current repo awareness.
        Injected into the system prompt on every chat() call.
        """
        lines: list[str] = []

        if self._read_files:
            lines.append("Files you have already read this session (do not re-read unless stale):")
            for rel in sorted(self._read_files):
                stale = self.is_stale(rel)
                tag = "  ⚠ MODIFIED ON DISK — re-read before editing" if stale else ""
                lines.append(f"  • {rel}{tag}")
        else:
            lines.append("You have not read any files yet this session.")

        if self._written_files:
            lines.append("\nFiles you have written this session:")
            for rel in sorted(self._written_files):
                lines.append(f"  • {rel}")

        tree = self._build_project_tree()
        if tree:
            lines.append(f"\nProject root ({self._workdir.name}/):")
            lines.extend(f"  {entry}" for entry in tree)

        return "\n".join(lines)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _rel(self, path: str) -> str:
        p = Path(path)
        if p.is_absolute():
            try:
                return str(p.relative_to(self._workdir))
            except ValueError:
                return path
        return str(p)

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()

    def _extract_signatures(self, path: Path) -> list[str]:
        rel = self._rel(str(path))
        if rel in self._read_files:
            return []

        sigs = []
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            if path.suffix == ".py":
                tree = ast.parse(content)
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        sigs.append(f"    def {node.name}(...)")
                    elif isinstance(node, ast.ClassDef):
                        sigs.append(f"    class {node.name}:")
                        for sub_node in node.body:
                            if isinstance(sub_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                sigs.append(f"        def {sub_node.name}(...)")
            elif path.suffix in (".js", ".ts"):
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("class ") or line.startswith("export class ") or \
                       line.startswith("function ") or line.startswith("export function "):
                        sigs.append(f"    {line}")
        except Exception:
            pass
        return sigs

    def _build_project_tree(self, max_entries: int = 200) -> list[str]:
        entries: list[str] = []
        ignores = {
            ".git", "node_modules", ".venv", "__pycache__", "dist", 
            "build", ".next", ".tox", "coverage_html_report", ".devpilot_sessions"
        }

        def _traverse(directory: Path, prefix: str = "") -> None:
            if len(entries) >= max_entries:
                return

            try:
                for item in sorted(directory.iterdir()):
                    if item.name.startswith(".") and item.name not in (".env", ".gitignore", ".github"):
                        continue
                    if item.name in ignores or item.name.endswith(".egg-info"):
                        continue

                    if item.is_dir():
                        entries.append(f"{prefix}📁 {item.name}/")
                        _traverse(item, prefix + "  ")
                    else:
                        entries.append(f"{prefix}📄 {item.name}")
                        if item.suffix in (".py", ".js", ".ts"):
                            sigs = self._extract_signatures(item)
                            for sig in sigs:
                                entries.append(f"{prefix}{sig}")

                    if len(entries) >= max_entries:
                        entries.append("… (truncated to ~200 items for context size)")
                        break
            except OSError:
                pass

        _traverse(self._workdir)
        return entries
