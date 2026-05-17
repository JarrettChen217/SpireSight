"""In-memory ring buffer of past inference results.

Holds up to MAX_ENTRIES entries, newest first. Not persisted to disk
in this slice (see spec §2 and §6.1).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, Signal


MAX_ENTRIES = 20


@dataclass(frozen=True)
class HistoryEntry:
    timestamp: datetime
    prompt_id: str               # quick-action id, or "custom"
    custom_text: str
    model_id: str
    include_screenshot: bool
    screenshot_png: bytes | None
    markdown: str


class HistoryStore(QObject):
    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: deque[HistoryEntry] = deque(maxlen=MAX_ENTRIES)

    def entries(self) -> list[HistoryEntry]:
        # Newest first.
        return list(reversed(self._entries))

    def append(self, entry: HistoryEntry) -> None:
        self._entries.append(entry)
        self.changed.emit()

    def clear(self) -> None:
        if not self._entries:
            return
        self._entries.clear()
        self.changed.emit()
