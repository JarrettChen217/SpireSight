from __future__ import annotations

from spiresight.core.usage import TokenUsage
from spiresight.llm.usage_parsing import parse_openai_usage


class _ChatDetails:
    def __init__(self, cached: int) -> None:
        self.cached_tokens = cached


class _ChatUsage:
    def __init__(self, prompt: int, completion: int, cached: int = 0) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.prompt_tokens_details = _ChatDetails(cached)


class _ResponsesDetails:
    def __init__(self, cached: int) -> None:
        self.cached_tokens = cached


class _ResponsesUsage:
    def __init__(self, inp: int, out: int, cached: int = 0) -> None:
        self.input_tokens = inp
        self.output_tokens = out
        self.input_tokens_details = _ResponsesDetails(cached)


def test_parse_chat_usage_with_cached():
    u = parse_openai_usage(_ChatUsage(100, 20, 60))
    assert u == TokenUsage(100, 20, 60)


def test_parse_responses_usage_with_cached():
    u = parse_openai_usage(_ResponsesUsage(200, 30, 150))
    assert u == TokenUsage(200, 30, 150)


def test_parse_missing_cached_defaults_zero():
    class Bare:
        prompt_tokens = 10
        completion_tokens = 5

    u = parse_openai_usage(Bare())
    assert u.cached_tokens == 0


def test_parse_none_usage():
    assert parse_openai_usage(None) == TokenUsage(0, 0, 0)
