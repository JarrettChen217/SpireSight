"""Lightweight in-memory log viewer.

Owns its own ring buffer (max 200 entries). MainWindow calls `log()`
on capability mismatches, API errors, etc. — no separate LogsStore
is needed because nothing else needs to read these entries.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from spiresight.prompts.ui_locale import UILocale


MAX_LINES = 200


class LogsTab(QWidget):
    def __init__(
        self,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._locale = locale
        self._buffer: deque[str] = deque(maxlen=MAX_LINES)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        bar = QHBoxLayout()
        self._copy_btn = QPushButton(locale.get("logs.copy_all"))
        self._copy_btn.clicked.connect(self._on_copy)
        self._clear_btn = QPushButton(locale.get("logs.clear"))
        self._clear_btn.clicked.connect(self._on_clear)
        bar.addWidget(self._copy_btn)
        bar.addWidget(self._clear_btn)
        bar.addStretch(1)
        outer.addLayout(bar)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setStyleSheet("font-family: ui-monospace, Menlo, monospace; font-size:11.5px;")
        outer.addWidget(self._view, stretch=1)

        locale.changed.connect(self._retranslate)

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._buffer.appendleft(f"[{ts}] {message}")
        self._redraw()

    def _redraw(self) -> None:
        self._view.setPlainText("\n".join(self._buffer))

    def _on_copy(self) -> None:
        QGuiApplication.clipboard().setText(self._view.toPlainText())

    def _on_clear(self) -> None:
        self._buffer.clear()
        self._view.clear()

    def _retranslate(self) -> None:
        loc = self._locale
        self._copy_btn.setText(loc.get("logs.copy_all"))
        self._clear_btn.setText(loc.get("logs.clear"))
