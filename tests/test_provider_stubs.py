import threading
import pytest
from spiresight.config.schema import ProviderConfig
from spiresight.llm.errors import MissingAPIKey
from spiresight.llm.providers.anthropic_provider import AnthropicProvider
from spiresight.llm.providers.gemini_provider import GeminiProvider


@pytest.mark.parametrize("cls,name", [
    (AnthropicProvider, "anthropic"),
    (GeminiProvider, "gemini"),
])
def test_stub_advertises_name_and_models(cls, name):
    p = cls(ProviderConfig(api_key=""))
    assert p.name == name


def test_anthropic_list_models_has_builtin_defaults():
    p = AnthropicProvider(ProviderConfig(api_key=""))
    models = p.list_models()
    assert len(models) > 0


def test_anthropic_stream_raises_missing_api_key():
    p = AnthropicProvider(ProviderConfig(api_key=""))
    with pytest.raises(MissingAPIKey):
        list(p.stream(
            model="x", system="s", user_text="u",
            images=[], cancel_event=threading.Event(),
        ))
