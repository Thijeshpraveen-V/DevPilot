"""
agent/tools/a2a.py
──────────────────
A2A delegation tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.a2a_client import delegate_task_to_peer
from agent.tools.base import BaseTool, ToolResult, ToolSchema

if TYPE_CHECKING:
    from agent.config import Config


class A2ATool(BaseTool):
    """Delegate tasks to peer agents."""

    def __init__(self, config: "Config") -> None:
        self._config = config

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="a2a_delegate_task",
            description=(
                "Delegate a subtask to an external A2A (Agent-to-Agent) peer. "
                "Use this when you need help from a specialist agent or another node. "
                "Provide the base URL of the peer agent and the task prompt."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "peer_url": {
                        "type": "string",
                        "description": "Base URL of the peer agent (e.g., http://localhost:8001)"
                    },
                    "prompt": {
                        "type": "string",
                        "description": "The coding task or instruction to delegate."
                    },
                    "token": {
                        "type": "string",
                        "description": "Optional Bearer token if the peer requires authentication."
                    }
                },
                "required": ["peer_url", "prompt"]
            },
            required=["peer_url", "prompt"],
            sprint="Sprint 4",
        )

    async def execute(self, peer_url: str, prompt: str, token: str | None = None) -> ToolResult:  # type: ignore[override]
        return await delegate_task_to_peer(peer_url, prompt, token)
