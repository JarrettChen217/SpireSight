import threading
import pytest
from spiresight.config.schema import ProviderConfig
from spiresight.llm.providers.anthropic_provider import AnthropicProvider
from spiresight.llm.providers.gemini_provider import GeminiProvider


@pytest.mark.parametrize("cls,name", [
    (AnthropicProvider, "anthropic"),
    (GeminiProvider, "gemini"),
])
def test_stub_advertises_name_and_models(cls, name):
    p = cls(ProviderConfig(api_key=""))
    assert p.name == name
    assert p.list_models() == []  # stubs offer no models yet


@pytest.mark.parametrize("cls", [AnthropicProvider, GeminiProvider])
def test_stub_stream_raises_not_implemented(cls):
    p = cls(ProviderConfig(api_key="sk-x"))
    with pytest.raises(NotImplementedError):
        list(p.stream(
            model="x", system="s", user_text="u",
            images=[], cancel_event=threading.Event(),
        ))
