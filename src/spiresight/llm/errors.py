# src/spiresight/llm/errors.py
from __future__ import annotations

from .capabilities import Capability


class LLMError(Exception):
    """Base class for all LLM-provider-related errors."""


class MissingAPIKey(LLMError):
    def __init__(self, provider: str) -> None:
        super().__init__(f"No API key configured for provider '{provider}'")
        self.provider = provider


class MissingCapabilityError(LLMError):
    def __init__(self, *, model: str, missing: set[Capability]) -> None:
        names = ", ".join(sorted(c.value for c in missing))
        super().__init__(f"Model '{model}' lacks required capabilities: {names}")
        self.model = model
        self.missing = set(missing)


class AuthError(LLMError):
    """Provider rejected the API key (HTTP 401)."""


class RateLimitError(LLMError):
    """Provider rate-limited the request (HTTP 429)."""
    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("Rate limited")
        self.retry_after = retry_after


class NetworkError(LLMError):
    """Network failure or timeout."""
