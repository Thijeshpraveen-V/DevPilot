"""
agent/providers/factory.py
───────────────────────────
Single factory function that reads config and instantiates
the correct provider. All other modules use this instead of
importing individual providers directly.
"""

from __future__ import annotations

from agent.config import Config
from agent.providers.base import BaseProvider


def create_provider(config: Config) -> BaseProvider:
    """
    Instantiate and return the correct BaseProvider for the given config.

    Raises:
        ValueError  : If config.provider is not a recognised name.
        ConfigError : If the provider's API key is missing (raised inside __init__).
    """
    # Import here (not at module level) to avoid loading unused SDKs
    if config.provider == "anthropic":
        from agent.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(config)

    if config.provider == "openai":
        from agent.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(config)

    raise ValueError(
        f"Unknown provider '{config.provider}'. "
        "Valid options are: 'anthropic', 'openai'."
    )
