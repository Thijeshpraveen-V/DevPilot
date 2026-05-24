"""
agent/mcp_client.py
───────────────────
MCP Client Integration (Sprint 3).
Connects to servers defined in mcp_servers.json, discovers tools,
and registers them into the ToolRegistry.
"""

import json
import asyncio
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import TextContent

from agent.tools import ToolRegistry, ToolResult
from agent.ui import UI


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
        """Connect to all servers in mcp_servers.json and register tools."""
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
            server_items = servers.items()
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

            ready_event = asyncio.Event()
            events.append(ready_event)
            task = asyncio.create_task(
                self._run_server(name, command, args, server_config.get("env"), registry, ready_event)
            )
            self._tasks.append(task)

        if events:
            await asyncio.gather(*(e.wait() for e in events))

    async def close(self) -> None:
        """Close all connections."""
        for task in self._tasks:
            task.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            
        self.sessions.clear()
        self._tasks.clear()
