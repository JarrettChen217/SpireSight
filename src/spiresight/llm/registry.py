from __future__ import annotations

from collections.abc import Callable

from spiresight.config.schema import ProviderConfig
from spiresight.llm.provider import LLMProvider
from spiresight.llm.providers.openai_provider import OpenAIProvider
from spiresight.llm.providers.anthropic_provider import AnthropicProvider
from spiresight.llm.providers.gemini_provider import GeminiProvider

_PROVIDERS: dict[str, Callable[[ProviderConfig], LLMProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
}


def names() -> list[str]:
    return list(_PROVIDERS.keys())


def get(name: str, config: ProviderConfig) -> LLMProvider:
    if name not in _PROVIDERS:
        raise KeyError(f"Unknown provider: {name}")
    return _PROVIDERS[name](config)
