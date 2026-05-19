"""Multi-turn chat transcript: one user bubble and one assistant block per turn."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from spiresight.core.messages import Message
from spiresight.ui.widgets.output_view import OutputView


class ConversationTranscript(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll)

        self._body = QWidget()
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)
        self._scroll.setWidget(self._body)

        self._active_output: OutputView | None = None
        self._turn_widgets = 0

    def reset(self) -> None:
        self._active_output = None
        self._turn_widgets = 0
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def is_empty(self) -> bool:
        return self._turn_widgets == 0 and self._active_output is None

    def append_user_message(self, text: str) -> None:
        label = QLabel(html.escape(text))
        label.setObjectName("bubble-user-msg")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        self._insert_before_stretch(label)

    def begin_assistant_turn(self) -> None:
        if self._active_output is not None:
            self._active_output.finalize()
            self._active_output = None

        wrap = QWidget()
        wrap.setObjectName("bubble-assistant-wrap")
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.setSpacing(0)

        out = OutputView()
        out.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )
        wrap_layout.addWidget(out)
        self._active_output = out
        self._insert_before_stretch(wrap)

    def append_delta(self, text: str) -> None:
        if self._active_output is None:
            self.begin_assistant_turn()
        assert self._active_output is not None
        self._active_output.append_delta(text)

    def finalize(self) -> None:
        if self._active_output is not None:
            self._active_output.finalize()
            self._active_output = None
        self._scroll_to_bottom()

    def load_static(self, markdown: str) -> None:
        """Render a single assistant block (e.g. HistoryTab detail)."""
        self.reset()
        self.begin_assistant_turn()
        assert self._active_output is not None
        self._active_output.load_static(markdown)
        self._active_output = None

    def current_markdown(self) -> str:
        if self._active_output is None:
            return ""
        return self._active_output.current_markdown()

    def render_turns(self, turns: tuple[Message, ...]) -> None:
        self.reset()
        for msg in turns:
            if msg.role == "user":
                self.append_user_message(msg.text)
            else:
                self.begin_assistant_turn()
                assert self._active_output is not None
                self._active_output.append_delta(msg.text)
                self.finalize()
        self._scroll_to_bottom()

    def _insert_before_stretch(self, widget: QWidget) -> None:
        idx = max(0, self._layout.count() - 1)
        if self._turn_widgets > 0:
            sep = QFrame()
            sep.setObjectName("turn-separator")
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setFixedHeight(1)
            self._layout.insertWidget(idx, sep)
            idx += 1
        self._layout.insertWidget(idx, widget)
        self._turn_widgets += 1
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
