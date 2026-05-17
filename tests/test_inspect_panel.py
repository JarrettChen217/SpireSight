from pathlib import Path

from PySide6.QtWidgets import QApplication

import pytest

from spiresight.core.inspect_session import InspectSession
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.widgets.inspect_panel import InspectPanel


# InspectPanel uses QWidget which needs QApplication (not just QCoreApplication).
@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def locale(tmp_path: Path) -> UILocale:
    en = tmp_path / "en"
    en.mkdir()
    (en / "ui_strings.yaml").write_text(
        "panel:\n"
        "  capture: 'Cap'\n"
        "  done: 'Done'\n"
        "  done_busy: 'Busy'\n"
        "  clear: 'Clear'\n"
        "  max_frames: 'Max {max}'\n"
        "  no_frames: 'Need a frame'\n"
        "  empty_hint: 'hint'\n"
        "  frame_tooltip: 'Frame {n}'\n",
        encoding="utf-8",
    )
    return UILocale(tmp_path, language="en")


def test_capture_clicked_emits_signal(qtwidgets_app, locale):
    session = InspectSession()
    panel = InspectPanel(session, locale)
    fired: list[int] = []
    panel.capture_requested.connect(lambda: fired.append(1))
    panel._capture_btn.click()
    assert fired == [1]


def test_done_disabled_when_no_frames(qtwidgets_app, locale):
    session = InspectSession()
    panel = InspectPanel(session, locale)
    assert panel._done_btn.isEnabled() is False


def test_done_enabled_after_frame_added(qtwidgets_app, locale):
    session = InspectSession()
    panel = InspectPanel(session, locale)
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    assert panel._done_btn.isEnabled() is True


def test_set_capture_enabled_false_disables_buttons(qtwidgets_app, locale):
    session = InspectSession()
    panel = InspectPanel(session, locale)
    panel.set_capture_enabled(False, "no model")
    assert panel._capture_btn.isEnabled() is False
    assert panel._done_btn.isEnabled() is False
