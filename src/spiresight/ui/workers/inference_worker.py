# src/spiresight/ui/workers/inference_worker.py
"""QThread wrapping InferenceRunner.

Emits one signal per chunk and one terminal signal: either finished
on success, or failed(exception) on any error (including capability/
API-key issues — UI catches and renders these as modals).
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from spiresight.core.request import InferenceRequest
from spiresight.core.runner import InferenceRunner


class InferenceWorker(QThread):
    chunk = Signal(str)              # text delta
    finished_ok = Signal()           # successful end-of-stream
    failed = Signal(object)          # exception instance

    def __init__(self, runner: InferenceRunner, request: InferenceRequest, parent=None) -> None:
        super().__init__(parent)
        self._runner = runner
        self._request = request
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            for c in self._runner.run(self._request, cancel_event=self._cancel):
                if c.text_delta:
                    self.chunk.emit(c.text_delta)
                if c.finish_reason is not None:
                    break
            self.finished_ok.emit()
        except Exception as exc:  # noqa: BLE001 — UI thread renders all errors
            self.failed.emit(exc)
