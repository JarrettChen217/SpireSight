from datetime import datetime, timezone
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.screenshot_store import ScreenshotBundle, ScreenshotStore
from spiresight.ui.tabs.screenshot_tab import ScreenshotTab


# 1x1 transparent PNG bytes (valid header).
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000000500010d0a2db40000000049454e44"
    "ae426082"
)


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def locale(tmp_path: Path) -> UILocale:
    en = tmp_path / "en"
    en.mkdir()
    (en / "ui_strings.yaml").write_text(
        "screenshot:\n"
        "  empty: 'No screenshot yet.'\n"
        "  save_as: 'Save as…'\n"
        "  dims_format: '{w}×{h}'\n",
        encoding="utf-8",
    )
    return UILocale(tmp_path, language="en")


def test_empty_state(qtwidgets_app, locale):
    store = ScreenshotStore()
    tab = ScreenshotTab(store, locale)
    assert tab._empty_label.isVisible() is True
    assert tab._save_btn.isEnabled() is False


def test_renders_after_set(qtwidgets_app, locale):
    store = ScreenshotStore()
    tab = ScreenshotTab(store, locale)
    bundle = ScreenshotBundle(
        frames=(_PNG_1x1,),
        timestamp=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
        width=1, height=1,
    )
    store.set(bundle)
    assert tab._empty_label.isVisible() is False
    assert tab._save_btn.isEnabled() is True
    # one frame label exists
    assert tab._frames_layout.count() >= 1
