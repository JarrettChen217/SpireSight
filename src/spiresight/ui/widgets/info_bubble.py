# src/spiresight/ui/widgets/info_bubble.py
"""Floating bubble anchored below the mini-bar.

Shows streaming markdown responses with a chat input for follow-up
questions. Frameless tool window, styled via dark_fantasy.qss.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QBrush, QColor, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)

from spiresight.core.usage import TokenUsage
from spiresight.ui.widgets.output_view import OutputView

BUBBLE_WIDTH = 360
BUBBLE_MAX_HEIGHT = 200
TAIL_SIZE = 10


class _TailWidget(QWidget):
    """Small triangle pointer drawn at the top of the bubble."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(TAIL_SIZE, TAIL_SIZE)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.moveTo(0, TAIL_SIZE)
        path.lineTo(TAIL_SIZE // 2, 0)
        path.lineTo(TAIL_SIZE, TAIL_SIZE)
        path.closeSubpath()
        p.setBrush(QBrush(QColor("#0d1018")))
        p.setPen(QPen(QColor("#1d2233"), 1))
        p.drawPath(path)


class InfoBubble(QWidget):
    closed = Signal()
    cancel_requested = Signal()
    follow_up_requested = Signal(str, bool)   # (text, recapture)

    def __init__(self, parent=None) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setObjectName("info-bubble")
        self._streaming = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # title bar
        title = QWidget()
        title.setObjectName("bubble-title-bar")
        title_row = QHBoxLayout(title)
        title_row.setContentsMargins(12, 8, 8, 8)

        self._chip = QLabel()
        self._chip.setObjectName("bubble-chip")
        self._model_label = QLabel()
        self._model_label.setObjectName("bubble-model")

        close_btn = QPushButton("×")
        close_btn.setObjectName("bubble-close")
        close_btn.setFixedSize(24, 24)
        close_btn.clicked.connect(self.closed.emit)
        close_btn.clicked.connect(self.hide)

        title_row.addWidget(self._chip)
        title_row.addWidget(self._model_label)
        title_row.addStretch(1)
        title_row.addWidget(close_btn)
        root.addWidget(title)

        # scrollable body
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setMaximumHeight(BUBBLE_MAX_HEIGHT)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(14, 12, 14, 12)
        self._body_layout.setSpacing(8)

        self._output = OutputView()
        self._body_layout.addWidget(self._output, stretch=1)

        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll, stretch=1)

        # controls row
        controls = QWidget()
        controls.setObjectName("bubble-controls")
        ctrl_row = QHBoxLayout(controls)
        ctrl_row.setContentsMargins(12, 6, 12, 6)

        self._cost_label = QLabel("")
        self._cost_label.setTextFormat(Qt.TextFormat.RichText)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("bubble-cancel")
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)
        self._cancel_btn.hide()

        ctrl_row.addWidget(self._cost_label)
        ctrl_row.addStretch(1)
        ctrl_row.addWidget(self._cancel_btn)
        root.addWidget(controls)

        # input row
        input_row = QWidget()
        input_row.setObjectName("bubble-input-row")
        ir = QHBoxLayout(input_row)
        ir.setContentsMargins(10, 8, 10, 8)
        ir.setSpacing(6)

        self._cam_btn = QToolButton()
        self._cam_btn.setText("\U0001f4f7")
        self._cam_btn.setObjectName("bubble-camera")
        self._cam_btn.setCheckable(True)
        self._cam_btn.setToolTip("Capture new screenshot for this follow-up")
        self._cam_btn.setFixedSize(28, 28)

        self._input = QLineEdit()
        self._input.setObjectName("bubble-input")
        self._input.setPlaceholderText("追问…")
        self._input.returnPressed.connect(self._on_send)

        send_btn = QPushButton("↵")
        send_btn.setObjectName("bubble-send")
        send_btn.setFixedSize(32, 28)
        send_btn.clicked.connect(self._on_send)

        ir.addWidget(self._cam_btn)
        ir.addWidget(self._input, stretch=1)
        ir.addWidget(send_btn)
        root.addWidget(input_row)

        self.resize(BUBBLE_WIDTH, 100)

    # public API

    def reset(self) -> None:
        self._output.reset()
        self._cost_label.clear()
        self._cancel_btn.hide()
        self._streaming = False
        for i in reversed(range(self._body_layout.count())):
            w = self._body_layout.itemAt(i).widget()
            if w is not self._output:
                w.deleteLater()

    def append_user_message(self, text: str) -> None:
        label = QLabel(text)
        label.setObjectName("bubble-user-msg")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        idx = self._body_layout.indexOf(self._output)
        self._body_layout.insertWidget(idx, label)

    def append_delta(self, text: str) -> None:
        self._output.append_delta(text)

    def finalize(self) -> None:
        self._output.finalize()
        self.set_streaming(False)

    def set_streaming(self, active: bool) -> None:
        self._streaming = active
        if active:
            self._cancel_btn.show()
        else:
            self._cancel_btn.hide()

    def set_cost(self, cost_usd: float | None, usage: TokenUsage | None) -> None:
        parts: list[str] = []
        if cost_usd is not None:
            parts.append(
                f'<span style="color:#4ade80;">●</span>'
                f' <span style="color:#6e7a89;">${cost_usd:.4f}</span>'
            )
        if usage is not None:
            parts.append(
                f'<span style="color:#6e7a89;">{usage.input_tokens} in'
                f' / {usage.output_tokens} out</span>'
            )
        if parts:
            self._cost_label.setText(" · ".join(parts))

    def set_title(self, action_label: str, model_id: str) -> None:
        self._chip.setText(action_label)
        self._model_label.setText(model_id)

    def move_anchored(self, anchor_pos: QPoint) -> None:
        x = anchor_pos.x() - BUBBLE_WIDTH // 2 + TAIL_SIZE + 2
        y = anchor_pos.y() + TAIL_SIZE
        self.move(x, y)

    # internals

    def _on_send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        recapture = self._cam_btn.isChecked()
        self._input.clear()
        self._cam_btn.setChecked(False)
        self.append_user_message(text)
        self.follow_up_requested.emit(text, recapture)
