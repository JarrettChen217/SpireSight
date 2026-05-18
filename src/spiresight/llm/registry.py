from __future__ import annotations

from spiresight.config.schema import ProviderConfig
from spiresight.llm.provider import LLMProvider, ProviderOptions
from spiresight.llm.providers.openai_provider import OpenAIProvider
from spiresight.llm.providers.anthropic_provider import AnthropicProvider
from spiresight.llm.providers.gemini_provider import GeminiProvider


def names() -> list[str]:
    return ["openai", "anthropic", "gemini"]


def make_provider(
    name: str,
    config: ProviderConfig,
    options: ProviderOptions | None = None,
) -> LLMProvider:
    options = options or ProviderOptions()
    if name == "openai":
        return OpenAIProvider(config, options)
    if name == "anthropic":
        return AnthropicProvider(config, options)
    if name == "gemini":
        return GeminiProvider(config, options)
    raise KeyError(f"Unknown provider: {name}")


def get(name: str, config: ProviderConfig) -> LLMProvider:
    return make_provider(name, config)
