import openai
import pytest

from spiresight.config.schema import ProviderConfig
from spiresight.llm.errors import RequestTimeoutError
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.openai_provider import OpenAIProvider


def test_openai_provider_stores_options(monkeypatch):
    monkeypatch.setattr(
        "spiresight.llm.providers.openai_provider.OpenAI",
        lambda **kw: type("F", (), {"chat": None, "models": None})(),
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-x"), ProviderOptions(request_timeout_seconds=42))
    assert p._options.request_timeout_seconds == 42


def test_openai_provider_wraps_api_timeout(monkeypatch):
    exc = openai.APITimeoutError(request=None)

    class FakeCompletions:
        def create(self, **kwargs):
            raise exc

    class FakeChat:
        def __init__(self): self.completions = FakeCompletions()

    monkeypatch.setattr(
        "spiresight.llm.providers.openai_provider.OpenAI",
        lambda **kw: type("F", (), {"chat": FakeChat(), "models": None})(),
    )
    p = OpenAIProvider(
        ProviderConfig(api_key="sk-x"),
        ProviderOptions(request_timeout_seconds=5),
    )
    with pytest.raises(RequestTimeoutError) as exc_info:
        list(p.stream(model="gpt-4o", system="s", user_text="hi"))
    assert "5s timeout" in str(exc_info.value)
