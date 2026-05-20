from __future__ import annotations

import pytest

from spiresight.config.schema import ProviderConfig
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import (
    AuthError, MissingAPIKey, RateLimitError, RequestTimeoutError,
)
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.openai_provider import OpenAIProvider


class FakeChoice:
    def __init__(self, content="", finish_reason=None):
        self.delta = type("D", (), {"content": content})()
        self.finish_reason = finish_reason


class FakeEvent:
    def __init__(self, choices=None, usage=None):
        self.choices = choices or []
        self.usage = usage


class FakeUsage:
    def __init__(self, prompt, completion, cached=0):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.prompt_tokens_details = type('D', (), {'cached_tokens': cached})()


class FakeStream:
    """Context manager that yields a fixed sequence of FakeEvent."""
    def __init__(self, events):
        self._events = events
    def __enter__(self): return iter(self._events)
    def __exit__(self, *exc): return False


class FakeCompletions:
    def __init__(self, events=None, raises=None):
        self._events = events or []
        self._raises = raises
    def create(self, **kwargs):
        if self._raises is not None:
            raise self._raises
        return FakeStream(self._events)


class FakeModelsList:
    def __init__(self, data):
        self.data = data


class FakeModels:
    def __init__(self, data=None, raises=None):
        self._data = data or []
        self._raises = raises
    def list(self):
        if self._raises:
            raise self._raises
        return FakeModelsList(self._data)


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeOpenAI:
    def __init__(self, *, api_key, base_url, timeout, max_retries):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.chat = None       # filled by test
        self.models = None     # filled by test


def _make(monkeypatch, *, events=None, raises=None, models_data=None, models_raises=None):
    holder = {}
    def factory(**kwargs):
        client = FakeOpenAI(**kwargs)
        client.chat = FakeChat(FakeCompletions(events=events, raises=raises))
        client.models = FakeModels(data=models_data, raises=models_raises)
        holder["client"] = client
        return client
    monkeypatch.setattr("spiresight.llm.providers.openai_provider.OpenAI", factory)
    provider = OpenAIProvider(
        ProviderConfig(api_key="sk-x"),
        ProviderOptions(request_timeout_seconds=30),
    )
    return provider, holder


def test_constructs_with_default_base_url(monkeypatch):
    p, holder = _make(monkeypatch)
    assert holder["client"].base_url == "https://api.openai.com/v1"


def test_stream_yields_text_then_usage(monkeypatch):
    events = [
        FakeEvent(choices=[FakeChoice(content="hello ")]),
        FakeEvent(choices=[FakeChoice(content="world", finish_reason="stop")]),
        FakeEvent(usage=FakeUsage(prompt=10, completion=5)),
    ]
    p, _ = _make(monkeypatch, events=events)
    chunks = list(p.stream(model="gpt-4o", system="s", user_text="hi"))
    texts = [c.text_delta for c in chunks if c.text_delta]
    assert "".join(texts) == "hello world"
    usage_chunks = [c for c in chunks if c.usage is not None]
    assert len(usage_chunks) == 1
    assert usage_chunks[0].usage.input_tokens == 10


def test_stream_raises_missing_api_key():
    p = OpenAIProvider(ProviderConfig(api_key=""), ProviderOptions())
    with pytest.raises(MissingAPIKey):
        list(p.stream(model="gpt-4o", system="s", user_text="hi"))


def test_stream_wraps_api_timeout(monkeypatch):
    import openai
    exc = openai.APITimeoutError(request=None)
    p, _ = _make(monkeypatch, raises=exc)
    with pytest.raises(RequestTimeoutError):
        list(p.stream(model="gpt-4o", system="s", user_text="hi"))


def test_stream_wraps_401(monkeypatch):
    import openai
    import httpx
    resp = httpx.Response(401, request=httpx.Request("POST", "https://x"))
    body = {"error": {"message": "unauthorized"}}
    p, _ = _make(monkeypatch, raises=openai.APIStatusError("unauthorized", response=resp, body=body))
    with pytest.raises(AuthError):
        list(p.stream(model="gpt-4o", system="s", user_text="hi"))


def test_stream_wraps_429(monkeypatch):
    import openai
    import httpx
    resp = httpx.Response(429, request=httpx.Request("POST", "https://x"),
                          headers={"retry-after": "30"})
    body = {"error": {"message": "rate limited"}}
    p, _ = _make(monkeypatch, raises=openai.RateLimitError("rate limited", response=resp, body=body))
    with pytest.raises(RateLimitError):
        list(p.stream(model="gpt-4o", system="s", user_text="hi"))


def test_fetch_remote_models_returns_known_capabilities(monkeypatch):
    class FakeModelEntry:
        def __init__(self, mid): self.id = mid
    p, _ = _make(monkeypatch, models_data=[FakeModelEntry("gpt-4o"), FakeModelEntry("totally-unknown-xyz")])
    models = p.fetch_remote_models()
    assert {m.id for m in models} == {"gpt-4o", "totally-unknown-xyz"}
    gpt4o = next(m for m in models if m.id == "gpt-4o")
    assert Capability.VISION in gpt4o.capabilities


def test_list_models_prefers_cached(monkeypatch):
    from spiresight.config.schema import ModelInfoDict
    cfg = ProviderConfig(
        api_key="sk-x",
        cached_models=[ModelInfoDict(id="cached-model", display_name="C", capabilities=["json_mode"])],
    )
    monkeypatch.setattr(
        "spiresight.llm.providers.openai_provider.OpenAI",
        lambda **kw: type("F", (), {"chat": None, "models": None})(),
    )
    p = OpenAIProvider(cfg, ProviderOptions())
    models = p.list_models()
    assert len(models) == 1
    assert models[0].id == "cached-model"

def test_stream_usage_includes_cached(monkeypatch):
    from spiresight.core.usage import TokenUsage
    events = [
        FakeEvent(choices=[FakeChoice("hi")]),
        FakeEvent(usage=FakeUsage(10, 5, cached=7)),
    ]
    p, _ = _make(monkeypatch, events=events)
    chunks = list(p.stream(model="gpt-4o", system="s", user_text="hi",
                                  cancel_event=__import__("threading").Event()))
    usage_chunks = [c for c in chunks if c.usage is not None]
    assert usage_chunks[-1].usage == TokenUsage(10, 5, 7)
