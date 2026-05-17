import pytest
from PySide6.QtWidgets import QApplication, QLabel

from spiresight.ui.tabs.tab_widget import TabWidget


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_mark_dirty_other_tab_sets_badge(qtwidgets_app):
    w = TabWidget()
    w.addTab(QLabel("a"), "A")
    w.addTab(QLabel("b"), "B")
    w.setCurrentIndex(0)
    w.mark_dirty(1)
    assert w.tabText(1).endswith("●")


def test_mark_dirty_active_tab_is_noop(qtwidgets_app):
    w = TabWidget()
    w.addTab(QLabel("a"), "A")
    w.addTab(QLabel("b"), "B")
    w.setCurrentIndex(1)
    w.mark_dirty(1)
    assert w.tabText(1) == "B"


def test_switching_to_dirty_tab_clears_badge(qtwidgets_app):
    w = TabWidget()
    w.addTab(QLabel("a"), "A")
    w.addTab(QLabel("b"), "B")
    w.setCurrentIndex(0)
    w.mark_dirty(1)
    assert w.tabText(1).endswith("●")
    w.setCurrentIndex(1)
    assert w.tabText(1) == "B"
