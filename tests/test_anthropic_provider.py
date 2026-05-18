from __future__ import annotations

import pytest

from spiresight.config.schema import ProviderConfig
from spiresight.core.messages import Message
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import AuthError, MissingAPIKey, RequestTimeoutError
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.anthropic_provider import AnthropicProvider


class FakeDelta:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


class FakeEvent:
    def __init__(self, type_, delta=None):
        self.type = type_
        self.delta = delta


class FakeMessageSnapshot:
    def __init__(self, in_tok, out_tok):
        self.usage = type("U", (), {"input_tokens": in_tok, "output_tokens": out_tok})()


class FakeStream:
    def __init__(self, events, snapshot=None):
        self._events = events
        self.current_message_snapshot = snapshot
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def __iter__(self): return iter(self._events)


class FakeMessages:
    def __init__(self, events=None, raises=None, snapshot=None):
        self._events = events or []
        self._raises = raises
        self._snapshot = snapshot
        self.kwargs_seen: dict | None = None
    def stream(self, **kwargs):
        self.kwargs_seen = kwargs
        if self._raises is not None:
            raise self._raises
        f = FakeStream(self._events, snapshot=self._snapshot)
        return f


class FakeModelsList:
    def __init__(self, data):
        self.data = data


class FakeModelsAPI:
    def __init__(self, data=None, raises=None):
        self._data = data or []
        self._raises = raises
    def list(self, limit=100):
        if self._raises:
            raise self._raises
        return FakeModelsList(self._data)


class FakeAnthropic:
    def __init__(self, *, api_key, base_url, timeout, max_retries):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.messages = None
        self.models = None


def _make(monkeypatch, *, events=None, raises=None, snapshot=None,
          models_data=None, models_raises=None):
    holder = {}
    def factory(**kwargs):
        client = FakeAnthropic(**kwargs)
        client.messages = FakeMessages(events=events, raises=raises, snapshot=snapshot)
        client.models = FakeModelsAPI(data=models_data, raises=models_raises)
        holder["client"] = client
        return client
    monkeypatch.setattr("spiresight.llm.providers.anthropic_provider.Anthropic", factory)
    p = AnthropicProvider(ProviderConfig(api_key="key"), ProviderOptions(request_timeout_seconds=20))
    return p, holder


def test_stream_yields_text_then_usage_on_stop(monkeypatch):
    events = [
        FakeEvent("content_block_delta", delta=FakeDelta("text_delta", text="hello ")),
        FakeEvent("content_block_delta", delta=FakeDelta("text_delta", text="world")),
        FakeEvent("message_stop"),
    ]
    snap = FakeMessageSnapshot(in_tok=12, out_tok=4)
    p, _ = _make(monkeypatch, events=events, snapshot=snap)
    chunks = list(p.stream(model="claude-x", system="SYS", user_text="hi"))
    texts = "".join(c.text_delta for c in chunks if c.text_delta)
    assert texts == "hello world"
    usage = next(c for c in chunks if c.usage is not None)
    assert usage.usage.input_tokens == 12
    assert usage.usage.output_tokens == 4


def test_stream_passes_system_as_top_level_kwarg(monkeypatch):
    p, holder = _make(monkeypatch, events=[FakeEvent("message_stop")], snapshot=FakeMessageSnapshot(0, 0))
    list(p.stream(model="claude-x", system="MY-SYS", user_text="hi"))
    seen = holder["client"].messages.kwargs_seen
    assert seen["system"] == "MY-SYS"
    assert all(m.get("role") != "system" for m in seen["messages"])


def test_stream_missing_api_key_raises():
    p = AnthropicProvider(ProviderConfig(api_key=""), ProviderOptions())
    with pytest.raises(MissingAPIKey):
        list(p.stream(model="claude-x", system="s", user_text="hi"))


def test_stream_wraps_api_timeout(monkeypatch):
    import anthropic
    p, _ = _make(monkeypatch, raises=anthropic.APITimeoutError(request=None))
    with pytest.raises(RequestTimeoutError):
        list(p.stream(model="claude-x", system="s", user_text="hi"))


def test_stream_wraps_401(monkeypatch):
    import anthropic
    import httpx
    resp = httpx.Response(401, request=httpx.Request("POST", "https://x"))
    p, _ = _make(monkeypatch, raises=anthropic.APIStatusError("nope", response=resp, body={}))
    with pytest.raises(AuthError):
        list(p.stream(model="claude-x", system="s", user_text="hi"))


def test_build_messages_image_format(monkeypatch):
    p, holder = _make(monkeypatch, events=[FakeEvent("message_stop")], snapshot=FakeMessageSnapshot(0, 0))
    list(p.stream(
        model="claude-x", system="s",
        messages=[Message(role="user", text="look", image_png=b"\x89PNG_FAKE")],
    ))
    seen = holder["client"].messages.kwargs_seen
    msg = seen["messages"][0]
    assert msg["role"] == "user"
    assert isinstance(msg["content"], list)
    assert msg["content"][0] == {"type": "text", "text": "look"}
    assert msg["content"][1]["type"] == "image"
    assert msg["content"][1]["source"]["media_type"] == "image/png"


def test_fetch_remote_models_assigns_known_caps(monkeypatch):
    class FakeM:
        def __init__(self, mid, display=None):
            self.id = mid
            self.display_name = display or mid
    p, _ = _make(monkeypatch, models_data=[FakeM("claude-opus-4-7-20251015")])
    models = p.fetch_remote_models()
    assert models[0].capabilities >= frozenset({Capability.VISION, Capability.JSON_MODE})
