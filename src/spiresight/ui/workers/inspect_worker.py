from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from spiresight.core.run_state import RunState
from spiresight.core.runner import InferenceRunner


class InspectWorker(QThread):
    ready = Signal(object)   # RunState
    failed = Signal(object)  # Exception

    def __init__(self, runner: InferenceRunner, parent=None) -> None:
        super().__init__(parent)
        self._runner = runner
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            state: RunState = self._runner.inspect(cancel_event=self._cancel)
            self.ready.emit(state)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(exc)
