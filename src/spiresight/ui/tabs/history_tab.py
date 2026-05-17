"""History tab: 220px list on the left + detail view on the right.

Selecting a row loads that entry's markdown into the detail OutputView.
Resend re-fires the entry as a new request; the wiring is done in
MainWindow (this tab only emits resend_requested(entry)).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.history_store import HistoryEntry, HistoryStore
from spiresight.ui.widgets.output_view import OutputView


class HistoryTab(QWidget):
    resend_requested = Signal(object)   # HistoryEntry

    def __init__(
        self,
        store: HistoryStore,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._locale = locale

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        # left: list
        left = QWidget()
        left.setFixedWidth(220)
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        left_l.addWidget(self._list)
        row.addWidget(left)

        # right: detail with Resend / Copy / placeholder header
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(4)

        bar = QHBoxLayout()
        self._resend_btn = QPushButton(locale.get("history.resend"))
        self._resend_btn.clicked.connect(self._on_resend)
        self._copy_btn = QPushButton(locale.get("history.copy_md"))
        self._copy_btn.clicked.connect(self._on_copy)
        bar.addWidget(self._resend_btn)
        bar.addWidget(self._copy_btn)
        bar.addStretch(1)
        right_l.addLayout(bar)

        self._detail = OutputView()
        right_l.addWidget(self._detail, stretch=1)

        self._empty_label = QLabel(locale.get("history.empty"))
        self._empty_label.setStyleSheet("color:#6e7a89;")
        right_l.addWidget(self._empty_label)

        row.addWidget(right, stretch=1)

        store.changed.connect(self._reload)
        locale.changed.connect(self._retranslate)
        self._reload()

    # ── public hooks used by MainWindow ──
    def selected_entry(self) -> HistoryEntry | None:
        idx = self._list.currentRow()
        if idx < 0 or idx >= len(self._entries):
            return None
        return self._entries[idx]

    # ── internals ──
    def _reload(self) -> None:
        self._entries: list[HistoryEntry] = self._store.entries()
        self._list.clear()
        loc = self._locale
        for e in self._entries:
            label = e.prompt_id if e.prompt_id else "custom"
            txt = loc.get(
                "history.row_format",
                time=e.timestamp.strftime("%H:%M"),
                label=label,
                model=e.model_id,
            )
            self._list.addItem(QListWidgetItem(txt))
        self._update_empty_state()
        # auto-select newest after a fresh append
        if self._entries:
            self._list.setCurrentRow(0)

    def _update_empty_state(self) -> None:
        empty = not self._entries
        self._empty_label.setVisible(empty)
        self._detail.setVisible(not empty)
        self._resend_btn.setEnabled(not empty)
        self._copy_btn.setEnabled(not empty)

    def _on_row_changed(self, idx: int) -> None:
        if 0 <= idx < len(self._entries):
            self._detail.load_static(self._entries[idx].markdown)

    def _on_resend(self) -> None:
        entry = self.selected_entry()
        if entry is not None:
            self.resend_requested.emit(entry)

    def _on_copy(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            return
        QGuiApplication.clipboard().setText(entry.markdown)

    def _retranslate(self) -> None:
        loc = self._locale
        self._resend_btn.setText(loc.get("history.resend"))
        self._copy_btn.setText(loc.get("history.copy_md"))
        self._empty_label.setText(loc.get("history.empty"))
        self._reload()
