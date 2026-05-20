"""Persistent bottom-of-right-pane compose bar.

Always visible regardless of which tab is active. Owns the Custom-text
input, the Include-screenshot toggle, and the dual-purpose Send/Stop
button. The Send button morphs into Stop while a request is in flight.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from spiresight.prompts.ui_locale import UILocale


class _ComposeTextEdit(QPlainTextEdit):
    """Enter sends; Shift+Enter inserts newline; Escape stops while streaming."""

    submit = Signal()
    stop = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._streaming = False

    def set_streaming(self, streaming: bool) -> None:
        self._streaming = streaming

    def keyPressEvent(self, ev: QKeyEvent) -> None:
        if ev.key() == Qt.Key.Key_Escape:
            if self._streaming:
                self.stop.emit()
            return
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(ev)
                return
            if self._streaming:
                self.stop.emit()
                return
            self.submit.emit()
            return
        super().keyPressEvent(ev)


class ComposeDock(QWidget):
    send_clicked = Signal(str, bool)            # text, include_screenshot
    stop_clicked = Signal()
    include_screenshot_toggled = Signal(bool)

    def __init__(
        self,
        locale: UILocale,
        attach_screenshot: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._locale = locale
        self._streaming = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)
        outer.setSpacing(4)

        self._text = _ComposeTextEdit()
        self._text.setPlaceholderText(locale.get("compose.placeholder"))
        self._text.setFixedHeight(64)
        self._text.submit.connect(self._on_send)
        self._text.stop.connect(self.stop_clicked.emit)
        outer.addWidget(self._text)

        row = QHBoxLayout()
        self._screenshot_chk = QCheckBox(locale.get("compose.include_screenshot"))
        self._screenshot_chk.setChecked(attach_screenshot)
        self._screenshot_chk.toggled.connect(self.include_screenshot_toggled.emit)
        row.addWidget(self._screenshot_chk)
        row.addStretch(1)
        self._send_btn = QPushButton(locale.get("compose.send"))
        self._send_btn.setObjectName("primary")
        self._send_btn.clicked.connect(self._on_send_btn)
        row.addWidget(self._send_btn)
        outer.addLayout(row)

        locale.changed.connect(self._retranslate)

    # ── public API ──
    def text(self) -> str:
        return self._text.toPlainText().strip()

    def clear_text(self) -> None:
        self._text.clear()

    def include_screenshot(self) -> bool:
        return self._screenshot_chk.isChecked()

    def set_attach_screenshot(self, value: bool) -> None:
        self._screenshot_chk.blockSignals(True)
        self._screenshot_chk.setChecked(value)
        self._screenshot_chk.blockSignals(False)

    def set_streaming(self, streaming: bool) -> None:
        self._streaming = streaming
        self._text.set_streaming(streaming)
        if streaming:
            self._send_btn.setObjectName("stop")
            self._send_btn.setText(self._locale.get("compose.stop"))
        else:
            self._send_btn.setObjectName("primary")
            self._send_btn.setText(self._locale.get("compose.send"))
        self._send_btn.style().unpolish(self._send_btn)
        self._send_btn.style().polish(self._send_btn)

    def is_streaming(self) -> bool:
        return self._streaming

    # ── internals ──
    def _on_send_btn(self) -> None:
        if self._streaming:
            self.stop_clicked.emit()
            return
        self._on_send()

    def _on_send(self) -> None:
        if self._streaming:
            return
        text = self.text()
        if not text:
            return
        self.send_clicked.emit(text, self.include_screenshot())
        self.clear_text()

    def _retranslate(self) -> None:
        loc = self._locale
        self._text.setPlaceholderText(loc.get("compose.placeholder"))
        self._screenshot_chk.setText(loc.get("compose.include_screenshot"))
        if self._streaming:
            self._send_btn.setText(loc.get("compose.stop"))
        else:
            self._send_btn.setText(loc.get("compose.send"))
