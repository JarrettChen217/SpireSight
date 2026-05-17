from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.tabs.logs_tab import LogsTab


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def locale(tmp_path: Path) -> UILocale:
    en = tmp_path / "en"
    en.mkdir()
    (en / "ui_strings.yaml").write_text(
        "logs:\n"
        "  empty: 'No events yet.'\n"
        "  copy_all: 'Copy'\n"
        "  clear: 'Clear'\n",
        encoding="utf-8",
    )
    return UILocale(tmp_path, language="en")


def test_starts_empty(qtwidgets_app, locale):
    tab = LogsTab(locale)
    assert tab._view.toPlainText() == ""


def test_log_appends_newest_on_top(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log("first")
    tab.log("second")
    text = tab._view.toPlainText()
    assert text.splitlines()[0].endswith("second")
    assert text.splitlines()[1].endswith("first")


def test_clear_empties(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log("a")
    tab._clear_btn.click()
    assert tab._view.toPlainText() == ""


def test_ring_buffer_caps_at_200(qtwidgets_app, locale):
    tab = LogsTab(locale)
    for i in range(250):
        tab.log(f"line-{i}")
    assert len(tab._view.toPlainText().splitlines()) == 200
    # oldest evicted: line-0 not present
    assert "line-0\n" not in tab._view.toPlainText()
    assert "line-49" not in tab._view.toPlainText()
