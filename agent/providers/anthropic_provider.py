"""
agent/providers/anthropic_provider.py
───────────────────────────────────────
Anthropic (Claude) model provider.

Uses the official `anthropic` Python SDK with async support.
The canonical message format IS the Anthropic format, so this
provider does zero conversion — it passes history directly.

Tool schemas use Anthropic's native `input_schema` key (JSON Schema).
"""

from __future__ import annotations

import asyncio
from typing import Any

import anthropic

from agent.config import Config
from agent.providers.base import BaseProvider, ProviderResponse, ToolUseBlock

# Maximum tokens to request in model responses
# When thinking is enabled we need to allow more room for the thinking budget + response
_MAX_TOKENS = 16000
_MAX_TOKENS_NO_THINKING = 8096

# Retry config for rate-limit / overload errors (NFR-07)
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0   # seconds; doubles each attempt: 1 → 2 → 4

# Default system prompt — can be overridden per-call
_DEFAULT_SYSTEM = (
    "You are DevPilot, an expert AI coding agent running in a terminal. "
    "You help developers read files, write code, run commands, and debug projects. "
    "Be concise. Always explain what you are about to do before calling a tool. "
    "When you have finished a task, summarise what you did. "
    "CRITICAL: When using the write_file tool to modify existing code, you MUST output the ENTIRE file from the first line to the last. "
    "NEVER use placeholders like '... existing code ...', 'pass', or write incomplete stubs. "
    "Failure to output the complete file will destroy the user's project."
)


class AnthropicProvider(BaseProvider):
    """
    Wraps anthropic.AsyncAnthropic.

    Message format: canonical = Anthropic native → no conversion needed.
    Tool schema format: canonical = Anthropic native → no conversion needed.
    """

    def __init__(self, config: Config) -> None:
        config.validate_api_key()                       # Fail early if key missing
        self._config = config
        self._client = anthropic.AsyncAnthropic(
            api_key=config.active_api_key,
        )

    async def _create_with_retry(self, **kwargs: Any) -> anthropic.types.Message:
        """
        Call messages.create with exponential-backoff retry.
        Retries on RateLimitError (429) and APIStatusError (529 overload).
        Raises on the final attempt.
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return await self._client.messages.create(**kwargs)  # type: ignore[call-overload]
            except (anthropic.RateLimitError, anthropic.APIStatusError) as exc:
                if attempt == _MAX_RETRIES:
                    raise
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                print(
                    f"  [DevPilot] API error ({exc.__class__.__name__}), "
                    f"retrying in {delay:.0f}s … (attempt {attempt + 1}/{_MAX_RETRIES})"
                )
                await asyncio.sleep(delay)
                last_exc = exc
        raise RuntimeError("Retry loop exited unexpectedly")  # unreachable

    # ── BaseProvider implementation ───────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str | None = None,
    ) -> ProviderResponse:
        """Call Anthropic messages.create (with retry) and return a ProviderResponse."""
        kwargs: dict[str, Any] = dict(
            model=self._config.model,
            system=system or _DEFAULT_SYSTEM,
            messages=messages,
            tools=tools,
        )

        if self._config.extended_thinking:
            # Extended thinking requires the interleaved-thinking beta
            kwargs["betas"] = ["interleaved-thinking-2025-05-14"]
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self._config.thinking_budget,
            }
            # max_tokens must be > thinking_budget for the model to actually reply
            kwargs["max_tokens"] = max(_MAX_TOKENS, self._config.thinking_budget + 4096)
        else:
            kwargs["max_tokens"] = _MAX_TOKENS_NO_THINKING

        response = await self._create_with_retry(**kwargs)

        text: str | None = None
        tool_uses: list[ToolUseBlock] = []
        raw_content: list[dict] = []
        thinking_text: str | None = None

        for block in response.content:
            if block.type == "thinking":
                # Extended thinking block — capture for UI rendering
                thinking_text = block.thinking
                raw_content.append({"type": "thinking", "thinking": block.thinking})

            elif block.type == "text":
                text = block.text
                raw_content.append({"type": "text", "text": block.text})

            elif block.type == "tool_use":
                tool_uses.append(
                    ToolUseBlock(id=block.id, name=block.name, input=block.input)
                )
                raw_content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )

        assistant_message = {"role": "assistant", "content": raw_content}

        # Bug 3 fix: check tool_uses first — a None stop_reason during a
        # tool-use turn must NOT fall through to "end_turn" and halt the loop.
        stop_reason = (
            "tool_use" if tool_uses else (response.stop_reason or "end_turn")
        )

        return ProviderResponse(
            text=text,
            tool_uses=tool_uses,
            stop_reason=stop_reason,
            assistant_message=assistant_message,
            thinking=thinking_text,
        )

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str | None = None,
    ) -> ProviderResponse:
        """
        Stream tokens live to the terminal, then return a full ProviderResponse.

        Anthropic SDK note: streaming is not compatible with extended_thinking,
        so we fall back to the non-streaming path when thinking is enabled.
        """
        if self._config.extended_thinking:
            # Streaming + thinking not supported — use blocking call
            return await self.chat(messages, tools, system=system)

        from agent.ui import console  # local import avoids circular dep at module level

        kwargs: dict[str, Any] = dict(
            model=self._config.model,
            max_tokens=_MAX_TOKENS_NO_THINKING,
            system=system or _DEFAULT_SYSTEM,
            messages=messages,
            tools=tools,
        )

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                # Print tokens as they arrive — no newline yet
                console.print()  # blank line before streaming starts
                async for text_delta in stream.text_stream:
                    console.print(text_delta, end="", highlight=False)
                console.print()  # newline after stream ends
                console.print()

                # Get the fully-parsed final message (tool_use blocks etc.)
                final = await stream.get_final_message()

        except (anthropic.RateLimitError, anthropic.APIStatusError):
            # On rate-limit during stream, fall back to retry-capable non-streaming
            return await self.chat(messages, tools, system=system)

        # Parse identically to non-streaming path
        text: str | None = None
        tool_uses: list[ToolUseBlock] = []
        raw_content: list[dict] = []

        for block in final.content:
            if block.type == "text":
                text = block.text
                raw_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                tool_uses.append(
                    ToolUseBlock(id=block.id, name=block.name, input=block.input)
                )
                raw_content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )

        stop_reason = "tool_use" if tool_uses else (final.stop_reason or "end_turn")
        assistant_message = {"role": "assistant", "content": raw_content}

        return ProviderResponse(
            text=text,
            tool_uses=tool_uses,
            stop_reason=stop_reason,
            assistant_message=assistant_message,
            streamed_text=True,
        )

    def make_tool_result_message(
        self,
        tool_use_id: str,
        content: str,
        is_error: bool = False,
    ) -> dict:
        """
        Returns the canonical user-role message that carries a tool result.
        Appended to history immediately after a tool executes.
        """
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                    "is_error": is_error,
                }
            ],
        }

    def make_user_message(self, text: str) -> dict:
        """Wrap a plain text string as a canonical user message."""
        return {"role": "user", "content": text}
