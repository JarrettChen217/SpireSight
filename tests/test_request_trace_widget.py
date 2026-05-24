from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import pytest


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _trace(*, finished: bool = False):
    from spiresight.core.request_trace import RequestTrace, RequestTraceStep

    started = time.monotonic() - 2.0
    return RequestTrace(
        started_at=started,
        finished_at=started + 2.0 if finished else None,
        summary="Calling model",
        steps=(
            RequestTraceStep("capture", "Capture screenshot", "done", elapsed_ms=10),
            RequestTraceStep("model", "Call model", "running" if not finished else "done"),
        ),
    )


def test_trace_widget_toggles_expanded_state(qtbot, qtwidgets_app):
    from spiresight.ui.widgets.request_trace_widget import RequestTraceWidget

    widget = RequestTraceWidget()
    qtbot.addWidget(widget)
    widget.set_trace(_trace())
    assert widget.is_expanded_for_test() is False
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton)
    assert widget.is_expanded_for_test() is True
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton)
    assert widget.is_expanded_for_test() is False


def test_trace_widget_completion_collapses_and_keeps_total(qtbot, qtwidgets_app):
    from spiresight.ui.widgets.request_trace_widget import RequestTraceWidget

    widget = RequestTraceWidget()
    qtbot.addWidget(widget)
    widget.set_trace(_trace())
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton)
    assert widget.is_expanded_for_test() is True
    widget.set_trace(_trace(finished=True))
    assert widget.is_expanded_for_test() is False
    assert "Done" in widget.summary_for_test()
    assert "00:02" in widget.summary_for_test()
