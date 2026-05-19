from __future__ import annotations

from spiresight.config.schema import ProviderConfig
from spiresight.llm.provider import LLMProvider, ProviderOptions
from spiresight.llm.providers.openai_provider import OpenAIProvider
from spiresight.llm.providers.openai_compat_provider import OpenAICompatProvider
from spiresight.llm.providers.pixel_api_provider import PixelApiProvider
from spiresight.llm.providers.anthropic_provider import AnthropicProvider
from spiresight.llm.providers.gemini_provider import GeminiProvider


_DISPLAY_NAMES: dict[str, str] = {
    "pixel_api": "PixelAPI-(OpenAI)",
}


def names() -> list[str]:
    return ["openai", "openai_compat", "pixel_api", "anthropic", "gemini"]


def display_name(name: str) -> str:
    """Human-facing label for the provider; falls back to capitalized internal name."""
    return _DISPLAY_NAMES.get(name) or name.capitalize()


def make_provider(
    name: str,
    config: ProviderConfig,
    options: ProviderOptions | None = None,
) -> LLMProvider:
    options = options or ProviderOptions()
    if name == "openai":
        return OpenAIProvider(config, options)
    if name == "openai_compat":
        return OpenAICompatProvider(config, options)
    if name == "pixel_api":
        return PixelApiProvider(config, options)
    if name == "anthropic":
        return AnthropicProvider(config, options)
    if name == "gemini":
        return GeminiProvider(config, options)
    raise KeyError(f"Unknown provider: {name}")


def get(name: str, config: ProviderConfig) -> LLMProvider:
    return make_provider(name, config)
