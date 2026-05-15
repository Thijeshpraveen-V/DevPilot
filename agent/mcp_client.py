"""
agent/mcp_client.py
───────────────────
MCP Client Integration (Sprint 3).
Connects to servers defined in mcp_servers.json, discovers tools,
and registers them into the ToolRegistry.
"""

import json
from contextlib import AsyncExitStack
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
        self.exit_stack = AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}

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

        # Handle both list of dicts and dict of dicts formats for mcp_servers.json
        if isinstance(servers, dict):
            # In official MCP config format, it's a dict mapping name to config
            server_items = servers.items()
        else:
            # Fallback if it's a list
            server_items = [(s.get("name", f"server_{i}"), s) for i, s in enumerate(servers)]

        for name, server_config in server_items:
            if server_config.get("enabled", True) is False:
                continue
            
            command = server_config.get("command")
            args = server_config.get("args", [])

            if not command:
                UI.print_error(f"MCP server '{name}' missing 'command'. Skipping.")
                continue

            try:
                server_params = StdioServerParameters(command=command, args=args, env=server_config.get("env"))
                stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
                read, write = stdio_transport
                session = await self.exit_stack.enter_async_context(ClientSession(read, write))
                await session.initialize()

                self.sessions[name] = session

                # Fetch and register tools
                tools_response = await session.list_tools()
                for mcp_tool in tools_response.tools:
                    # Convert to canonical schema format
                    canonical_schema = {
                        "name": mcp_tool.name,
                        "description": mcp_tool.description or "",
                        "input_schema": mcp_tool.inputSchema,
                        "_mcp_server_id": name,
                    }

                    # Create closure for execution
                    def make_executor(session_ref: ClientSession, tool_name: str):
                        async def _executor(tool_input: dict) -> ToolResult:
                            try:
                                result = await session_ref.call_tool(tool_name, tool_input)
                                # Flatten result text
                                text_contents = [c.text for c in result.content if isinstance(c, TextContent)]
                                output = "\n".join(text_contents)
                                return ToolResult(output, is_error=result.isError)
                            except Exception as e:
                                return ToolResult(f"MCP execution error: {e}", is_error=True)
                        return _executor

                    registry.register_mcp_tool(canonical_schema, make_executor(session, mcp_tool.name))

                UI.print_info(f"Connected to MCP server: {name} ({len(tools_response.tools)} tools)")
            except Exception as e:
                UI.print_error(f"Failed to connect to MCP server '{name}': {e}")
                registry.deregister_mcp_tools(name)

    async def close(self) -> None:
        """Close all connections."""
        await self.exit_stack.aclose()
        self.sessions.clear()
