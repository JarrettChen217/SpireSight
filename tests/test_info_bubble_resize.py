from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

import pytest

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.widgets.info_bubble import InfoBubble


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def locale(tmp_path: Path) -> UILocale:
    en = tmp_path / "en"
    en.mkdir()
    (en / "ui_strings.yaml").write_text(
        "chat:\n"
        "  clear_context: 'Clear'\n"
        "compose:\n"
        "  send: 'Send'\n"
        "  stop: 'Stop'\n",
        encoding="utf-8",
    )
    return UILocale(tmp_path, language="en")


@pytest.fixture
def bubble(locale: UILocale) -> InfoBubble:
    return InfoBubble(locale)


def test_apply_size_resizes_within_bounds(bubble):
    bubble.apply_size(QSize(500, 300))
    assert bubble.width() == 500
    assert bubble.height() == 300


def test_apply_size_clamps_below_min(bubble):
    bubble.apply_size(QSize(50, 50))
    assert bubble.width() == bubble.minimumWidth()
    assert bubble.height() == bubble.minimumHeight()
    assert bubble.minimumWidth() == 280
    assert bubble.minimumHeight() == 140


def test_apply_size_clamps_above_max(bubble):
    huge = QSize(9999, 9999)
    bubble.apply_size(huge)
    assert bubble.width() <= bubble.maximumWidth()
    assert bubble.height() <= bubble.maximumHeight()


def test_tail_recentered_on_resize(bubble):
    from spiresight.ui.widgets.info_bubble import TAIL_SIZE

    bubble.apply_size(QSize(500, 300))
    expected_x = (bubble.width() - TAIL_SIZE) // 2
    assert bubble._tail.x() == expected_x


def test_size_grip_present_and_bottom_right(bubble):
    bubble.apply_size(QSize(400, 260))
    assert bubble._grip is not None
    assert bubble._grip.x() + bubble._grip.width() <= bubble.width()
    assert bubble._grip.y() + bubble._grip.height() <= bubble.height()
    assert bubble._grip.x() >= bubble.width() - 32
    assert bubble._grip.y() >= bubble.height() - 32


def test_is_empty_initial_true(bubble):
    assert bubble.is_empty() is True


def test_render_history_replays_turns(bubble):
    from spiresight.core.messages import Message

    turns = (
        Message(role="user", text="hi"),
        Message(role="assistant", text="hello back"),
    )
    bubble.render_history(turns)
    assert bubble.is_empty() is False


def test_render_history_with_empty_tuple_is_noop(bubble):
    bubble.render_history(())
    assert bubble.is_empty() is True


def test_size_changed_signal_emitted_after_debounce(bubble, qtwidgets_app):
    from PySide6.QtCore import QTimer

    received: list[QSize] = []
    bubble.size_changed.connect(received.append)

    bubble.apply_size(QSize(400, 260))
    bubble.apply_size(QSize(500, 280))
    bubble.apply_size(QSize(520, 300))

    assert received == []

    end_at = [False]
    QTimer.singleShot(450, lambda: end_at.__setitem__(0, True))
    while not end_at[0]:
        QApplication.processEvents()
    assert len(received) == 1
    assert received[0] == QSize(520, 300)
