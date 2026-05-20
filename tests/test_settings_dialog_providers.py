from pathlib import Path

from unittest.mock import MagicMock

from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.config.store import ConfigStore
from spiresight.prompts.ui_locale import UILocale
from spiresight.llm.capabilities import Capability
from spiresight.llm.models import ModelInfo


def _locale():
    repo = Path(__file__).resolve().parents[1] / "prompts"
    return UILocale(repo / "locales", "en")


def _config(tmp_path):
    return AppConfig(
        providers={
            "openai": ProviderConfig(api_key=""),
            "openai_compat": ProviderConfig(api_key="", base_url=""),
            "pixel_api": ProviderConfig(api_key=""),
            "anthropic": ProviderConfig(api_key=""),
            "gemini": ProviderConfig(api_key=""),
        }
    )


def test_dialog_creates_pane_per_provider(qtbot, tmp_path):
    from spiresight.ui.windows.settings_dialog import SettingsDialog
    cfg = _config(tmp_path)
    store = MagicMock(spec=ConfigStore)
    dlg = SettingsDialog(cfg, store, _locale())
    qtbot.addWidget(dlg)
    assert set(dlg._panes.keys()) == {"openai", "openai_compat", "pixel_api", "anthropic", "gemini"}


def test_refresh_succeeded_persists_models(qtbot, tmp_path, monkeypatch):
    from spiresight.ui.windows.settings_dialog import SettingsDialog
    cfg = _config(tmp_path)
    store = MagicMock(spec=ConfigStore)
    dlg = SettingsDialog(cfg, store, _locale())
    qtbot.addWidget(dlg)
    fake_models = [
        ModelInfo("m1", "M1", frozenset({Capability.VISION, Capability.JSON_MODE}), 100),
    ]
    dlg._on_refresh_succeeded("openai", fake_models)
    cached = cfg.providers["openai"].cached_models
    assert len(cached) == 1
    assert cached[0].id == "m1"
    assert "json_mode" in cached[0].capabilities
    store.save.assert_called_once_with(cfg)


def test_refresh_failed_emits_signal(qtbot, tmp_path, monkeypatch):
    from spiresight.ui.windows.settings_dialog import SettingsDialog
    from PySide6.QtWidgets import QMessageBox
    # Prevent modal QMessageBox from blocking the test
    monkeypatch.setattr(QMessageBox, "warning", MagicMock())
    cfg = _config(tmp_path)
    store = MagicMock(spec=ConfigStore)
    dlg = SettingsDialog(cfg, store, _locale())
    qtbot.addWidget(dlg)
    with qtbot.waitSignal(dlg.models_refresh_failed, timeout=2000) as blocker:
        dlg._on_refresh_failed("openai", RuntimeError("bad"))
    assert blocker.args[0] == "openai"


def test_apply_writes_api_keys_and_base_urls(qtbot, tmp_path):
    from spiresight.ui.windows.settings_dialog import SettingsDialog
    cfg = _config(tmp_path)
    store = MagicMock(spec=ConfigStore)
    dlg = SettingsDialog(cfg, store, _locale())
    qtbot.addWidget(dlg)
    dlg._panes["openai"]._api_key_edit.setText("sk-new")
    dlg._panes["openai_compat"]._api_key_edit.setText("relay-key")
    dlg._panes["openai_compat"]._base_url_edit.setText("http://localhost:11434/v1")
    dlg._apply_and_accept()
    assert cfg.providers["openai"].api_key == "sk-new"
    assert cfg.providers["openai_compat"].api_key == "relay-key"
    assert cfg.providers["openai_compat"].base_url == "http://localhost:11434/v1"


def test_apply_persists_image_policy(qtbot, tmp_path):
    from spiresight.ui.windows.settings_dialog import SettingsDialog
    cfg = _config(tmp_path)
    cfg.image_policy = "full"
    store = __import__("unittest.mock").mock.MagicMock(spec=ConfigStore)
    dlg = SettingsDialog(cfg, store, _locale())
    qtbot.addWidget(dlg)
    idx = dlg._image_policy.findData("once_only")
    dlg._image_policy.setCurrentIndex(idx)
    dlg._apply_and_accept()
    assert cfg.image_policy == "once_only"
