from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class InspectSession(QObject):
    MAX_FRAMES = 6

    changed = Signal()  # emitted after any add_frame / remove_frame / clear

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._frames: list[bytes] = []

    @property
    def count(self) -> int:
        return len(self._frames)

    @property
    def frames(self) -> list[bytes]:
        return list(self._frames)

    def add_frame(self, png: bytes) -> None:
        if len(self._frames) >= self.MAX_FRAMES:
            raise RuntimeError(
                f"Inspect session is full ({self.MAX_FRAMES} frames). "
                "Press Done or remove a frame first."
            )
        self._frames.append(png)
        self.changed.emit()

    def remove_frame(self, index: int) -> None:
        if index < 0 or index >= len(self._frames):
            raise IndexError(f"frame index {index} out of range (count={len(self._frames)})")
        del self._frames[index]
        self.changed.emit()

    def clear(self) -> None:
        if not self._frames:
            return
        self._frames.clear()
        self.changed.emit()
