# tests/test_provider_contract.py
import threading
from collections.abc import Iterator

from spiresight.llm.provider import LLMProvider, StreamChunk
from spiresight.llm.models import ModelInfo
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import (
    LLMError,
    MissingAPIKey,
    MissingCapabilityError,
    AuthError,
    RateLimitError,
    NetworkError,
)


class _Fake:
    name = "fake"

    def list_models(self) -> list[ModelInfo]:
        return [ModelInfo("fake-1", "Fake 1", frozenset({Capability.VISION}), 8000)]

    def stream(self, *, model, system, user_text, image_png, cancel_event) -> Iterator[StreamChunk]:
        yield StreamChunk(text_delta="hi")
        yield StreamChunk(text_delta="!", finish_reason="stop")


def test_protocol_structural_typing():
    fake: LLMProvider = _Fake()  # static-typing reassurance; runtime is duck-typed
    assert fake.name == "fake"
    assert fake.list_models()[0].id == "fake-1"


def test_streamchunk_defaults():
    c = StreamChunk(text_delta="x")
    assert c.text_delta == "x"
    assert c.finish_reason is None


def test_errors_inherit_from_llm_error():
    for cls in (MissingAPIKey, MissingCapabilityError, AuthError, RateLimitError, NetworkError):
        assert issubclass(cls, LLMError)


def test_missing_capability_carries_missing_set():
    err = MissingCapabilityError(model="gpt-3.5-turbo", missing={Capability.VISION})
    assert "gpt-3.5-turbo" in str(err)
    assert err.model == "gpt-3.5-turbo"
    assert err.missing == {Capability.VISION}


def test_streaming_via_protocol_consumes_chunks():
    fake: LLMProvider = _Fake()
    chunks = list(fake.stream(
        model="fake-1", system="sys", user_text="hi",
        image_png=None, cancel_event=threading.Event(),
    ))
    assert "".join(c.text_delta for c in chunks) == "hi!"
    assert chunks[-1].finish_reason == "stop"
