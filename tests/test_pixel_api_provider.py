import pytest

from spiresight.config.schema import ProviderConfig
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.pixel_api_provider import (
    PIXEL_API_BASE_URL, PixelApiProvider,
)


def test_default_base_url_constant():
    assert PIXEL_API_BASE_URL == "http://pixel.try-chatapi.com/v1"


def test_constructs_without_base_url_uses_default(monkeypatch):
    captured: dict = {}

    def fake_openai(**kw):
        captured.update(kw)
        return object()

    monkeypatch.setattr(
        "spiresight.llm.providers.pixel_api_provider.OpenAI", fake_openai
    )
    p = PixelApiProvider(ProviderConfig(api_key="sk-x"), ProviderOptions())
    assert p.name == "pixel_api"
    assert p.display_name == "PixelAPI-(OpenAI)"
    assert captured["base_url"] == PIXEL_API_BASE_URL


def test_constructs_with_custom_base_url(monkeypatch):
    captured: dict = {}

    def fake_openai(**kw):
        captured.update(kw)
        return object()

    monkeypatch.setattr(
        "spiresight.llm.providers.pixel_api_provider.OpenAI", fake_openai
    )
    PixelApiProvider(
        ProviderConfig(api_key="sk-x", base_url="http://custom/v1"),
        ProviderOptions(),
    )
    assert captured["base_url"] == "http://custom/v1"


def test_builtin_defaults_includes_known_models(monkeypatch):
    monkeypatch.setattr(
        "spiresight.llm.providers.pixel_api_provider.OpenAI", lambda **kw: object()
    )
    p = PixelApiProvider(
        ProviderConfig(api_key="sk-x"), ProviderOptions(),
    )
    ids = {m.id for m in p._BUILTIN_DEFAULTS}
    assert "gpt-5.5" in ids
    assert "gpt-5.4-mini" in ids
    assert p.list_models() == p._BUILTIN_DEFAULTS


def test_fetch_remote_models_uses_builtin_no_network(monkeypatch):
    """fetch_remote_models must NOT call .models.list() — the relay's
    /v1/models endpoint is on a 76-second slow path."""
    monkeypatch.setattr(
        "spiresight.llm.providers.pixel_api_provider.OpenAI", lambda **kw: object()
    )
    p = PixelApiProvider(
        ProviderConfig(api_key="sk-x"), ProviderOptions(),
    )
    # Replace internal client with one that explodes on any attribute access.
    class Boom:
        def __getattr__(self, name):
            raise AssertionError(f"network call attempted: {name}")
    p._client = Boom()
    models = p.fetch_remote_models()
    assert len(models) > 0
    assert {m.id for m in models} == {m.id for m in p._BUILTIN_DEFAULTS}


def test_build_user_content_text_only():
    parts = PixelApiProvider._build_user_content("hello", [])
    assert parts == [{"type": "input_text", "text": "hello"}]


def test_build_user_content_with_image():
    png = b"\x89PNG\r\n\x1a\nfake"
    parts = PixelApiProvider._build_user_content("look at this", [png])
    assert parts[0] == {"type": "input_text", "text": "look at this"}
    assert parts[1]["type"] == "input_image"
    assert parts[1]["image_url"].startswith("data:image/png;base64,")


def test_build_input_from_messages_skips_system():
    from spiresight.core.messages import Message

    msgs = [
        Message(role="user", text="hi"),
        Message(role="assistant", text="hello there"),
        Message(role="user", text="what about images?", image_png=b"\x89PNG"),
    ]
    result = PixelApiProvider._build_input_from_messages(msgs)
    assert len(result) == 3
    assert result[0] == {
        "role": "user",
        "content": [{"type": "input_text", "text": "hi"}],
    }
    assert result[1] == {
        "role": "assistant",
        "content": [{"type": "output_text", "text": "hello there"}],
    }
    assert result[2]["role"] == "user"
    assert result[2]["content"][0] == {"type": "input_text", "text": "what about images?"}
    assert result[2]["content"][1]["type"] == "input_image"


def _setup_capture(monkeypatch):
    captured: dict = {}

    class FakeStream:
        def __enter__(self):
            return iter([])
        def __exit__(self, *a):
            return False

    class FakeResponses:
        def stream(self, **kw):
            captured.update(kw)
            return FakeStream()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(
        "spiresight.llm.providers.pixel_api_provider.OpenAI", lambda **kw: FakeClient()
    )
    return captured


def test_stream_text_only_uses_plain_string_input(monkeypatch):
    """Regression: structured `input=[{role,content:[parts]}]` consistently
    triggers a ~76s slow path on this relay. Text-only calls must use plain
    string input to stay on the fast path."""
    captured = _setup_capture(monkeypatch)
    p = PixelApiProvider(ProviderConfig(api_key="sk-x"), ProviderOptions())
    list(p.stream(model="gpt-5.5", system="", user_text="hi there"))
    assert captured["input"] == "hi there"
    assert "instructions" not in captured  # empty system => omit instructions


def test_stream_with_system_passes_instructions(monkeypatch):
    captured = _setup_capture(monkeypatch)
    p = PixelApiProvider(ProviderConfig(api_key="sk-x"), ProviderOptions())
    list(p.stream(model="gpt-5.5", system="you are X", user_text="hi"))
    assert captured["input"] == "hi"
    assert captured["instructions"] == "you are X"


def test_stream_with_images_uses_structured_input(monkeypatch):
    captured = _setup_capture(monkeypatch)
    p = PixelApiProvider(ProviderConfig(api_key="sk-x"), ProviderOptions())
    list(p.stream(model="gpt-5.5", system="", user_text="describe", images=[b"\x89PNG"]))
    assert isinstance(captured["input"], list)
    assert captured["input"][0]["role"] == "user"
    content = captured["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert content[1]["type"] == "input_image"


def test_stream_json_mode_uses_json_schema_not_json_object(monkeypatch):
    """Regression: the relay's upstream returns 502 for `json_object`. We must
    send `json_schema` instead."""
    captured: dict = {}

    class FakeStream:
        def __enter__(self):
            return iter([])
        def __exit__(self, *a):
            return False

    class FakeResponses:
        def stream(self, **kw):
            captured.update(kw)
            return FakeStream()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(
        "spiresight.llm.providers.pixel_api_provider.OpenAI", lambda **kw: FakeClient()
    )
    p = PixelApiProvider(ProviderConfig(api_key="sk-x"), ProviderOptions())
    list(p.stream(model="gpt-5.5", system="hi", user_text="ping", json_mode=True))

    fmt = captured.get("text", {}).get("format", {})
    assert fmt.get("type") == "json_schema", "must NOT be json_object — relay 502s on it"
    assert "schema" in fmt
    assert fmt["schema"]["type"] == "object"


def test_stream_raises_missing_api_key(monkeypatch):
    monkeypatch.setattr(
        "spiresight.llm.providers.pixel_api_provider.OpenAI", lambda **kw: object()
    )
    from spiresight.llm.errors import MissingAPIKey

    p = PixelApiProvider(ProviderConfig(api_key=""), ProviderOptions())
    with pytest.raises(MissingAPIKey):
        list(p.stream(model="gpt-5.5", system="hi"))
