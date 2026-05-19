from pathlib import Path

from PySide6.QtWidgets import QApplication

import pytest

from spiresight.core.inspect_session import InspectSession
from spiresight.prompts.loader import PromptLoader
from spiresight.prompts.ui_locale import UILocale


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def loader(tmp_path: Path) -> PromptLoader:
    qa_dir = tmp_path / "quick_actions"
    qa_dir.mkdir()
    (qa_dir / "demo.yaml").write_text(
        "id: demo\nlabel: 'Demo'\nlabel_zh: '演示'\n"
        "system_prompt: 'sys'\nuser_template: 'u'\nrequires_screenshot: false\n",
        encoding="utf-8",
    )
    return PromptLoader(tmp_path)


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


def test_mini_bar_constructs(qtwidgets_app, loader, locale):
    from spiresight.ui.widgets.mini_bar import MiniBar
    session = InspectSession()
    bar = MiniBar(loader, hotkey_hint="Ctrl+X", inspect_session=session, locale=locale)
    assert bar is not None


def test_set_bubble_visible_syncs_button(qtwidgets_app, loader, locale):
    from spiresight.ui.widgets.mini_bar import MiniBar
    session = InspectSession()
    bar = MiniBar(loader, "Ctrl+X", inspect_session=session, locale=locale)
    bar.set_bubble_visible(True)
    assert bar._bubble_btn.isChecked() is True
    bar.set_bubble_visible(False)
    assert bar._bubble_btn.isChecked() is False


def test_bubble_toggle_emits_signal(qtwidgets_app, loader, locale):
    from spiresight.ui.widgets.mini_bar import MiniBar
    session = InspectSession()
    bar = MiniBar(loader, "Ctrl+X", inspect_session=session, locale=locale)
    received: list[bool] = []
    bar.bubble_toggle_requested.connect(received.append)
    bar._bubble_btn.click()
    assert received == [True]


def test_inspect_capture_forwarded(qtwidgets_app, loader, locale):
    from spiresight.ui.widgets.mini_bar import MiniBar
    session = InspectSession()
    bar = MiniBar(loader, "Ctrl+X", inspect_session=session, locale=locale)
    fired: list[int] = []
    bar.inspect_capture_requested.connect(lambda: fired.append(1))
    bar._inspect._capture_btn.click()
    assert fired == [1]


def test_set_inspect_capability_propagates(qtwidgets_app, loader, locale):
    from spiresight.ui.widgets.mini_bar import MiniBar
    session = InspectSession()
    bar = MiniBar(loader, "Ctrl+X", inspect_session=session, locale=locale)
    bar.set_inspect_capability(False, "off")
    assert bar._inspect._capture_btn.isEnabled() is False
    assert bar._inspect._capture_btn.toolTip() == "off"


def test_set_inspect_busy_propagates(qtwidgets_app, loader, locale):
    from spiresight.ui.widgets.mini_bar import MiniBar
    session = InspectSession()
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    bar = MiniBar(loader, "Ctrl+X", inspect_session=session, locale=locale)
    bar.set_inspect_busy(True)
    assert bar._inspect._capture_btn.isEnabled() is False
    assert bar._inspect._done_btn.isEnabled() is False
