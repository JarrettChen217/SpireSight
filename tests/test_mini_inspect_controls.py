from pathlib import Path

from PySide6.QtWidgets import QApplication

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


def test_badge_hidden_when_count_zero(qtwidgets_app, locale):
    from spiresight.ui.widgets.inspect_controls import MiniInspectControls
    session = InspectSession()
    w = MiniInspectControls(session, locale)
    assert w._badge.isVisible() is False or w._badge.count() == 0


def test_badge_visible_with_count(qtwidgets_app, locale):
    from spiresight.ui.widgets.inspect_controls import MiniInspectControls
    session = InspectSession()
    w = MiniInspectControls(session, locale)
    w.show()
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    assert w._badge.count() == 2
    assert w._badge.isVisible() is True


def test_capture_signal_forwarded(qtwidgets_app, locale):
    from spiresight.ui.widgets.inspect_controls import MiniInspectControls
    session = InspectSession()
    w = MiniInspectControls(session, locale)
    fired: list[int] = []
    w.capture_requested.connect(lambda: fired.append(1))
    w._capture_btn.click()
    assert fired == [1]


def test_set_capability_propagates(qtwidgets_app, locale):
    from spiresight.ui.widgets.inspect_controls import MiniInspectControls
    session = InspectSession()
    w = MiniInspectControls(session, locale)
    w.set_capability(False, "no vision")
    assert w._capture_btn.isEnabled() is False
    assert w._capture_btn.toolTip() == "no vision"


def test_set_busy_disables_all(qtwidgets_app, locale):
    from spiresight.ui.widgets.inspect_controls import MiniInspectControls
    session = InspectSession()
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    w = MiniInspectControls(session, locale)
    w.set_busy(True)
    assert w._capture_btn.isEnabled() is False
    assert w._done_btn.isEnabled() is False
