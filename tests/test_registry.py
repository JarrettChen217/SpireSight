import pytest
from spiresight.config.schema import ProviderConfig
from spiresight.llm import registry
from spiresight.llm.providers.openai_provider import OpenAIProvider


def test_registry_lists_three_providers():
    assert set(registry.names()) == {"openai", "anthropic", "gemini"}


def test_registry_returns_concrete_provider():
    p = registry.get("openai", ProviderConfig(api_key="sk-x"))
    assert isinstance(p, OpenAIProvider)
    assert p.name == "openai"


def test_registry_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        registry.get("nonesuch", ProviderConfig())
