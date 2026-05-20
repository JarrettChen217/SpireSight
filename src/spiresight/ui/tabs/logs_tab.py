"""Lightweight in-memory log viewer.

Owns a vertical stack of LogRow / TextRow widgets (max 200), inserted at
the top. log() emits a TextRow for plain text events, log_cost() emits a
TextRow for cost lines, log_request() emits a LogRow for an in-flight
inference call which is later finalized via update_response().
"""
from __future__ import annotations

import logging
from datetime import datetime
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from spiresight.core.usage import CallRecord, LogStatus, RequestLog
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.widgets.log_row import LogRow, TextRow

_log = logging.getLogger(__name__)
MAX_ROWS = 200


class LogsTab(QWidget):
    def __init__(self, locale: UILocale, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._locale = locale
        self._rows: dict[str, LogRow] = {}

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

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._container = QWidget()
        self._stack = QVBoxLayout(self._container)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setSpacing(2)
        self._stack.addStretch(1)  # trailing stretch keeps rows top-aligned
        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, stretch=1)

        locale.changed.connect(self._retranslate)

    # ---- plain rows (unchanged API) ----

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._insert(TextRow(escape(f"[{ts}] {message}")))

    def log_cost(self, record: CallRecord) -> None:
        ts = record.timestamp.strftime("%H:%M:%S")
        in_tok = str(record.usage.input_tokens) if record.usage_known else "?"
        cached_tok = str(record.usage.cached_tokens) if record.usage_known else "?"
        out_tok = str(record.usage.output_tokens) if record.usage_known else "?"
        cost = f"~${record.cost_usd:.4f}" if record.cost_usd is not None else "~$—"
        text = (
            f"[{ts}] [cost] {record.model} "
            f"↑ {in_tok} ⚡{cached_tok} ↓ {out_tok} {cost} | "
            f'Q: "{record.input_preview}" | '
            f'A: "{record.output_preview}"'
        )
        self._insert(TextRow(text))

    # ---- request rows (new) ----

    def log_request(self, record: RequestLog) -> None:
        row = LogRow(record, locale=self._locale)
        self._rows[record.correlation_id] = row
        self._insert(row)

    def update_response(
        self,
        correlation_id: str,
        response: str,
        status: LogStatus,
        error: str | None = None,
    ) -> None:
        row = self._rows.get(correlation_id)
        if row is None:
            _log.debug("update_response for evicted/unknown id %s", correlation_id)
            return
        row.set_response(response, status, error)

    # ---- internals ----

    def _row_count(self) -> int:
        return max(0, self._stack.count() - 1)  # subtract trailing stretch

    def _insert(self, widget: QFrame) -> None:
        self._stack.insertWidget(0, widget)
        self._enforce_cap()

    def _enforce_cap(self) -> None:
        while self._row_count() > MAX_ROWS:
            # last layout item is the stretch; second-to-last is the oldest row
            item = self._stack.takeAt(self._stack.count() - 2)
            if item is None:
                return
            w = item.widget()
            if isinstance(w, LogRow):
                self._rows.pop(w.correlation_id, None)
            if w is not None:
                w.deleteLater()

    def _on_copy(self) -> None:
        parts: list[str] = []
        for i in range(self._stack.count() - 1):  # skip trailing stretch
            item = self._stack.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is not None and hasattr(w, "to_plain_text"):
                parts.append(w.to_plain_text())  # type: ignore[union-attr]
        QGuiApplication.clipboard().setText("\n\n---\n\n".join(parts))

    def _on_clear(self) -> None:
        while self._row_count() > 0:
            item = self._stack.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows.clear()

    def _retranslate(self) -> None:
        loc = self._locale
        self._copy_btn.setText(loc.get("logs.copy_all"))
        self._clear_btn.setText(loc.get("logs.clear"))
