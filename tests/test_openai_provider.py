# tests/test_openai_provider.py
import base64
import threading

import httpx
import pytest
import respx

from spiresight.config.schema import ProviderConfig
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import AuthError, MissingAPIKey, NetworkError, RateLimitError
from spiresight.llm.providers.openai_provider import OpenAIProvider


def _sse(*chunks: str) -> str:
    return "".join(f"data: {c}\n\n" for c in chunks) + "data: [DONE]\n\n"


def test_list_models_includes_vision_and_non_vision():
    p = OpenAIProvider(ProviderConfig(api_key="sk-x"))
    ids = {m.id for m in p.list_models()}
    assert "gpt-4o" in ids and "gpt-4o-mini" in ids
    gpt4o = next(m for m in p.list_models() if m.id == "gpt-4o")
    assert Capability.VISION in gpt4o.capabilities
    non_vision = next(m for m in p.list_models() if m.id == "gpt-3.5-turbo")
    assert Capability.VISION not in non_vision.capabilities


def test_missing_api_key_raises_on_stream():
    p = OpenAIProvider(ProviderConfig(api_key=""))
    with pytest.raises(MissingAPIKey):
        list(p.stream(
            model="gpt-4o", system="s", user_text="hi",
            images=[], cancel_event=threading.Event(),
        ))


@respx.mock
def test_stream_text_only_request_yields_chunks():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse(
                '{"choices":[{"delta":{"content":"Hello"}}]}',
                '{"choices":[{"delta":{"content":" world"},"finish_reason":null}]}',
                '{"choices":[{"delta":{},"finish_reason":"stop"}]}',
            ),
        )
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-test"))
    chunks = list(p.stream(
        model="gpt-4o", system="sys", user_text="hi",
        images=[], cancel_event=threading.Event(),
    ))
    assert route.called
    assert "".join(c.text_delta for c in chunks) == "Hello world"
    assert chunks[-1].finish_reason == "stop"
    # text-only requests must not include an image part
    body = route.calls.last.request.content.decode()
    assert "image_url" not in body


@respx.mock
def test_stream_with_image_sends_multimodal_payload():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse('{"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}'),
        )
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-test"))
    png = b"\x89PNG\r\n\x1a\nFAKE"
    list(p.stream(
        model="gpt-4o", system="sys", user_text="see this",
        images=[png], cancel_event=threading.Event(),
    ))
    body = respx.calls.last.request.content.decode()
    expected_b64 = base64.b64encode(png).decode()
    assert "image_url" in body
    assert expected_b64 in body


@respx.mock
def test_401_maps_to_auth_error():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-bad"))
    with pytest.raises(AuthError):
        list(p.stream(
            model="gpt-4o", system="s", user_text="u",
            images=[], cancel_event=threading.Event(),
        ))


@respx.mock
def test_429_maps_to_rate_limit():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(429, headers={"retry-after": "3"}, json={})
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-x"))
    with pytest.raises(RateLimitError) as exc:
        list(p.stream(
            model="gpt-4o", system="s", user_text="u",
            images=[], cancel_event=threading.Event(),
        ))
    assert exc.value.retry_after == 3.0


@respx.mock
def test_network_error_maps():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=httpx.ConnectError("boom")
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-x"))
    with pytest.raises(NetworkError):
        list(p.stream(
            model="gpt-4o", system="s", user_text="u",
            images=[], cancel_event=threading.Event(),
        ))


@respx.mock
def test_cancel_event_aborts_stream_mid_flight():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse(
                '{"choices":[{"delta":{"content":"part1"}}]}',
                '{"choices":[{"delta":{"content":"part2"}}]}',
                '{"choices":[{"delta":{"content":"part3"},"finish_reason":"stop"}]}',
            ),
        )
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-x"))
    evt = threading.Event()
    out: list[str] = []
    for chunk in p.stream(
        model="gpt-4o", system="s", user_text="u",
        images=[], cancel_event=evt,
    ):
        out.append(chunk.text_delta)
        if "part1" in out:
            evt.set()
    assert out == ["part1"]


@respx.mock
def test_stream_with_json_mode_sets_response_format():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse('{"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}]}'),
        )
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-test"))
    list(p.stream(
        model="gpt-4o", system="sys", user_text="hi",
        images=[], cancel_event=threading.Event(),
        json_mode=True,
    ))
    body = route.calls.last.request.content.decode()
    assert '"response_format"' in body
    assert '"json_object"' in body


@respx.mock
def test_stream_without_json_mode_omits_response_format():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse('{"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}'),
        )
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-test"))
    list(p.stream(
        model="gpt-4o", system="sys", user_text="hi",
        images=[], cancel_event=threading.Event(),
    ))
    body = route.calls.last.request.content.decode()
    assert "response_format" not in body


def test_build_user_content_no_images_returns_plain_text():
    from spiresight.llm.providers.openai_provider import OpenAIProvider
    result = OpenAIProvider._build_user_content("hello", [])
    assert result == "hello"


def test_build_user_content_one_image_returns_parts():
    from spiresight.llm.providers.openai_provider import OpenAIProvider
    import base64
    png = b"\x89PNG"
    result = OpenAIProvider._build_user_content("hi", [png])
    assert isinstance(result, list)
    assert result[0] == {"type": "text", "text": "hi"}
    assert result[1]["type"] == "image_url"
    assert result[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert base64.b64decode(result[1]["image_url"]["url"].split(",")[1]) == png


def test_build_user_content_three_images_preserves_order():
    from spiresight.llm.providers.openai_provider import OpenAIProvider
    pngs = [b"A", b"B", b"C"]
    result = OpenAIProvider._build_user_content("x", pngs)
    assert len(result) == 4  # text + 3 images
    assert result[0]["type"] == "text"
    for i, (part, expected_png) in enumerate(zip(result[1:], pngs), start=1):
        assert part["type"] == "image_url"
