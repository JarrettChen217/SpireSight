from unittest.mock import MagicMock

from spiresight.config.schema import ProviderConfig
from spiresight.ui.widgets.provider_pane import ProviderPane


def test_pane_returns_api_key_and_base_url(qtbot):
    cb = MagicMock()
    pane = ProviderPane(
        "openai_compat",
        ProviderConfig(api_key="k1", base_url="http://x/v1"),
        require_base_url=True,
        base_url_presets={"X": "http://x/v1"},
        on_refresh=cb,
    )
    qtbot.addWidget(pane)
    assert pane.api_key_value() == "k1"
    assert pane.base_url_value() == "http://x/v1"


def test_pane_hides_base_url_when_not_required(qtbot):
    cb = MagicMock()
    pane = ProviderPane(
        "openai",
        ProviderConfig(api_key="k"),
        require_base_url=False,
        base_url_presets=None,
        on_refresh=cb,
    )
    qtbot.addWidget(pane)
    pane.show()
    assert pane._base_url_edit.isVisible() is False


def test_pane_preset_fills_base_url(qtbot):
    cb = MagicMock()
    pane = ProviderPane(
        "openai_compat",
        ProviderConfig(api_key="k"),
        require_base_url=True,
        base_url_presets={"OpenRouter": "https://openrouter.ai/api/v1"},
        on_refresh=cb,
    )
    qtbot.addWidget(pane)
    # Select OpenRouter preset (index 1, after "Custom…" at 0)
    pane._preset_combo.setCurrentIndex(1)
    pane._preset_combo.activated.emit(1)
    assert pane.base_url_value() == "https://openrouter.ai/api/v1"


def test_pane_refresh_button_invokes_callback(qtbot):
    cb = MagicMock()
    pane = ProviderPane(
        "openai",
        ProviderConfig(api_key="k"),
        require_base_url=False,
        base_url_presets=None,
        on_refresh=cb,
    )
    qtbot.addWidget(pane)
    pane._refresh_btn.click()
    cb.assert_called_once_with("openai")


def test_pane_set_busy_disables_refresh(qtbot):
    cb = MagicMock()
    pane = ProviderPane(
        "openai",
        ProviderConfig(api_key="k"),
        require_base_url=False,
        base_url_presets=None,
        on_refresh=cb,
    )
    qtbot.addWidget(pane)
    pane.set_busy(True)
    assert pane._refresh_btn.isEnabled() is False
    pane.set_busy(False)
    assert pane._refresh_btn.isEnabled() is True


def test_pane_set_model_count_updates_label(qtbot):
    cb = MagicMock()
    pane = ProviderPane(
        "openai",
        ProviderConfig(api_key="k"),
        require_base_url=False,
        base_url_presets=None,
        on_refresh=cb,
    )
    qtbot.addWidget(pane)
    pane.set_model_count(7)
    assert "7" in pane._count_label.text()
