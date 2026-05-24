"""
agent/config.py
───────────────
Central configuration for DevPilot.

All settings are read from environment variables (or a .env file).
API keys are NEVER hardcoded. Missing keys raise a clear ConfigError
so the user knows exactly what to set before running.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

# ── Persistent user config: ~/.devpilot/.env ─────────────────────────────────
# This is where the setup wizard saves configuration so it persists
# regardless of which directory `devpilot` is run from.
_USER_CONFIG_DIR = Path.home() / ".devpilot"
_USER_ENV_FILE   = _USER_CONFIG_DIR / ".env"

# Load global user config first — this is where the setup wizard saves settings
load_dotenv(dotenv_path=_USER_ENV_FILE, override=False)

# Load project-local .env second — can ADD vars but won't override global config
# (override=False means global ~/.devpilot/.env always wins)
load_dotenv(dotenv_path=Path(".") / ".env", override=False)



# ── Custom exception ─────────────────────────────────────────────────────────

class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


# ── Supported providers ───────────────────────────────────────────────────────

Provider = Literal["anthropic", "openai"]

PROVIDER_DEFAULTS: dict[str, str] = {
    "anthropic": "claude-opus-4-5-20251101",
    "openai":    "gpt-5.4",
}

# Keys required per provider (checked lazily so we can build/test without keys)
REQUIRED_ENV_KEYS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

# Models that support extended thinking (Anthropic only)
# Verified via Anthropic API — May 2026
THINKING_CAPABLE_MODELS: set[str] = {
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-opus-4-5-20251101",
    "claude-opus-4-1-20250805",
    "claude-sonnet-4-5-20250929",
    "claude-3-7-sonnet-20250219",
    "claude-3-5-sonnet-20241022",
}


# ── Config dataclass ──────────────────────────────────────────────────────────

@dataclass
class Config:
    # Provider + model
    provider: Provider
    model: str
    base_url: str | None          # Custom endpoint for Ollama / local models

    # Agentic loop
    max_iterations: int

    # Safety
    no_confirm: bool

    # A2A server
    a2a_port: int
    a2a_token: str | None

    # Workspace
    workdir: str

    # Extended thinking (Anthropic Claude only)
    extended_thinking: bool
    thinking_budget: int

    # Feature flags
    web_search_enabled: bool
    memory_enabled: bool
    a2a_enabled: bool

    # Sessions
    sessions_dir: Path

    # ── Derived properties ────────────────────────────────────────────────────

    @property
    def anthropic_api_key(self) -> str | None:
        return os.getenv("ANTHROPIC_API_KEY")

    @property
    def openai_api_key(self) -> str | None:
        return os.getenv("OPENAI_API_KEY")

    @property
    def active_api_key(self) -> str | None:
        """Return the API key for the currently selected provider."""
        if self.provider == "anthropic":
            return self.anthropic_api_key
        return self.openai_api_key

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_api_key(self) -> None:
        """
        Raises ConfigError if the active provider's API key is missing.
        Call this right before making the first API request — not at startup —
        so users can explore/test without a key.
        """
        key_name = REQUIRED_ENV_KEYS[self.provider]
        if not self.active_api_key:
            raise ConfigError(
                f"\n[DevPilot] Missing API key for provider '{self.provider}'.\n"
                f"  → Set the environment variable: {key_name}\n"
                f"  → Or add it to your .env file (copy .env.example to .env).\n"
                f"  → Get an Anthropic key at: https://console.anthropic.com/\n"
            )
        
        if self.extended_thinking:
            if self.provider != "anthropic":
                raise ConfigError("Extended thinking is only supported with the Anthropic provider.")
            if self.thinking_budget < 1000:
                raise ConfigError("thinking_budget must be >= 1000 tokens.")
            # Note: We don't strictly enforce model names since API evolves, but it's good to check
            if not any(self.model.startswith(m) for m in ["claude-3", "claude-opus"]):
                pass  # We'll let the API reject it if it's really unsupported

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def load(cls) -> "Config":
        """
        Load configuration from environment variables.
        Raises ConfigError for invalid (not missing) values.
        """
        # ── Provider ────────────────────────────────────────────────────
        provider_raw = os.getenv("DEVPILOT_PROVIDER", "anthropic").lower()
        if provider_raw not in ("anthropic", "openai"):
            raise ConfigError(
                f"Invalid DEVPILOT_PROVIDER='{provider_raw}'. "
                "Must be 'anthropic' or 'openai'."
            )
        provider: Provider = provider_raw  # type: ignore[assignment]

        # ── Model ───────────────────────────────────────────────────────
        model = os.getenv("DEVPILOT_MODEL") or PROVIDER_DEFAULTS[provider]

        # ── Base URL ────────────────────────────────────────────────────
        base_url = os.getenv("DEVPILOT_BASE_URL") or None

        # ── Max iterations ───────────────────────────────────────────────
        try:
            max_iterations = int(os.getenv("DEVPILOT_MAX_ITERATIONS", "50"))
            if max_iterations < 1:
                raise ValueError
        except ValueError:
            raise ConfigError(
                "DEVPILOT_MAX_ITERATIONS must be a positive integer."
            )

        # ── No-confirm flag ─────────────────────────────────────────────
        no_confirm_raw = os.getenv("DEVPILOT_NO_CONFIRM", "false").lower()
        no_confirm = no_confirm_raw in ("true", "1", "yes")

        # ── A2A port ────────────────────────────────────────────────────
        try:
            a2a_port = int(os.getenv("DEVPILOT_A2A_PORT", "8000"))
        except ValueError:
            raise ConfigError("DEVPILOT_A2A_PORT must be an integer.")

        # ── A2A token ───────────────────────────────────────────────────
        a2a_token = os.getenv("DEVPILOT_A2A_TOKEN") or None

        # ── Workspace ───────────────────────────────────────────────────
        workdir = os.getenv("DEVPILOT_WORKDIR", os.getcwd())

        # ── Extended thinking ───────────────────────────────────────────
        extended_thinking = os.getenv("DEVPILOT_THINKING", "false").lower() in ("true", "1", "yes")
        try:
            thinking_budget = int(os.getenv("DEVPILOT_THINKING_BUDGET", "10000"))
        except ValueError:
            raise ConfigError("DEVPILOT_THINKING_BUDGET must be an integer.")

        # ── Feature flags ───────────────────────────────────────────────
        web_search_enabled = os.getenv("DEVPILOT_NO_WEB_SEARCH", "false").lower() not in ("true", "1", "yes")
        memory_enabled = os.getenv("DEVPILOT_NO_MEMORY", "false").lower() not in ("true", "1", "yes")
        a2a_enabled = os.getenv("DEVPILOT_NO_A2A", "false").lower() not in ("true", "1", "yes")

        # ── Sessions dir ────────────────────────────────────────────────
        sessions_dir = Path(
            os.getenv("DEVPILOT_SESSIONS_DIR", ".devpilot_sessions")
        )

        return cls(
            provider=provider,
            model=model,
            base_url=base_url,
            max_iterations=max_iterations,
            no_confirm=no_confirm,
            a2a_port=a2a_port,
            a2a_token=a2a_token,
            workdir=workdir,
            extended_thinking=extended_thinking,
            thinking_budget=thinking_budget,
            web_search_enabled=web_search_enabled,
            memory_enabled=memory_enabled,
            a2a_enabled=a2a_enabled,
            sessions_dir=sessions_dir,
        )

    # ── Display ───────────────────────────────────────────────────────────────

    def __str__(self) -> str:
        key_status = "✓ present" if self.active_api_key else "✗ MISSING"
        return (
            f"DevPilot Config\n"
            f"  provider      : {self.provider}\n"
            f"  model         : {self.model}\n"
            f"  base_url      : {self.base_url or '(default)'}\n"
            f"  max_iterations: {self.max_iterations}\n"
            f"  no_confirm    : {self.no_confirm}\n"
            f"  a2a_port      : {self.a2a_port}\n"
            f"  thinking      : {self.extended_thinking} (budget: {self.thinking_budget})\n"
            f"  web_search    : {self.web_search_enabled}\n"
            f"  memory        : {self.memory_enabled}\n"
            f"  a2a           : {self.a2a_enabled}\n"
            f"  api_key       : {key_status}\n"
            f"  sessions_dir  : {self.sessions_dir}\n"
        )
