from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from spiresight.core.messages import Message


class ConversationStore(QObject):
    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._turns: list[Message] = []

    def turns(self) -> tuple[Message, ...]:
        return tuple(self._turns)

    def append(self, message: Message) -> None:
        self._turns.append(message)
        self.changed.emit()

    def clear(self) -> None:
        self._turns.clear()
        self.changed.emit()

    def last_screenshot(self) -> bytes | None:
        for m in reversed(self._turns):
            if m.role == "user" and m.image_png is not None:
                return m.image_png
        return None
