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


def test_registry_builds_openai_with_options():
    from spiresight.llm.provider import ProviderOptions

    cfg = ProviderConfig(api_key="sk-test")
    opts = ProviderOptions(request_timeout_seconds=42)
    provider = registry.make_provider("openai", cfg, opts)
    assert provider.name == "openai"
    assert getattr(provider, "_options", None) is opts
