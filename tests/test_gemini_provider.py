from __future__ import annotations

import pytest

from spiresight.config.schema import ProviderConfig
from spiresight.core.messages import Message
from spiresight.llm.errors import MissingAPIKey
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.gemini_provider import GeminiProvider


class FakeUsageMeta:
    def __init__(self, prompt, candidates):
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates


class FakeChunk:
    def __init__(self, text="", usage=None):
        self.text = text
        self.usage_metadata = usage


class FakeModelsAPI:
    def __init__(self, *, stream_chunks=None, stream_raises=None,
                 list_data=None, list_raises=None):
        self._chunks = stream_chunks or []
        self._stream_raises = stream_raises
        self._list_data = list_data or []
        self._list_raises = list_raises
        self.stream_kwargs: dict | None = None
    def generate_content_stream(self, **kwargs):
        self.stream_kwargs = kwargs
        if self._stream_raises is not None:
            raise self._stream_raises
        return iter(self._chunks)
    def list(self):
        if self._list_raises:
            raise self._list_raises
        return iter(self._list_data)


class FakeClient:
    def __init__(self, *, api_key, http_options=None):
        self.api_key = api_key
        self.http_options = http_options
        self.models = None


def _make(monkeypatch, **api_kwargs):
    holder = {}
    def factory(api_key=None, http_options=None):
        c = FakeClient(api_key=api_key, http_options=http_options)
        c.models = FakeModelsAPI(**api_kwargs)
        holder["client"] = c
        return c
    monkeypatch.setattr("spiresight.llm.providers.gemini_provider.genai", type("G", (), {"Client": factory}))
    p = GeminiProvider(ProviderConfig(api_key="g-key"), ProviderOptions())
    return p, holder


def test_stream_collects_text_and_usage(monkeypatch):
    chunks = [
        FakeChunk(text="A"),
        FakeChunk(text="B"),
        FakeChunk(usage=FakeUsageMeta(prompt=7, candidates=2)),
    ]
    p, _ = _make(monkeypatch, stream_chunks=chunks)
    out = list(p.stream(model="gemini-2.5-pro", system="SYS", user_text="hi"))
    text = "".join(c.text_delta for c in out)
    assert text == "AB"
    usage = next(c for c in out if c.usage is not None)
    assert usage.usage.input_tokens == 7
    assert usage.usage.output_tokens == 2


def test_assistant_role_maps_to_model(monkeypatch):
    p, holder = _make(monkeypatch, stream_chunks=[])
    list(p.stream(
        model="gemini-2.5-flash", system="s",
        messages=[
            Message(role="user", text="hi", image_png=None),
            Message(role="assistant", text="hello", image_png=None),
        ],
    ))
    contents = holder["client"].models.stream_kwargs["contents"]
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"


def test_json_mode_sets_response_mime_type(monkeypatch):
    p, holder = _make(monkeypatch, stream_chunks=[])
    list(p.stream(model="gemini-2.5-flash", system="s", user_text="hi", json_mode=True))
    cfg = holder["client"].models.stream_kwargs["config"]
    assert cfg.response_mime_type == "application/json"


def test_system_instruction_set_in_config(monkeypatch):
    p, holder = _make(monkeypatch, stream_chunks=[])
    list(p.stream(model="gemini-2.5-flash", system="MY-SYS", user_text="hi"))
    cfg = holder["client"].models.stream_kwargs["config"]
    assert cfg.system_instruction == "MY-SYS"


def test_missing_api_key_raises():
    p = GeminiProvider(ProviderConfig(api_key=""), ProviderOptions())
    with pytest.raises(MissingAPIKey):
        list(p.stream(model="gemini-2.5-pro", system="s", user_text="hi"))


def test_fetch_remote_models_filters_embed_and_aqa(monkeypatch):
    class FakeM:
        def __init__(self, name, display=None, ctx=0):
            self.name = name
            self.display_name = display
            self.input_token_limit = ctx
    listed = [
        FakeM("models/gemini-2.5-pro", display="Gemini 2.5 Pro", ctx=2_000_000),
        FakeM("models/text-embedding-004"),
        FakeM("models/aqa"),
    ]
    p, _ = _make(monkeypatch, list_data=listed)
    models = p.fetch_remote_models()
    ids = {m.id for m in models}
    assert "gemini-2.5-pro" in ids
    assert "text-embedding-004" not in ids
    assert "aqa" not in ids
