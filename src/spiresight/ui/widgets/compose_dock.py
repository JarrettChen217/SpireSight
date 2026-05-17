"""Persistent bottom-of-right-pane compose bar.

Always visible regardless of which tab is active. Owns the Custom-text
input, the Include-screenshot toggle, and the dual-purpose Send/Cancel
button. The Send button morphs into Cancel while a request is in
flight (see set_streaming).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from spiresight.prompts.ui_locale import UILocale


class _CtrlEnterTextEdit(QPlainTextEdit):
    """QPlainTextEdit that fires submit() on Ctrl/Cmd+Enter."""

    submit = Signal()
    cancel = Signal()

    def keyPressEvent(self, ev: QKeyEvent) -> None:
        mod = ev.modifiers()
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
            mod & Qt.KeyboardModifier.ControlModifier
            or mod & Qt.KeyboardModifier.MetaModifier
        ):
            self.submit.emit()
            return
        if ev.key() == Qt.Key.Key_Escape:
            self.cancel.emit()
            return
        super().keyPressEvent(ev)


class ComposeDock(QWidget):
    send_clicked = Signal(str, bool)            # text, include_screenshot
    cancel_clicked = Signal()
    include_screenshot_toggled = Signal(bool)

    def __init__(
        self,
        locale: UILocale,
        include_screenshot_default: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._locale = locale
        self._streaming = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)
        outer.setSpacing(4)

        self._text = _CtrlEnterTextEdit()
        self._text.setPlaceholderText(locale.get("compose.placeholder"))
        self._text.setFixedHeight(64)
        self._text.submit.connect(self._on_send_or_cancel)
        self._text.cancel.connect(self._on_escape)
        outer.addWidget(self._text)

        row = QHBoxLayout()
        self._screenshot_chk = QCheckBox(locale.get("compose.include_screenshot"))
        self._screenshot_chk.setChecked(include_screenshot_default)
        self._screenshot_chk.toggled.connect(self.include_screenshot_toggled.emit)
        row.addWidget(self._screenshot_chk)
        row.addStretch(1)
        self._send_btn = QPushButton(locale.get("compose.send"))
        self._send_btn.setObjectName("primary")
        self._send_btn.clicked.connect(self._on_send_or_cancel)
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

    def set_streaming(self, streaming: bool) -> None:
        self._streaming = streaming
        self._send_btn.setText(
            self._locale.get("compose.cancel") if streaming
            else self._locale.get("compose.send")
        )

    # ── internals ──
    def _on_send_or_cancel(self) -> None:
        if self._streaming:
            self.cancel_clicked.emit()
            return
        self.send_clicked.emit(self.text(), self.include_screenshot())

    def _on_escape(self) -> None:
        if self._streaming:
            self.cancel_clicked.emit()

    def _retranslate(self) -> None:
        loc = self._locale
        self._text.setPlaceholderText(loc.get("compose.placeholder"))
        self._screenshot_chk.setText(loc.get("compose.include_screenshot"))
        self._send_btn.setText(
            loc.get("compose.cancel") if self._streaming else loc.get("compose.send")
        )
