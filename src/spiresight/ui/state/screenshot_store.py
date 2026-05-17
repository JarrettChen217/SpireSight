"""Most recent screenshot bundle sent to the LLM.

Holds the frames that were attached to the latest request so the
Screenshot tab can display what the model actually saw. Not persisted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True)
class ScreenshotBundle:
    frames: tuple[bytes, ...]
    timestamp: datetime
    width: int
    height: int


class ScreenshotStore(QObject):
    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bundle: ScreenshotBundle | None = None

    def get(self) -> ScreenshotBundle | None:
        return self._bundle

    def set(self, bundle: ScreenshotBundle) -> None:
        if self._bundle is not None and self._bundle.frames == bundle.frames:
            self._bundle = bundle  # update metadata silently
            return
        self._bundle = bundle
        self.changed.emit()
