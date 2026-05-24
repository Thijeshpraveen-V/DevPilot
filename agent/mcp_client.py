"""
agent/mcp_client.py
───────────────────
MCP Client Integration (Sprint 3).
Connects to servers defined in mcp_servers.json, discovers tools,
and registers them into the ToolRegistry.
"""

import json
import asyncio
import shutil
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import TextContent

from agent.tools import ToolRegistry, ToolResult
from agent.ui import UI


# ── Install hints for common MCP server commands ─────────────────────────────

_INSTALL_HINTS: dict[str, str] = {
    "npx":    "Node.js is not installed or not on PATH.\n"
              "  → Install it from https://nodejs.org/ (LTS version recommended)\n"
              "  → After installing, restart your terminal and try again.",
    "node":   "Node.js is not installed or not on PATH.\n"
              "  → Install it from https://nodejs.org/",
    "uvx":    "'uvx' (uv tool runner) is not installed.\n"
              "  → Install uv: https://docs.astral.sh/uv/getting-started/installation/",
    "docker": "Docker is not installed or not running.\n"
              "  → Install Docker Desktop from https://www.docker.com/products/docker-desktop/",
    "python": "Python is not on PATH (unexpected — DevPilot itself runs on Python).",
    "python3":"Python 3 is not on PATH.",
}


def _check_command(command: str, server_name: str) -> bool:
    """
    Return True if `command` is available on PATH.
    If not, print a clear, actionable error and return False.
    """
    if shutil.which(command) is not None:
        return True

    hint = _INSTALL_HINTS.get(command.lower(),
        f"'{command}' was not found on your PATH.\n"
        f"  → Make sure it is installed and your terminal can see it."
    )
    UI.print_error(
        f"MCP server '{server_name}' requires '{command}' but it was not found.\n"
        f"  {hint}\n"
        f"  This MCP server will be skipped. Disable it in mcp_servers.json to suppress this message."
    )
    return False


class MCPManager:
    """Manages connections to multiple MCP servers."""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.sessions: dict[str, ClientSession] = {}
        self._tasks: list[asyncio.Task] = []

    async def _run_server(
        self, 
        name: str, 
        command: str, 
        args: list[str], 
        env: dict | None, 
        registry: ToolRegistry, 
        ready_event: asyncio.Event
    ) -> None:
        try:
            server_params = StdioServerParameters(command=command, args=args, env=env)
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.sessions[name] = session

                    # Fetch and register tools
                    tools_response = await session.list_tools()
                    for mcp_tool in tools_response.tools:
                        canonical_schema = {
                            "name": mcp_tool.name,
                            "description": mcp_tool.description or "",
                            "input_schema": mcp_tool.inputSchema,
                            "_mcp_server_id": name,
                        }

                        def make_executor(session_ref: ClientSession, tool_name: str):
                            async def _executor(tool_input: dict) -> ToolResult:
                                try:
                                    result = await session_ref.call_tool(tool_name, tool_input)
                                    text_contents = [c.text for c in result.content if isinstance(c, TextContent)]
                                    output = "\n".join(text_contents)
                                    return ToolResult(output, is_error=result.isError)
                                except Exception as e:
                                    return ToolResult(f"MCP execution error: {e}", is_error=True)
                            return _executor

                        registry.register_mcp_tool(canonical_schema, make_executor(session, mcp_tool.name))

                    UI.print_info(f"Connected to MCP server: {name} ({len(tools_response.tools)} tools)")
                    ready_event.set()

                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        pass
        except Exception as e:
            UI.print_error(f"Failed to connect to MCP server '{name}': {e}")
            registry.deregister_mcp_tools(name)
        finally:
            ready_event.set()

    async def connect_all(self, registry: ToolRegistry) -> None:
        """Connect to all servers in mcp_servers.json and register tools.
        
        Uses a non-blocking approach: MCP servers connect in background tasks.
        Startup waits at most MCP_CONNECT_TIMEOUT seconds total so a slow
        npx download never freezes DevPilot at launch.
        """
        MCP_CONNECT_TIMEOUT = 2.0  # seconds — enough for cached/local servers; slow npx downloads skip

        if not self.config_path.exists():
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                servers = data.get("mcpServers", data.get("servers", {}))
        except (json.JSONDecodeError, OSError) as e:
            UI.print_error(f"Failed to read mcp_servers.json: {e}")
            return

        if isinstance(servers, dict):
            server_items = list(servers.items())
        else:
            server_items = [(s.get("name", f"server_{i}"), s) for i, s in enumerate(servers)]

        events = []
        for name, server_config in server_items:
            if server_config.get("enabled", True) is False:
                continue

            command = server_config.get("command")
            args = server_config.get("args", [])

            if not command:
                UI.print_error(f"MCP server '{name}' missing 'command'. Skipping.")
                continue

            # Pre-flight: make sure the binary is actually installed
            if not _check_command(command, name):
                continue

            ready_event = asyncio.Event()
            events.append(ready_event)
            task = asyncio.create_task(
                self._run_server(name, command, args, server_config.get("env"), registry, ready_event)
            )
            self._tasks.append(task)

        if events:
            # Wait for all servers to be ready, but cap total wait time.
            # If any server is slow (e.g. npx downloading a package), DevPilot
            # still starts promptly and the server connects in the background.
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(e.wait() for e in events)),
                    timeout=MCP_CONNECT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                pending = sum(1 for e in events if not e.is_set())
                UI.print_info(
                    f"{pending} MCP server(s) still connecting in background "
                    f"(took >{MCP_CONNECT_TIMEOUT:.0f}s). DevPilot is ready now."
                )


    async def close(self) -> None:
        """Close all connections."""
        for task in self._tasks:
            task.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            
        self.sessions.clear()
        self._tasks.clear()
