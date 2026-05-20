from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from spiresight.prompts.ui_locale import UILocale

from spiresight.ui.widgets.compose_dock import ComposeDock


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def locale(tmp_path: Path) -> UILocale:
    en = tmp_path / "en"
    en.mkdir()
    (en / "ui_strings.yaml").write_text(
        "compose:\n"
        "  placeholder: 'type'\n"
        "  send: 'Send'\n"
        "  cancel: 'Cancel'\n"
        "  stop: 'Stop'\n"
        "  stopped: 'Stopped'\n"
        "  include_screenshot: 'Screenshot'\n",
        encoding="utf-8",
    )
    return UILocale(tmp_path, language="en")


def test_send_clicked_emits_with_text(qtwidgets_app, locale):
    dock = ComposeDock(locale, include_screenshot_default=True)
    captured: list[tuple[str, bool]] = []
    dock.send_clicked.connect(lambda t, s: captured.append((t, s)))
    dock._text.setPlainText("hello")
    dock._send_btn.click()
    assert captured == [("hello", True)]


def test_include_screenshot_toggle_emits(qtwidgets_app, locale):
    dock = ComposeDock(locale, include_screenshot_default=True)
    seen: list[bool] = []
    dock.include_screenshot_toggled.connect(lambda v: seen.append(v))
    dock._screenshot_chk.click()
    assert seen == [False]


def test_set_streaming_swaps_button_label(qtwidgets_app, locale):
    dock = ComposeDock(locale, include_screenshot_default=True)
    assert dock._send_btn.text() == "Send"
    dock.set_streaming(True)
    assert dock._send_btn.text() == "Stop"
    assert dock._send_btn.objectName() == "stop"
    dock.set_streaming(False)
    assert dock._send_btn.text() == "Send"


def test_enter_submits_plain_text(qtwidgets_app, locale):
    dock = ComposeDock(locale, include_screenshot_default=False)
    captured: list[tuple[str, bool]] = []
    dock.send_clicked.connect(lambda t, s: captured.append((t, s)))
    dock._text.setPlainText("hello\n")
    dock._text.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    )
    QApplication.processEvents()
    assert captured == [("hello", False)]
    assert dock.text() == ""


def test_shift_enter_does_not_submit(qtwidgets_app, locale):
    dock = ComposeDock(locale, include_screenshot_default=False)
    captured: list[tuple[str, bool]] = []
    dock.send_clicked.connect(lambda t, s: captured.append((t, s)))
    dock._text.setPlainText("")
    dock._text.keyPressEvent(
        QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.ShiftModifier,
        )
    )
    QApplication.processEvents()
    assert captured == []
    assert "\n" in dock._text.toPlainText()


def test_clicking_send_while_streaming_emits_stop(qtwidgets_app, locale):
    dock = ComposeDock(locale, include_screenshot_default=True)
    stopped: list[int] = []
    dock.stop_clicked.connect(lambda: stopped.append(1))
    dock.set_streaming(True)
    dock._send_btn.click()
    assert stopped == [1]


def test_enter_while_streaming_emits_stop(qtwidgets_app, locale):
    dock = ComposeDock(locale, include_screenshot_default=False)
    stopped: list[int] = []
    dock.stop_clicked.connect(lambda: stopped.append(1))
    dock.set_streaming(True)
    dock._text.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    )
    QApplication.processEvents()
    assert stopped == [1]
