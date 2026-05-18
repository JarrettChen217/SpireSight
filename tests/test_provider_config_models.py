import pytest

from spiresight.config.schema import AppConfig, ModelInfoDict, ProviderConfig


def test_model_info_dict_defaults():
    d = ModelInfoDict(id="gpt-4o", display_name="GPT-4o")
    assert d.capabilities == []
    assert d.context_window == 0


def test_provider_config_default_cached_models_empty():
    pc = ProviderConfig()
    assert pc.cached_models == []


def test_provider_config_with_cached_models_roundtrip():
    pc = ProviderConfig(
        api_key="sk-x",
        base_url="https://api.example.com/v1",
        cached_models=[
            ModelInfoDict(
                id="gpt-4o",
                display_name="GPT-4o",
                capabilities=["vision", "tool_use", "json_mode"],
                context_window=128_000,
            ),
        ],
    )
    encoded = pc.model_dump_json()
    decoded = ProviderConfig.model_validate_json(encoded)
    assert decoded == pc


def test_app_config_active_provider_literal_rejects_unknown():
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        AppConfig(active_provider="bogus")  # type: ignore[arg-type]


def test_app_config_active_provider_accepts_openai_compat():
    cfg = AppConfig(active_provider="openai_compat")
    assert cfg.active_provider == "openai_compat"
