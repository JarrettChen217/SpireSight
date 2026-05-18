# src/spiresight/ui/workers/inference_worker.py
"""QThread wrapping InferenceRunner.

Emits text deltas as they arrive, and at end-of-stream emits a structured
`usage_recorded(CallRecord)` that downstream surfaces (UsageTracker,
LogsTab) consume. The worker does NOT price calls itself — `cost_usd`
is set to None here; MainWindow attaches a price via PricingTable before
forwarding the record to the tracker.

Why not break on finish_reason: OpenAI's `stream_options.include_usage`
sends the `usage` block in a SEPARATE chunk AFTER the finish_reason
chunk. Breaking early would drop it.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from PySide6.QtCore import QThread, Signal

from spiresight.core.request import InferenceRequest
from spiresight.core.runner import InferenceRunner
from spiresight.core.usage import CallRecord, TokenUsage, _truncate_preview


class InferenceWorker(QThread):
    chunk = Signal(str)              # text delta (existing)
    finished_ok = Signal()           # successful end-of-stream (existing)
    failed = Signal(object)          # exception instance (existing)
    run_started = Signal(str, str)   # NEW: (model_id, input_preview)
    usage_recorded = Signal(object)  # NEW: CallRecord
    cancelled = Signal()             # NEW: emitted when run was cancelled mid-flight

    def __init__(
        self,
        runner: InferenceRunner,
        request: InferenceRequest,
        *,
        model_id: str,
        input_preview: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._runner = runner
        self._request = request
        self._model_id = model_id
        self._input_preview = input_preview
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        self.run_started.emit(self._model_id, self._input_preview)

        captured_usage: TokenUsage | None = None
        text_buffer: list[str] = []

        try:
            for c in self._runner.run(self._request, cancel_event=self._cancel):
                if self._cancel.is_set():
                    self.cancelled.emit()
                    return
                if c.text_delta:
                    text_buffer.append(c.text_delta)
                    self.chunk.emit(c.text_delta)
                if c.usage is not None:
                    captured_usage = c.usage
                # NOTE: we no longer break on finish_reason; the iterator
                # naturally ends after [DONE] / generator exhaustion.

            if self._cancel.is_set():
                self.cancelled.emit()
                return
        except Exception as exc:  # noqa: BLE001 — UI thread renders all errors
            self.failed.emit(exc)
            return

        record = CallRecord(
            timestamp=datetime.now(tz=timezone.utc),
            model=self._model_id,
            usage=captured_usage if captured_usage is not None else TokenUsage(0, 0),
            usage_known=captured_usage is not None,
            cost_usd=None,  # MainWindow attaches the price before forwarding.
            input_preview=_truncate_preview(self._input_preview, 60),
            output_preview=_truncate_preview("".join(text_buffer), 60),
        )
        self.usage_recorded.emit(record)
        self.finished_ok.emit()
