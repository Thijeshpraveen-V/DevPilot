"""
agent/providers/base.py
────────────────────────
Abstract interface and shared data types for all model providers.

The agentic loop works exclusively with these types — it has zero knowledge
of whether Anthropic, OpenAI, or any other provider is underneath.

─── Canonical message format (stored in conversation history) ───────────────

  User text message:
    {"role": "user", "content": "some text"}

  User message carrying tool results:
    {"role": "user", "content": [
        {
          "type":        "tool_result",
          "tool_use_id": "<id that matches the tool_use block>",
          "content":     "<tool output string>",
          "is_error":    False
        }
    ]}

  Assistant message (text and/or tool calls):
    {"role": "assistant", "content": [
        {"type": "text",     "text": "..."},
        {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
    ]}

─── Canonical tool schema format (fed to the provider) ──────────────────────

  {
    "name":         "tool_name",
    "description":  "What the tool does.",
    "input_schema": {          ← Anthropic-style JSON Schema
      "type": "object",
      "properties": { ... },
      "required":   [ ... ]
    }
  }

  Providers that use a different schema format (e.g., OpenAI uses
  "function.parameters") are responsible for converting internally.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# ── Shared data types ─────────────────────────────────────────────────────────

@dataclass
class ToolUseBlock:
    """A single tool invocation requested by the model."""
    id: str       # Unique ID — used to pair with the tool_result
    name: str     # Must match a tool name in the registry
    input: dict   # Arguments the model wants to pass to the tool


@dataclass
class ProviderResponse:
    """
    Normalised response returned by every provider's chat() call.
    The agentic loop reads only this object — never raw SDK types.
    """
    text: str | None                    # Prose text, if any
    tool_uses: list[ToolUseBlock]       # Zero or more tool invocations
    stop_reason: str                    # "end_turn" | "tool_use" | "max_tokens"
    assistant_message: dict             # Ready-to-append canonical history entry
    thinking: str | None = None         # Extended thinking inner monologue (Anthropic only)
    streamed_text: bool = False         # True if the text was already printed live to stdout

    @property
    def has_tool_uses(self) -> bool:
        """True when the model wants to call one or more tools."""
        return len(self.tool_uses) > 0


# ── Abstract provider interface ───────────────────────────────────────────────

class BaseProvider(ABC):
    """
    Every model provider must implement this interface.
    No other module should import SDK-specific types.
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str | None = None,
    ) -> ProviderResponse:
        """
        Send the conversation to the model and return a normalised response.

        Args:
            messages : Full conversation history in canonical format.
            tools    : Tool schemas in canonical (Anthropic-style) format.
            system   : Optional system prompt override.

        Returns:
            ProviderResponse — text, tool_uses, stop_reason, assistant_message.
        """
        ...

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str | None = None,
    ) -> ProviderResponse:
        """
        Stream the model response, printing tokens to the console in real time,
        then return the same ProviderResponse as chat().

        Providers that don't support streaming should fall back to chat().
        The default implementation does exactly that.
        """
        return await self.chat(messages, tools, system=system)

    @abstractmethod
    def make_tool_result_message(
        self,
        tool_use_id: str,
        content: str,
        is_error: bool = False,
    ) -> dict:
        """
        Build the canonical history message that carries a tool's output back
        to the model. This is appended to history immediately after a tool runs.

        Args:
            tool_use_id : The ID from the matching ToolUseBlock.
            content     : The tool's output (stringified).
            is_error    : True if the tool raised an exception.
        """
        ...

    @abstractmethod
    def make_user_message(self, text: str) -> dict:
        """
        Wrap a plain text string in a canonical user message dict.
        Used to inject the initial task into the conversation.
        """
        ...
