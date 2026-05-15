"""
agent/history.py
────────────────
Manages the conversation history and context window.

Improvements over original blunt character-count truncation:
  - Smart pruning: large bash/tool outputs are SUMMARISED in place rather
    than the whole message being dropped. The model retains awareness of
    what ran and what happened, just with a shorter representation.
  - Tool results over TOOL_RESULT_TRIM_CHARS are replaced with a one-line
    summary: "[output truncated — N lines, exit code X]"
  - When overall history still exceeds the limit after trimming, oldest
    user↔assistant pairs are dropped (never orphaning tool_use blocks).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Overall hard limit in characters (~400k chars ≈ 100k tokens)
_MAX_CHARS = 100_000 * 4

# Individual tool result outputs larger than this get summarised in-place
# before they're ever stored (≈4k tokens — enough for most command output)
_TOOL_RESULT_TRIM_CHARS = 16_000


def _summarise_tool_result_message(msg: dict[str, Any]) -> dict[str, Any]:
    """
    Replace oversized tool_result content blocks with a compact summary.
    Returns a new message dict; the original is not mutated.
    """
    if msg.get("role") != "user":
        return msg
    content = msg.get("content")
    if not isinstance(content, list):
        return msg

    new_blocks: list[dict[str, Any]] = []
    changed = False
    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_result"
            and isinstance(block.get("content"), str)
            and len(block["content"]) > _TOOL_RESULT_TRIM_CHARS
        ):
            raw: str = block["content"]
            lines = raw.splitlines()
            # Extract exit code if present (run_bash format)
            exit_code_line = next(
                (ln for ln in reversed(lines) if ln.startswith("exit code:")), None
            )
            exit_info = f", {exit_code_line}" if exit_code_line else ""
            summary = (
                f"[output trimmed — {len(lines)} lines, "
                f"{len(raw):,} chars{exit_info}. "
                f"First 20 lines:\n"
                + "\n".join(lines[:20])
                + ("\n…" if len(lines) > 20 else "")
                + "]"
            )
            new_blocks.append({**block, "content": summary})
            changed = True
        else:
            new_blocks.append(block)

    return {**msg, "content": new_blocks} if changed else msg


class HistoryManager:
    """Stores the conversation history and manages session persistence."""

    def __init__(self) -> None:
        self._messages: list[dict[str, Any]] = []

    def append(self, message: dict[str, Any]) -> None:
        """Add a message to history, summarising large tool outputs first."""
        self._messages.append(_summarise_tool_result_message(message))
        self._truncate_if_needed()

    def extend(self, messages: list[dict[str, Any]]) -> None:
        for msg in messages:
            self._messages.append(_summarise_tool_result_message(msg))
        self._truncate_if_needed()

    def get_messages(self) -> list[dict[str, Any]]:
        return list(self._messages)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _is_tool_result(self, msg: dict[str, Any]) -> bool:
        if msg.get("role") != "user":
            return False
        content = msg.get("content")
        if isinstance(content, list):
            return any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            )
        return False

    def _is_tool_use(self, msg: dict[str, Any]) -> bool:
        if msg.get("role") != "assistant":
            return False
        content = msg.get("content")
        if isinstance(content, list):
            return any(
                isinstance(b, dict) and b.get("type") == "tool_use" for b in content
            )
        return False

    def _truncate_if_needed(self) -> None:
        """
        Drop oldest complete exchange units until under _MAX_CHARS.

        An exchange unit is one of:
          • A plain user message
          • An assistant message + its following tool_result user messages

        We never drop a tool_use assistant message without also dropping
        its paired tool_result messages, avoiding Anthropic 400 errors.
        """
        while True:
            total = sum(len(json.dumps(m)) for m in self._messages)
            if total <= _MAX_CHARS or len(self._messages) <= 2:
                break

            # Find the first droppable unit: a user message that is NOT a
            # tool_result (those must go with their preceding assistant msg).
            drop_end = 0
            for i, msg in enumerate(self._messages):
                if msg.get("role") == "user" and not self._is_tool_result(msg):
                    drop_end = i + 1
                    # Also drop the following assistant message + its tool results
                    j = drop_end
                    while j < len(self._messages):
                        next_msg = self._messages[j]
                        if next_msg.get("role") == "assistant":
                            drop_end = j + 1
                            j += 1
                            # consume paired tool_results
                            while j < len(self._messages) and self._is_tool_result(
                                self._messages[j]
                            ):
                                drop_end = j + 1
                                j += 1
                        else:
                            break
                    break

            if drop_end == 0:
                # Fallback: drop the very first message
                self._messages.pop(0)
            else:
                del self._messages[:drop_end]

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: Path | str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self._messages, f, indent=2)

    def load(self, path: Path | str) -> None:
        p = Path(path)
        if not p.exists():
            return
        with open(p, "r", encoding="utf-8") as f:
            self._messages = json.load(f)
