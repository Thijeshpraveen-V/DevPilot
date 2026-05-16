"""
agent/providers/anthropic_provider.py
───────────────────────────────────────
Anthropic (Claude) model provider.
"""

from __future__ import annotations

import asyncio
from typing import Any

import anthropic

from agent.config import Config
from agent.providers.base import BaseProvider, ProviderResponse, ToolUseBlock
from agent.providers.system_prompt import build_system_prompt

_MAX_TOKENS = 16000
_MAX_TOKENS_NO_THINKING = 8096
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0


class AnthropicProvider(BaseProvider):

    def __init__(self, config: Config) -> None:
        config.validate_api_key()
        self._config = config
        self._client = anthropic.AsyncAnthropic(api_key=config.active_api_key)

    async def _create_with_retry(self, **kwargs: Any) -> anthropic.types.Message:
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
        raise RuntimeError("Retry loop exited unexpectedly")

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str | None = None,
    ) -> ProviderResponse:
        kwargs: dict[str, Any] = dict(
            model=self._config.model,
            system=system or build_system_prompt(),
            messages=messages,
            tools=tools,
        )

        if self._config.extended_thinking:
            kwargs["betas"] = ["interleaved-thinking-2025-05-14"]
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self._config.thinking_budget,
            }
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
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                )

        stop_reason = "tool_use" if tool_uses else (response.stop_reason or "end_turn")
        return ProviderResponse(
            text=text,
            tool_uses=tool_uses,
            stop_reason=stop_reason,
            assistant_message={"role": "assistant", "content": raw_content},
            thinking=thinking_text,
        )

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str | None = None,
    ) -> ProviderResponse:
        if self._config.extended_thinking:
            return await self.chat(messages, tools, system=system)

        from agent.ui import console

        kwargs: dict[str, Any] = dict(
            model=self._config.model,
            max_tokens=_MAX_TOKENS_NO_THINKING,
            system=system or build_system_prompt(),
            messages=messages,
            tools=tools,
        )

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                from agent.ui import UI
                if not getattr(UI, "_tui_app", None):
                    console.print()

                async for text_delta in stream.text_stream:
                    UI.print_stream_token(text_delta)

                if not getattr(UI, "_tui_app", None):
                    console.print()
                    console.print()

                final = await stream.get_final_message()

        except (anthropic.RateLimitError, anthropic.APIStatusError):
            return await self.chat(messages, tools, system=system)

        text = None
        tool_uses = []
        raw_content = []

        for block in final.content:
            if block.type == "text":
                text = block.text
                raw_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                tool_uses.append(
                    ToolUseBlock(id=block.id, name=block.name, input=block.input)
                )
                raw_content.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                )

        stop_reason = "tool_use" if tool_uses else (final.stop_reason or "end_turn")
        return ProviderResponse(
            text=text,
            tool_uses=tool_uses,
            stop_reason=stop_reason,
            assistant_message={"role": "assistant", "content": raw_content},
            streamed_text=True,
        )

    def make_tool_result_message(self, tool_use_id: str, content: str, is_error: bool = False) -> dict:
        return {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": content, "is_error": is_error}],
        }

    def make_user_message(self, text: str) -> dict:
        return {"role": "user", "content": text}
