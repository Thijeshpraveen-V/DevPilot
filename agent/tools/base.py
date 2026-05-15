"""
agent/tools/base.py
───────────────────
Base interfaces for DevPilot tools.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ToolResult:
    """Returned by every tool executor."""
    output: str       # String content to send back to the model
    is_error: bool    # True if the tool raised an error or was cancelled


@dataclass
class ToolSchema:
    """Portable tool schema — provider-agnostic."""
    name: str
    description: str
    parameters: dict[str, Any]           # JSON Schema object for input
    required: list[str] = field(default_factory=list)
    is_destructive: bool = False         # If True, permission guard prompts
    sprint: str = "Sprint 1"            # Implemented in which sprint


class BaseTool(ABC):
    """Abstract base class for all DevPilot tools."""

    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """Return the tool's JSON schema for the model."""

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute the tool with the arguments the model provided.
        Returns a ToolResult containing output and error status.
        """

    @property
    def name(self) -> str:
        return self.schema.name

    @property
    def is_destructive(self) -> bool:
        return self.schema.is_destructive
