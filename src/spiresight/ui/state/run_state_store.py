from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from spiresight.core.run_state import RunState


class RunStateStore(QObject):
    changed = Signal(object)  # RunState | None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state: RunState | None = None

    def get(self) -> RunState | None:
        return self._state

    def set(self, state: RunState) -> None:
        self._state = state
        self.changed.emit(state)

    def clear(self) -> None:
        self._state = None
        self.changed.emit(None)
