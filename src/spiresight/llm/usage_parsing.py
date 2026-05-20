"""Parse token usage from OpenAI Chat Completions and Responses API objects."""
from __future__ import annotations

from spiresight.core.usage import TokenUsage


def _cached_from_details(details: object | None) -> int:
    if details is None:
        return 0
    raw = getattr(details, "cached_tokens", None)
    if raw is None and isinstance(details, dict):
        raw = details.get("cached_tokens")
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def parse_openai_usage(usage: object) -> TokenUsage:
    """Map Chat Completions or Responses API usage to TokenUsage."""
    if usage is None:
        return TokenUsage(0, 0, 0)

    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    if prompt is None:
        prompt = getattr(usage, "input_tokens", 0)
    if completion is None:
        completion = getattr(usage, "output_tokens", 0)

    details = getattr(usage, "prompt_tokens_details", None)
    if details is None:
        details = getattr(usage, "input_tokens_details", None)

    return TokenUsage(
        input_tokens=max(0, int(prompt or 0)),
        output_tokens=max(0, int(completion or 0)),
        cached_tokens=_cached_from_details(details),
    )
