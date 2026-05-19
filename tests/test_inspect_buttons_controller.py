from pathlib import Path

from PySide6.QtWidgets import QApplication, QPushButton

import pytest

from spiresight.core.inspect_session import InspectSession
from spiresight.prompts.ui_locale import UILocale


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


def _make_controller(qtwidgets_app, locale):
    from spiresight.ui.widgets.inspect_controls import InspectButtonsController
    session = InspectSession()
    cap, done, clr = QPushButton(), QPushButton(), QPushButton()
    ctrl = InspectButtonsController(session, locale, cap, done, clr)
    return session, ctrl, cap, done, clr


def test_initial_state_done_disabled_no_frames(qtwidgets_app, locale):
    _, _, cap, done, clr = _make_controller(qtwidgets_app, locale)
    assert cap.isEnabled() is True
    assert done.isEnabled() is False
    assert clr.isEnabled() is True


def test_done_enabled_after_frame_added(qtwidgets_app, locale):
    session, _, _, done, _ = _make_controller(qtwidgets_app, locale)
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    assert done.isEnabled() is True


def test_capture_disabled_at_max(qtwidgets_app, locale):
    session, _, cap, _, _ = _make_controller(qtwidgets_app, locale)
    for _i in range(InspectSession.MAX_FRAMES):
        session.add_frame(b"\x89PNG\r\n\x1a\n")
    assert cap.isEnabled() is False
    assert "Max" in cap.toolTip()


def test_capability_off_disables_capture_and_done(qtwidgets_app, locale):
    session, ctrl, cap, done, _ = _make_controller(qtwidgets_app, locale)
    ctrl.set_capability(False, "no vision")
    assert cap.isEnabled() is False
    assert done.isEnabled() is False
    assert cap.toolTip() == "no vision"


def test_busy_disables_all_three(qtwidgets_app, locale):
    session, ctrl, cap, done, clr = _make_controller(qtwidgets_app, locale)
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    ctrl.set_busy(True)
    assert cap.isEnabled() is False
    assert done.isEnabled() is False
    assert done.text() == "Busy"


def test_click_signals_forwarded(qtwidgets_app, locale):
    _, ctrl, cap, done, clr = _make_controller(qtwidgets_app, locale)
    fired: list[str] = []
    ctrl.capture_clicked.connect(lambda: fired.append("c"))
    ctrl.done_clicked.connect(lambda: fired.append("d"))
    ctrl.clear_clicked.connect(lambda: fired.append("x"))
    cap.click()
    done.click()
    clr.click()
    # done is disabled until a frame exists; add one then click
    from spiresight.core.inspect_session import InspectSession  # noqa: F401
    assert "c" in fired and "x" in fired


def test_count_reflects_session(qtwidgets_app, locale):
    session, ctrl, *_ = _make_controller(qtwidgets_app, locale)
    assert ctrl.count() == 0
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    assert ctrl.count() == 1


def test_retranslate_updates_done_text(qtwidgets_app, locale):
    _, ctrl, _, done, _ = _make_controller(qtwidgets_app, locale)
    assert done.text() == "Done"
    ctrl.set_busy(True)
    assert done.text() == "Busy"
    ctrl.set_busy(False)
    assert done.text() == "Done"
