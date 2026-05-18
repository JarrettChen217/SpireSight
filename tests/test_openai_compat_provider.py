import pytest

from spiresight.config.schema import ProviderConfig
from spiresight.llm.errors import MissingBaseURL
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.openai_compat_provider import (
    OpenAICompatProvider, RELAY_PRESETS,
)


def test_relay_presets_includes_openrouter_and_deepseek():
    assert "OpenRouter" in RELAY_PRESETS
    assert "DeepSeek" in RELAY_PRESETS
    assert "Groq" in RELAY_PRESETS
    assert "Ollama local" in RELAY_PRESETS
    assert RELAY_PRESETS["OpenRouter"].endswith("/v1")


def test_constructs_without_base_url_raises(monkeypatch):
    monkeypatch.setattr(
        "spiresight.llm.providers.openai_provider.OpenAI",
        lambda **kw: object(),
    )
    with pytest.raises(MissingBaseURL):
        OpenAICompatProvider(ProviderConfig(api_key="sk-x"), ProviderOptions())


def test_constructs_with_base_url(monkeypatch):
    monkeypatch.setattr(
        "spiresight.llm.providers.openai_provider.OpenAI",
        lambda **kw: object(),
    )
    p = OpenAICompatProvider(
        ProviderConfig(api_key="sk-x", base_url="http://localhost:11434/v1"),
        ProviderOptions(),
    )
    assert p.name == "openai_compat"


def test_builtin_defaults_empty(monkeypatch):
    monkeypatch.setattr(
        "spiresight.llm.providers.openai_provider.OpenAI",
        lambda **kw: object(),
    )
    p = OpenAICompatProvider(
        ProviderConfig(api_key="sk-x", base_url="http://x/v1"),
        ProviderOptions(),
    )
    assert p._BUILTIN_DEFAULTS == []
    assert p.list_models() == []
