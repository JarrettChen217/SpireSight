from PySide6.QtWidgets import QApplication

import pytest


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_default_unchecked(qtwidgets_app):
    from spiresight.ui.widgets.bubble_toggle_button import BubbleToggleButton
    btn = BubbleToggleButton()
    assert btn.isChecked() is False


def test_initial_visible_state_sets_checked(qtwidgets_app):
    from spiresight.ui.widgets.bubble_toggle_button import BubbleToggleButton
    btn = BubbleToggleButton(visible=True)
    assert btn.isChecked() is True


def test_click_emits_toggled_with_new_state(qtwidgets_app):
    from spiresight.ui.widgets.bubble_toggle_button import BubbleToggleButton
    btn = BubbleToggleButton(visible=False)
    received: list[bool] = []
    btn.toggled.connect(received.append)
    btn.click()
    assert received == [True]
    btn.click()
    assert received == [True, False]


def test_set_visible_state_does_not_emit(qtwidgets_app):
    from spiresight.ui.widgets.bubble_toggle_button import BubbleToggleButton
    btn = BubbleToggleButton(visible=False)
    received: list[bool] = []
    btn.toggled.connect(received.append)
    btn.set_visible_state(True)
    assert btn.isChecked() is True
    assert received == []


def test_set_visible_state_same_value_is_noop(qtwidgets_app):
    from spiresight.ui.widgets.bubble_toggle_button import BubbleToggleButton
    btn = BubbleToggleButton(visible=True)
    received: list[bool] = []
    btn.toggled.connect(received.append)
    btn.set_visible_state(True)
    assert received == []
