"""
agent/tools/registry.py
───────────────────────
ToolRegistry and PermissionGuard.

Improvements:
  - PermissionGuard: session-level "allow all" whitelist so the model
    isn't interrupted on every destructive call after first approval
  - ToolRegistry: accepts RepoContext and passes it to fs tools
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from agent.tools.base import BaseTool, ToolResult
from agent.ui import UI

if TYPE_CHECKING:
    from agent.config import Config
    from agent.context import RepoContext


class PermissionGuard:
    """
    Intercepts calls to destructive tools and prompts the user.

    Three response modes:
      y / Enter  → allow this one call
      a          → allow all remaining calls this session (whitelist)
      n          → deny this call

    In --no-confirm mode all calls are allowed without prompting.
    """

    def __init__(self, no_confirm: bool = False) -> None:
        self.no_confirm = no_confirm
        self._allow_all = False          # set to True when user types 'a'
        self._whitelisted: set[str] = set()  # per-tool whitelist (future extension)

    def allow_all_for_session(self) -> None:
        """Programmatically grant session-wide permission (used by tests / CI)."""
        self._allow_all = True

    async def check(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        if self.no_confirm or self._allow_all:
            return True

        # Build a human-readable preview
        preview_lines: list[str] = []
        if tool_name == "write_file":
            preview_lines.append(f"Write to: {tool_input.get('path', '?')}")
        elif tool_name == "edit_file":
            preview_lines.append(f"Edit file: {tool_input.get('path', '?')}")
        elif tool_name == "run_bash":
            preview_lines.append(f"Run: {tool_input.get('command', '?')}")
        elif tool_name == "git_commit":
            preview_lines.append(
                f"Git Commit: {tool_input.get('message', '')}\n  Files: {', '.join(tool_input.get('paths', []))}"
            )
        else:
            for k, v in tool_input.items():
                preview_lines.append(f"  {k}: {v}")

        choice = await UI.ask_permission(tool_name, preview_lines)

        if choice in ("y", "yes", ""):
            return True
        if choice in ("a", "all"):
            self._allow_all = True
            UI.print_info("Permission granted for all remaining operations this session.")
            return True
        if choice in ("n", "no"):
            return False
        
        return False


@dataclass
class ToolRegistry:
    """
    Unified store of tool schemas and executors.
    Manages both built-in OOP tools and dynamic MCP/A2A tools.
    """

    _config: "Config"
    _context: "RepoContext | None" = field(default=None)
    _tools: dict[str, BaseTool] = field(default_factory=dict)
    _mcp_schemas: list[dict[str, Any]] = field(default_factory=list)
    _mcp_executors: dict[str, Callable[[dict[str, Any]], Awaitable[ToolResult]]] = field(
        default_factory=dict
    )
    _guard: PermissionGuard = field(init=False)

    def __post_init__(self) -> None:
        self._guard = PermissionGuard(no_confirm=self._config.no_confirm)
        self._register_builtins()

    def _register_builtins(self) -> None:
        """Register all default native tools."""
        # All heavy tool imports are lazy here — keeps startup fast.
        # GitPython, tavily, shell, and other deps only load when the
        # registry is instantiated inside main_async(), not at module import time.
        from agent.tools.fs import ListFilesTool, ReadFileTool, WriteFileTool, EditFileTool
        from agent.tools.shell import RunBashTool
        from agent.tools.search_code import SearchCodeTool
        from agent.tools.git_ops import GitStatusTool, GitCommitTool
        from agent.tools.doc_gen import DocGenTool
        from agent.tools.diagram import DiagramTool

        tools: list[BaseTool] = [
            ReadFileTool(self._config, self._context),
            WriteFileTool(self._config, self._context),
            EditFileTool(self._config, self._context),
            ListFilesTool(self._config, self._context),
            RunBashTool(self._config),
            SearchCodeTool(self._config),
            GitStatusTool(self._config),
            GitCommitTool(self._config),
            DocGenTool(self._config),
            DiagramTool(self._config),
        ]

        if self._config.web_search_enabled:
            from agent.tools.web_search import WebSearchTool
            tools.append(WebSearchTool(self._config))

        if self._config.a2a_enabled:
            from agent.tools.a2a import A2ATool
            tools.append(A2ATool(self._config))

        for t in tools:
            self._tools[t.name] = t

    # ── Tool management ───────────────────────────────────────────────────────

    def register_tool(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    # ── Schema access ─────────────────────────────────────────────────────────

    @property
    def schemas(self) -> list[dict[str, Any]]:
        seen_names = set()
        final_schemas = []

        # Add native tools first (they take precedence)
        for t in self._tools.values():
            if t.schema.name not in seen_names:
                final_schemas.append({
                    "name": t.schema.name,
                    "description": t.schema.description,
                    "input_schema": t.schema.parameters,
                })
                seen_names.add(t.schema.name)
        
        # Add MCP tools if they don't collide
        for s in self._mcp_schemas:
            if s["name"] not in seen_names:
                final_schemas.append({
                    "name": s["name"],
                    "description": s["description"],
                    "input_schema": s["input_schema"],
                })
                seen_names.add(s["name"])
                
        return final_schemas

    def has_tool(self, name: str) -> bool:
        return name in self._tools or name in self._mcp_executors

    # ── Execution ─────────────────────────────────────────────────────────────

    async def execute(self, tool_name: str, tool_input: dict[str, Any]) -> ToolResult:
        if not self.has_tool(tool_name):
            available = list(self._tools.keys()) + list(self._mcp_executors.keys())
            return ToolResult(
                f"Error: Unknown tool '{tool_name}'. Available: {', '.join(available)}",
                is_error=True,
            )

        is_destructive = (
            self._tools[tool_name].is_destructive
            if tool_name in self._tools
            else False
        )

        if is_destructive:
            allowed = await self._guard.check(tool_name, tool_input)
            if not allowed:
                return ToolResult(f"Operation cancelled by user: {tool_name}", is_error=False)

        try:
            if tool_name in self._tools:
                return await self._tools[tool_name].execute(**tool_input)
            else:
                return await self._mcp_executors[tool_name](tool_input)
        except Exception as e:
            return ToolResult(f"Unexpected error in {tool_name}: {e}", is_error=True)

    # ── MCP extension ─────────────────────────────────────────────────────────

    def register_mcp_tool(
        self,
        schema: dict[str, Any],
        executor: Callable[[dict[str, Any]], Awaitable[ToolResult]],
    ) -> None:
        name: str = schema["name"]
        self._mcp_schemas.append(schema)
        self._mcp_executors[name] = executor

    def deregister_mcp_tools(self, server_id: str) -> None:
        to_remove = [s["name"] for s in self._mcp_schemas if s.get("_mcp_server_id") == server_id]
        self._mcp_schemas = [s for s in self._mcp_schemas if s.get("_mcp_server_id") != server_id]
        for name in to_remove:
            self._mcp_executors.pop(name, None)
