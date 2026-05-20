"""Streaming markdown view.

Buffers incoming text deltas and re-renders at most every 50ms (or
every 32 deltas) to keep the UI responsive. Each flush runs the buffer
through spiresight.ui.markdown.renderer.render so we get Pygments-
highlighted code, real tables, and the shared CSS theme.
"""
from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QTimer, Slot, Qt
from PySide6.QtWidgets import QSizePolicy, QTextBrowser

from spiresight.ui.markdown.renderer import render as render_markdown

_FLUSH_INTERVAL_MS = 50
_FLUSH_DELTA_COUNT = 32

TranscriptScrollMode = Literal["compact", "expanded"]


class OutputView(QTextBrowser):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self._buffer: list[str] = []
        self._pending = 0
        self._scroll_mode: TranscriptScrollMode = "compact"
        self._max_height = 200
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush)
        self.set_scroll_mode("compact")

    def set_scroll_mode(
        self,
        mode: TranscriptScrollMode,
        *,
        max_height: int = 200,
    ) -> None:
        self._scroll_mode = mode
        self._max_height = max_height
        if mode == "compact":
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Minimum,
            )
            self.setMinimumHeight(0)
            self.setMaximumHeight(max_height)
        else:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            self.setMaximumHeight(16777215)
            self._resize_to_document()

    def reset(self) -> None:
        self._buffer.clear()
        self._pending = 0
        self.setHtml(render_markdown(""))
        if self._scroll_mode == "expanded":
            self._resize_to_document()

    def load_static(self, markdown: str) -> None:
        """Render a non-streaming markdown blob (used by HistoryTab detail)."""
        self._flush_timer.stop()
        self._buffer = [markdown]
        self._pending = 0
        self.setHtml(render_markdown(markdown))
        if self._scroll_mode == "expanded":
            self._resize_to_document()

    @Slot(str)
    def append_delta(self, text: str) -> None:
        self._buffer.append(text)
        self._pending += 1
        if self._pending >= _FLUSH_DELTA_COUNT:
            self._flush()
        elif not self._flush_timer.isActive():
            self._flush_timer.start(_FLUSH_INTERVAL_MS)

    @Slot()
    def finalize(self) -> None:
        self._flush_timer.stop()
        self._flush()

    def is_empty(self) -> bool:
        return not self._buffer

    def current_markdown(self) -> str:
        return "".join(self._buffer)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._scroll_mode == "expanded":
            self._resize_to_document()

    def _flush(self) -> None:
        self.setHtml(render_markdown("".join(self._buffer)))
        self._pending = 0
        if self._scroll_mode == "expanded":
            self._resize_to_document()
        else:
            sb = self.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _resize_to_document(self) -> None:
        doc = self.document()
        doc.setTextWidth(max(self.viewport().width(), 1))
        height = int(doc.size().height()) + 8
        self.setFixedHeight(max(height, 24))
