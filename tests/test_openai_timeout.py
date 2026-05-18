import httpx
import pytest

from spiresight.config.schema import ProviderConfig
from spiresight.llm.errors import RequestTimeoutError
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.openai_provider import OpenAIProvider


def test_openai_provider_stores_options():
    p = OpenAIProvider(ProviderConfig(api_key="sk-x"), ProviderOptions(request_timeout_seconds=42))
    assert p._options.request_timeout_seconds == 42


def test_openai_provider_wraps_httpx_timeout(monkeypatch):
    """Simulate httpx.ReadTimeout during stream() and assert RequestTimeoutError is raised."""

    class _FakeStream:
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def __init__(self, *a, **kw):
            raise httpx.ReadTimeout("read timed out")

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def stream(self, *a, **kw): return _FakeStream()

    monkeypatch.setattr(httpx, "Client", _FakeClient)

    p = OpenAIProvider(
        ProviderConfig(api_key="sk-x"),
        ProviderOptions(request_timeout_seconds=5),
    )
    with pytest.raises(RequestTimeoutError) as exc_info:
        list(p.stream(model="gpt-4o", system="s", user_text="hi"))
    assert "5s timeout" in str(exc_info.value)
