from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

import pytest


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_apply_size_resizes_within_bounds(qtwidgets_app):
    from spiresight.ui.widgets.info_bubble import InfoBubble
    b = InfoBubble()
    b.apply_size(QSize(500, 300))
    assert b.width() == 500
    assert b.height() == 300


def test_apply_size_clamps_below_min(qtwidgets_app):
    from spiresight.ui.widgets.info_bubble import InfoBubble
    b = InfoBubble()
    b.apply_size(QSize(50, 50))
    assert b.width() == b.minimumWidth()
    assert b.height() == b.minimumHeight()
    assert b.minimumWidth() == 280
    assert b.minimumHeight() == 140


def test_apply_size_clamps_above_max(qtwidgets_app):
    from spiresight.ui.widgets.info_bubble import InfoBubble
    b = InfoBubble()
    huge = QSize(9999, 9999)
    b.apply_size(huge)
    assert b.width() <= b.maximumWidth()
    assert b.height() <= b.maximumHeight()


def test_tail_recentered_on_resize(qtwidgets_app):
    from spiresight.ui.widgets.info_bubble import InfoBubble, TAIL_SIZE
    b = InfoBubble()
    b.apply_size(QSize(500, 300))
    expected_x = (b.width() - TAIL_SIZE) // 2
    assert b._tail.x() == expected_x


def test_size_grip_present_and_bottom_right(qtwidgets_app):
    from spiresight.ui.widgets.info_bubble import InfoBubble
    b = InfoBubble()
    b.apply_size(QSize(400, 260))
    assert b._grip is not None
    assert b._grip.x() + b._grip.width() <= b.width()
    assert b._grip.y() + b._grip.height() <= b.height()
    assert b._grip.x() >= b.width() - 32
    assert b._grip.y() >= b.height() - 32


def test_size_changed_signal_emitted_after_debounce(qtwidgets_app):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from spiresight.ui.widgets.info_bubble import InfoBubble
    b = InfoBubble()
    received: list[QSize] = []
    b.size_changed.connect(received.append)

    b.apply_size(QSize(400, 260))
    b.apply_size(QSize(500, 280))
    b.apply_size(QSize(520, 300))

    assert received == []  # debounce not fired yet

    end_at = [False]
    QTimer.singleShot(450, lambda: end_at.__setitem__(0, True))
    while not end_at[0]:
        QApplication.processEvents()
    assert len(received) == 1
    assert received[0] == QSize(520, 300)
