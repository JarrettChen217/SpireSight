"""Lightweight in-memory log viewer.

Owns its own ring buffer (max 200 entries). MainWindow calls `log()` for
plain text events (errors, status), and `log_cost(record)` for a
structured per-call usage row. Cost rows are HTML-styled so the [cost]
prefix can be color-tinted to scan quickly.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from html import escape

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from spiresight.core.usage import CallRecord
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.theme import USAGE_COLORS


MAX_LINES = 200


class LogsTab(QWidget):
    def __init__(
        self,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._locale = locale
        # Buffer holds HTML fragments (one per row). Plain-text rows are
        # html.escape()'d before insertion so they round-trip safely.
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

        self._view = QTextEdit()
        self._view.setReadOnly(True)
        self._view.setStyleSheet("font-family: ui-monospace, Menlo, monospace; font-size:11.5px;")
        outer.addWidget(self._view, stretch=1)

        locale.changed.connect(self._retranslate)

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._buffer.appendleft(escape(f"[{ts}] {message}"))
        self._redraw()

    def log_cost(self, record: CallRecord) -> None:
        ts = record.timestamp.strftime("%H:%M:%S")
        in_tok = str(record.usage.input_tokens) if record.usage_known else "?"
        out_tok = str(record.usage.output_tokens) if record.usage_known else "?"
        cost = f"~${record.cost_usd:.4f}" if record.cost_usd is not None else "~$—"
        line_html = (
            f'<span style="color:{USAGE_COLORS["cost_tag"]};">[{escape(ts)}] [cost]</span> '
            f'<b>{escape(record.model)}</b> '
            f'↑ {escape(in_tok)} ↓ {escape(out_tok)} {escape(cost)} | '
            f'Q: "<i>{escape(record.input_preview)}</i>" | '
            f'A: "<i>{escape(record.output_preview)}</i>"'
        )
        self._buffer.appendleft(line_html)
        self._redraw()

    def _redraw(self) -> None:
        self._view.setHtml("<br>".join(self._buffer))

    def _on_copy(self) -> None:
        # QTextEdit's toPlainText strips HTML automatically.
        QGuiApplication.clipboard().setText(self._view.toPlainText())

    def _on_clear(self) -> None:
        self._buffer.clear()
        self._view.clear()

    def _retranslate(self) -> None:
        loc = self._locale
        self._copy_btn.setText(loc.get("logs.copy_all"))
        self._clear_btn.setText(loc.get("logs.clear"))
