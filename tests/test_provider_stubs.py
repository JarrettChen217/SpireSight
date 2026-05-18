"""Smoke tests that all three stub providers expose the real ProviderProtocol surface.

The behavior tests live in test_anthropic_provider.py / test_gemini_provider.py /
test_openai_provider.py.
"""
from __future__ import annotations

from spiresight.config.schema import ProviderConfig
from spiresight.llm.provider import LLMProvider, ProviderOptions
from spiresight.llm.providers.anthropic_provider import AnthropicProvider
from spiresight.llm.providers.gemini_provider import GeminiProvider


def test_anthropic_satisfies_protocol(monkeypatch):
    monkeypatch.setattr(
        "spiresight.llm.providers.anthropic_provider.Anthropic",
        lambda **kw: object(),
    )
    p = AnthropicProvider(ProviderConfig(api_key="k"), ProviderOptions())
    assert isinstance(p, LLMProvider)
    assert hasattr(p, "fetch_remote_models")


def test_gemini_satisfies_protocol(monkeypatch):
    class FakeGenAI:
        def Client(self, **kwargs):
            return object()
    monkeypatch.setattr("spiresight.llm.providers.gemini_provider.genai", FakeGenAI())
    p = GeminiProvider(ProviderConfig(api_key="k"), ProviderOptions())
    assert isinstance(p, LLMProvider)
    assert hasattr(p, "fetch_remote_models")


def test_anthropic_has_builtin_defaults(monkeypatch):
    monkeypatch.setattr(
        "spiresight.llm.providers.anthropic_provider.Anthropic",
        lambda **kw: object(),
    )
    p = AnthropicProvider(ProviderConfig(api_key="k"), ProviderOptions())
    models = p.list_models()
    assert len(models) > 0
    assert any("claude" in m.id for m in models)


def test_gemini_has_builtin_defaults(monkeypatch):
    class FakeGenAI:
        def Client(self, **kwargs):
            return object()
    monkeypatch.setattr("spiresight.llm.providers.gemini_provider.genai", FakeGenAI())
    p = GeminiProvider(ProviderConfig(api_key="k"), ProviderOptions())
    models = p.list_models()
    assert len(models) > 0
    assert any("gemini" in m.id for m in models)
