# src/spiresight/ui/widgets/info_bubble.py
"""Floating bubble anchored below the mini-bar.

Shows streaming markdown responses with a chat input for follow-up
questions. Frameless tool window, styled via dark_fantasy.qss.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QBrush, QColor, QPen, QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizeGrip,
    QToolButton, QVBoxLayout, QWidget,
)

from spiresight.core.messages import Message
from spiresight.core.usage import TokenUsage
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.widgets.conversation_transcript import ConversationTranscript
from spiresight.ui.widgets.output_view import TranscriptScrollMode

BUBBLE_WIDTH = 360
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
    stop_requested = Signal()
    clear_context_requested = Signal()
    follow_up_requested = Signal(str, bool)   # (text, recapture) — recapture ignored; see MainWindow
    attach_screenshot_toggled = Signal(bool)
    size_changed = Signal(QSize)

    def __init__(
        self,
        locale: UILocale,
        *,
        transcript_mode: TranscriptScrollMode = "compact",
        assistant_max_height: int = 200,
        parent=None,
    ) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setObjectName("info-bubble")
        self._locale = locale
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

        self._clear_btn = QPushButton()
        self._clear_btn.setObjectName("bubble-clear")
        self._clear_btn.clicked.connect(self.clear_context_requested.emit)

        close_btn = QPushButton("×")
        close_btn.setObjectName("bubble-close")
        close_btn.setFixedSize(24, 24)
        close_btn.clicked.connect(self.closed.emit)
        close_btn.clicked.connect(self.hide)

        title_row.addWidget(self._chip)
        title_row.addWidget(self._model_label)
        title_row.addStretch(1)
        title_row.addWidget(self._clear_btn)
        title_row.addWidget(close_btn)
        root.addWidget(title)

        self._transcript = ConversationTranscript(
            transcript_mode=transcript_mode,
            assistant_max_height=assistant_max_height,
        )
        root.addWidget(self._transcript, stretch=1)

        # controls row
        controls = QWidget()
        controls.setObjectName("bubble-controls")
        ctrl_row = QHBoxLayout(controls)
        ctrl_row.setContentsMargins(12, 6, 12, 6)

        self._cost_label = QLabel("")
        self._cost_label.setTextFormat(Qt.TextFormat.RichText)

        ctrl_row.addWidget(self._cost_label)
        ctrl_row.addStretch(1)
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
        self._cam_btn.setToolTip("Attach a screenshot to the next message")
        self._cam_btn.setFixedSize(28, 28)
        self._cam_btn.toggled.connect(self.attach_screenshot_toggled.emit)

        self._input = QLineEdit()
        self._input.setObjectName("bubble-input")
        self._input.setPlaceholderText("追问…")
        self._input.returnPressed.connect(self._on_send_btn)

        self._send_btn = QPushButton("↵")
        self._send_btn.setObjectName("bubble-send")
        self._send_btn.setFixedSize(32, 28)
        self._send_btn.clicked.connect(self._on_send_btn)

        ir.addWidget(self._cam_btn)
        ir.addWidget(self._input, stretch=1)
        ir.addWidget(self._send_btn)
        root.addWidget(input_row)

        # tail pointer — overlay widget at top-center, pointing up toward mini-bar
        self._tail = _TailWidget(self)

        # size constraints
        self.setMinimumSize(280, 140)
        raw_max = QGuiApplication.primaryScreen().availableSize() * 0.8
        self.setMaximumSize(QSize(int(raw_max.width()), int(raw_max.height())))

        # resize grip (bottom-right, absolute positioned)
        self._grip = QSizeGrip(self)
        self._grip.setFixedSize(14, 14)

        # debounce timer for size_changed signal
        self._size_debounce = QTimer(self)
        self._size_debounce.setSingleShot(True)
        self._size_debounce.setInterval(300)
        self._size_debounce.timeout.connect(
            lambda: self.size_changed.emit(self.size())
        )

        locale.changed.connect(self._retranslate)
        self.resize(BUBBLE_WIDTH, 240)
        self._reposition_tail()
        self._reposition_grip()
        self._retranslate()

    @property
    def transcript(self) -> ConversationTranscript:
        return self._transcript

    def set_transcript_mode(
        self,
        mode: TranscriptScrollMode,
        *,
        assistant_max_height: int | None = None,
    ) -> None:
        self._transcript.set_transcript_mode(
            mode, assistant_max_height=assistant_max_height
        )

    # public API

    def reset(self) -> None:
        self._transcript.reset()
        self._cost_label.clear()
        self._streaming = False
        self._apply_send_button_style()

    def append_user_message(self, text: str, *, image_png: bytes | None = None) -> None:
        self._transcript.append_user_message(text, image_png=image_png)

    def begin_assistant_turn(self) -> None:
        self._transcript.begin_assistant_turn()

    def update_trace(self, trace) -> None:
        self._transcript.update_trace(trace)

    def append_delta(self, text: str) -> None:
        self._transcript.append_delta(text)

    def finalize(self) -> None:
        self._transcript.finalize()
        self.set_streaming(False)

    def set_streaming(self, active: bool) -> None:
        self._streaming = active
        self._apply_send_button_style()

    def set_cost(self, cost_usd: float | None, usage: TokenUsage | None) -> None:
        parts: list[str] = []
        if cost_usd is not None:
            parts.append(
                f'<span style="color:#4ade80;">●</span>'
                f' <span style="color:#6e7a89;">${cost_usd:.4f}</span>'
            )
        if usage is not None:
            parts.append(
                f'<span style="color:#6e7a89;">{usage.input_tokens} in · {usage.cached_tokens} cached'
                f' / {usage.output_tokens} out</span>'
            )
        if parts:
            self._cost_label.setText(" · ".join(parts))

    def set_title(self, action_label: str, model_id: str) -> None:
        self._chip.setText(action_label)
        self._model_label.setText(model_id)

    def is_empty(self) -> bool:
        return self._transcript.is_empty()

    def set_attach_screenshot(self, value: bool) -> None:
        self._cam_btn.blockSignals(True)
        self._cam_btn.setChecked(value)
        self._cam_btn.blockSignals(False)

    def render_history(self, turns: tuple[Message, ...]) -> None:
        """Replay conversation from store."""
        if not turns:
            return
        self.reset()
        self._transcript.render_turns(turns)

    def apply_size(self, size: QSize) -> None:
        clamped = QSize(
            max(self.minimumWidth(),  min(self.maximumWidth(),  size.width())),
            max(self.minimumHeight(), min(self.maximumHeight(), size.height())),
        )
        self.resize(clamped)
        self._reposition_tail()
        self._reposition_grip()
        self._size_debounce.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_tail()
        self._reposition_grip()
        self._size_debounce.start()

    def _reposition_tail(self) -> None:
        self._tail.move((self.width() - TAIL_SIZE) // 2, -TAIL_SIZE)

    def _reposition_grip(self) -> None:
        self._grip.move(self.width() - 16, self.height() - 16)
        self._grip.raise_()

    def move_anchored(self, anchor_pos: QPoint) -> None:
        x = anchor_pos.x() - self.width() // 2
        y = anchor_pos.y() + TAIL_SIZE
        self.move(x, y)

    def _apply_send_button_style(self) -> None:
        if self._streaming:
            self._send_btn.setObjectName("stop")
            self._send_btn.setText(self._locale.get("compose.stop"))
        else:
            self._send_btn.setObjectName("bubble-send")
            self._send_btn.setText("↵")
        self._send_btn.style().unpolish(self._send_btn)
        self._send_btn.style().polish(self._send_btn)

    def _retranslate(self) -> None:
        self._clear_btn.setText(self._locale.get("chat.clear_context"))
        self._clear_btn.setToolTip(self._locale.get("chat.clear_context"))
        self._apply_send_button_style()

    # internals

    def _on_send_btn(self) -> None:
        if self._streaming:
            self.stop_requested.emit()
            return
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.follow_up_requested.emit(text, self._cam_btn.isChecked())
