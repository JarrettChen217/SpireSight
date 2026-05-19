"""Integration tests for mini-mode UI expansion wiring."""
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

import pytest


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def main_window(qtwidgets_app, tmp_path, monkeypatch):
    """Construct a MainWindow with on-disk config in tmp_path."""
    from spiresight.config.schema import AppConfig
    from spiresight.config.store import ConfigStore
    from spiresight.core.conversation import ConversationStore
    from spiresight.core.usage import PricingTable
    from spiresight.prompts.loader import PromptLoader
    from spiresight.ui.windows.main_window import MainWindow

    cfg = AppConfig()
    store = ConfigStore(tmp_path / "config.json")
    store.save(cfg)
    repo_prompts = Path(__file__).resolve().parents[1] / "prompts"
    loader = PromptLoader(repo_prompts)
    pricing = PricingTable({})
    conv = ConversationStore()
    w = MainWindow(cfg, store, loader, pricing=pricing, conversation_store=conv)
    yield w
    w.close()


def test_toggle_mini_bar_initializes_widgets(main_window):
    main_window._toggle_mini_bar()
    assert main_window._mini_bar is not None
    assert main_window._bubble is not None


def test_minibar_bubble_toggle_off_hides_bubble(main_window):
    main_window._toggle_mini_bar()
    main_window._bubble.show()
    main_window._on_minibar_bubble_toggled(False)
    assert main_window._bubble.isVisible() is False


def test_bubble_closed_syncs_button(main_window):
    main_window._toggle_mini_bar()
    main_window._mini_bar.set_bubble_visible(True)
    main_window._on_bubble_closed()
    assert main_window._mini_bar._bubble_btn.isChecked() is False


def test_bubble_size_changed_writes_config(main_window):
    main_window._toggle_mini_bar()
    main_window._on_bubble_size_changed(QSize(520, 320))
    assert main_window._config.bubble_width == 520
    assert main_window._config.bubble_height == 320


def test_inspect_capability_pushed_on_minibar_entry(main_window):
    main_window._toggle_mini_bar()
    main_window._mini_bar.set_inspect_capability(False, "test off")
    assert main_window._mini_bar._inspect._capture_btn.toolTip() == "test off"


def test_inspect_busy_propagates_to_minibar(main_window):
    main_window._toggle_mini_bar()
    main_window._mini_bar.set_inspect_busy(True)
    assert main_window._mini_bar._inspect._capture_btn.isEnabled() is False


def test_quick_action_sets_minibar_bubble_visible(main_window):
    main_window._toggle_mini_bar()
    main_window._bubble.show()
    main_window._mini_bar.set_bubble_visible(True)
    assert main_window._mini_bar._bubble_btn.isChecked() is True
