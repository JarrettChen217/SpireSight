# tests/test_config_store.py
import json
import pytest
from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.config.store import ConfigStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIRESIGHT_CONFIG_DIR", str(tmp_path))
    return ConfigStore()


def test_load_returns_defaults_when_no_file(store):
    cfg = store.load()
    assert cfg.active_provider == "openai"
    assert cfg.active_model == "gpt-4o"
    assert cfg.language == "en"
    assert cfg.always_on_top is True
    assert cfg.providers == {}


def test_save_then_load_roundtrip(store):
    cfg = AppConfig(active_provider="openai", active_model="gpt-4o-mini")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-test")
    store.save(cfg)
    loaded = store.load()
    assert loaded.active_model == "gpt-4o-mini"
    assert loaded.providers["openai"].api_key == "sk-test"


def test_save_writes_atomically(store, tmp_path):
    cfg = AppConfig()
    store.save(cfg)
    # tmp file must not be left behind
    assert not (tmp_path / "config.json.tmp").exists()
    assert (tmp_path / "config.json").exists()


def test_load_recovers_from_corrupt_file(store, tmp_path):
    (tmp_path / "config.json").write_text("{not json")
    cfg = store.load()
    # corrupt file → defaults returned
    assert cfg.active_provider == "openai"


def test_load_falls_back_when_validation_fails(store, tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"language": "fr"}))
    # "fr" is not in Literal["en", "zh"]; loader returns defaults.
    cfg = store.load()
    assert cfg.language == "en"


def test_include_screenshot_default_defaults_to_false():
    from spiresight.config.schema import AppConfig
    cfg = AppConfig()
    assert cfg.include_screenshot_default is False


def test_app_config_request_timeout_default():
    from spiresight.config.schema import AppConfig
    cfg = AppConfig()
    assert cfg.request_timeout_seconds == 180


def test_app_config_request_timeout_override():
    from spiresight.config.schema import AppConfig
    cfg = AppConfig(request_timeout_seconds=60)
    assert cfg.request_timeout_seconds == 60


def test_app_config_defaults_bubble_size():
    from spiresight.config.schema import AppConfig
    cfg = AppConfig()
    assert cfg.bubble_width == 360
    assert cfg.bubble_height == 280


def test_app_config_round_trip_preserves_bubble_size(tmp_path):
    from spiresight.config.schema import AppConfig
    from spiresight.config.store import ConfigStore

    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(bubble_width=500, bubble_height=320)
    store.save(cfg)
    loaded = store.load()
    assert loaded.bubble_width == 500
    assert loaded.bubble_height == 320


def test_app_config_legacy_file_uses_defaults(tmp_path):
    """A config file written before bubble_width/height existed must still load."""
    import json
    from spiresight.config.store import ConfigStore

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"hotkey": "ctrl+shift+x"}), encoding="utf-8")
    cfg = ConfigStore(path).load()
    assert cfg.bubble_width == 360
    assert cfg.bubble_height == 280
