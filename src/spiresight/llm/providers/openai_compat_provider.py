"""OpenAI-compatible relay provider.

Subclasses OpenAIProvider — same wire protocol, same SDK, just a different
base_url and no built-in model list. Designed for OpenRouter, DeepSeek,
Groq, Ollama, or arbitrary custom endpoints.
"""
from __future__ import annotations

from typing import Final

from spiresight.llm.models import ModelInfo
from spiresight.llm.providers.openai_provider import OpenAIProvider


RELAY_PRESETS: Final[dict[str, str]] = {
    "OpenRouter":   "https://openrouter.ai/api/v1",
    "DeepSeek":     "https://api.deepseek.com/v1",
    "Groq":         "https://api.groq.com/openai/v1",
    "Ollama local": "http://localhost:11434/v1",
}


class OpenAICompatProvider(OpenAIProvider):
    """OpenAI Chat Completions API against a third-party relay.

    Inherits stream() and fetch_remote_models() unchanged. Differences:
      - name is "openai_compat"
      - base_url is required (no fallback to api.openai.com)
      - _BUILTIN_DEFAULTS is empty: model selection comes entirely from the
        cached_models populated by the user's Settings Refresh action.
    """
    name = "openai_compat"
    _DEFAULT_BASE: str | None = None
    _BUILTIN_DEFAULTS: list[ModelInfo] = []
