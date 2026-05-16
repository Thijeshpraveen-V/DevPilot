"""
agent/providers/openai_provider.py
────────────────────────────────────
OpenAI-compatible model provider.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall

from agent.config import Config
from agent.providers.base import BaseProvider, ProviderResponse, ToolUseBlock
from agent.providers.system_prompt import build_system_prompt

_MAX_TOKENS = 4096
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0

_STOP_REASON_MAP: dict[str, str] = {
    "stop":           "end_turn",
    "tool_calls":     "tool_use",
    "length":         "max_tokens",
    "content_filter": "end_turn",
}


class OpenAIProvider(BaseProvider):

    def __init__(self, config: Config) -> None:
        config.validate_api_key()
        self._config = config
        self._client = AsyncOpenAI(api_key=config.active_api_key, base_url=config.base_url)

    @staticmethod
    def _to_openai_messages(messages: list[dict]) -> list[dict]:
        result: list[dict] = []
        for msg in messages:
            role: str = msg["role"]
            content: Any = msg["content"]

            if isinstance(content, str):
                result.append({"role": role, "content": content})
                continue

            if role == "assistant":
                text_parts: list[str] = []
                tool_calls: list[dict] = []
                for block in content:
                    if block["type"] == "text":
                        text_parts.append(block["text"])
                    elif block["type"] == "tool_use":
                        tool_calls.append({
                            "id": block["id"],
                            "type": "function",
                            "function": {"name": block["name"], "arguments": json.dumps(block["input"])},
                        })
                oai_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": " ".join(text_parts) if text_parts else None,
                }
                if tool_calls:
                    oai_msg["tool_calls"] = tool_calls
                result.append(oai_msg)

            elif role == "user":
                for block in content:
                    if block["type"] == "tool_result":
                        result.append({
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": block["content"],
                        })
                    else:
                        result.append({"role": "user", "content": block.get("text", "")})

        return result

    @staticmethod
    def _to_openai_tools(tools: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            }
            for t in tools
        ]

    async def _create_with_retry(self, **kwargs: Any) -> ChatCompletion:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return cast(ChatCompletion, await self._client.chat.completions.create(**kwargs))
            except (openai.RateLimitError, openai.APIStatusError) as exc:
                if attempt == _MAX_RETRIES:
                    raise
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                print(
                    f"  [DevPilot] API error ({exc.__class__.__name__}), "
                    f"retrying in {delay:.0f}s … (attempt {attempt + 1}/{_MAX_RETRIES})"
                )
                await asyncio.sleep(delay)
        raise RuntimeError("Unreachable")

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str | None = None,
    ) -> ProviderResponse:
        oai_messages = self._to_openai_messages(messages)
        oai_messages.insert(0, {"role": "system", "content": system or build_system_prompt()})

        call_kwargs: dict[str, Any] = {
            "model": self._config.model,
            "max_completion_tokens": _MAX_TOKENS,
            "messages": oai_messages,
        }
        oai_tools = self._to_openai_tools(tools)
        if oai_tools:
            call_kwargs["tools"] = oai_tools

        response = await self._create_with_retry(**call_kwargs)
        choice = response.choices[0]
        oai_msg = choice.message

        text: str | None = oai_msg.content or None
        tool_uses: list[ToolUseBlock] = []
        raw_content: list[dict] = []

        if text:
            raw_content.append({"type": "text", "text": text})

        tool_calls = oai_msg.tool_calls
        if tool_calls:
            for tc in tool_calls:
                tc_typed = cast(ChatCompletionMessageToolCall, tc)
                fn_name: str = tc_typed.function.name
                fn_args: str = tc_typed.function.arguments or "{}"
                try:
                    tool_input: dict = json.loads(fn_args)
                except json.JSONDecodeError:
                    tool_input = {}
                tool_uses.append(ToolUseBlock(id=tc_typed.id, name=fn_name, input=tool_input))
                raw_content.append(
                    {"type": "tool_use", "id": tc_typed.id, "name": fn_name, "input": tool_input}
                )
        elif text:
            # Fallback: detect JSON tool calls hallucinated inline by local models (e.g. Ollama)
            try:
                import re, uuid
                match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
                if match:
                    potential_json, start_idx, end_idx = match.group(1), match.start(), match.end()
                else:
                    start_idx, end_idx = text.find("{"), text.rfind("}")
                    potential_json = text[start_idx:end_idx + 1] if start_idx != -1 and end_idx > start_idx else ""

                if potential_json:
                    parsed = json.loads(potential_json)
                    if isinstance(parsed, dict) and "name" in parsed and "arguments" in parsed:
                        fake_id = f"call_{uuid.uuid4().hex[:8]}"
                        tool_uses.append(ToolUseBlock(id=fake_id, name=parsed["name"], input=parsed.get("arguments", {})))
                        raw_content.append(
                            {"type": "tool_use", "id": fake_id, "name": parsed["name"], "input": parsed.get("arguments", {})}
                        )
            except Exception:
                pass

        stop_reason = _STOP_REASON_MAP.get(choice.finish_reason or "stop", "end_turn")
        return ProviderResponse(
            text=text,
            tool_uses=tool_uses,
            stop_reason=stop_reason,
            assistant_message={"role": "assistant", "content": raw_content},
        )

    def make_tool_result_message(self, tool_use_id: str, content: str, is_error: bool = False) -> dict:
        return {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": content, "is_error": is_error}],
        }

    def make_user_message(self, text: str) -> dict:
        return {"role": "user", "content": text}
