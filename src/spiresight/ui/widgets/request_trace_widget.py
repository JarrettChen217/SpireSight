from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from spiresight.core.request_trace import RequestTrace, format_elapsed


class RequestTraceWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("request-trace")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._trace: RequestTrace | None = None
        self._expanded = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 7, 10, 7)
        self._layout.setSpacing(5)
        self._summary = QLabel("")
        self._summary.setObjectName("request-trace-summary")
        self._summary.setWordWrap(True)
        self._details = QLabel("")
        self._details.setObjectName("request-trace-details")
        self._details.setWordWrap(True)
        self._layout.addWidget(self._summary)
        self._layout.addWidget(self._details)
        self._details.hide()

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._render)

    def set_trace(self, trace: RequestTrace) -> None:
        was_running = self._trace is not None and not self._trace.is_finished
        self._trace = trace
        if trace.is_finished:
            self._expanded = False
            self._timer.stop()
        elif not self._timer.isActive():
            self._timer.start()
        if was_running and trace.is_finished:
            self._expanded = False
        self._render()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._expanded = not self._expanded
            self._render()
            event.accept()
            return
        super().mousePressEvent(event)

    def is_expanded_for_test(self) -> bool:
        return self._expanded

    def summary_for_test(self) -> str:
        return self._summary.text()

    def _render(self) -> None:
        if self._trace is None:
            self._summary.setText("")
            self._details.hide()
            return
        elapsed = format_elapsed(self._trace.elapsed_seconds)
        if self._trace.is_finished:
            self._summary.setText(f"Done · {elapsed}")
        else:
            self._summary.setText(f"{self._trace.summary} · {elapsed}")
        if self._expanded:
            lines = []
            for step in self._trace.steps:
                detail = f" — {step.detail}" if step.detail else ""
                lines.append(f"{step.status}: {step.label}{detail}")
            self._details.setText("\n".join(lines))
            self._details.show()
        else:
            self._details.hide()
