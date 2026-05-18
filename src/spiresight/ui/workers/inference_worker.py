"""QThread wrapping InferenceRunner.

Two factory classmethods produce workers for quick-action vs follow-up
requests. The worker calls the appropriate runner method, emits text deltas,
and at end-of-stream emits a usage_recorded(CallRecord).
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from datetime import datetime, timezone

from PySide6.QtCore import QThread, Signal

from spiresight.core.request import QuickActionRequest, FollowUpRequest
from spiresight.core.messages import Message
from spiresight.core.runner import InferenceRunner
from spiresight.core.usage import CallRecord, TokenUsage, _truncate_preview
from spiresight.llm.provider import StreamChunk

RunFn = Callable[[threading.Event], Iterator[StreamChunk]]


class InferenceWorker(QThread):
    chunk = Signal(str)
    finished_ok = Signal()
    failed = Signal(object)
    run_started = Signal(str, str)   # model_id, input_preview
    usage_recorded = Signal(object)  # CallRecord
    cancelled = Signal()

    def __init__(
        self,
        runner: InferenceRunner,
        run_fn: RunFn,
        *,
        model_id: str,
        input_preview: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._runner = runner
        self._run_fn = run_fn
        self._model_id = model_id
        self._input_preview = input_preview
        self._cancel = threading.Event()

    @classmethod
    def for_quick_action(
        cls,
        runner: InferenceRunner,
        request: QuickActionRequest,
        *,
        model_id: str,
        input_preview: str,
        parent=None,
    ) -> "InferenceWorker":
        def run_fn(cancel: threading.Event) -> Iterator[StreamChunk]:
            yield from runner.run_quick_action(request, cancel_event=cancel)
        return cls(runner, run_fn, model_id=model_id, input_preview=input_preview, parent=parent)

    @classmethod
    def for_follow_up(
        cls,
        runner: InferenceRunner,
        request: FollowUpRequest,
        history: tuple[Message, ...],
        *,
        model_id: str,
        input_preview: str,
        parent=None,
    ) -> "InferenceWorker":
        def run_fn(cancel: threading.Event) -> Iterator[StreamChunk]:
            yield from runner.run_follow_up(request, history, cancel_event=cancel)
        return cls(runner, run_fn, model_id=model_id, input_preview=input_preview, parent=parent)

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        self.run_started.emit(self._model_id, self._input_preview)

        captured_usage: TokenUsage | None = None
        text_buffer: list[str] = []

        try:
            for c in self._run_fn(self._cancel):
                if self._cancel.is_set():
                    self.cancelled.emit()
                    return
                if c.text_delta:
                    text_buffer.append(c.text_delta)
                    self.chunk.emit(c.text_delta)
                if c.usage is not None:
                    captured_usage = c.usage

            if self._cancel.is_set():
                self.cancelled.emit()
                return
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(exc)
            return

        record = CallRecord(
            timestamp=datetime.now(tz=timezone.utc),
            model=self._model_id,
            usage=captured_usage if captured_usage is not None else TokenUsage(0, 0),
            usage_known=captured_usage is not None,
            cost_usd=None,
            input_preview=_truncate_preview(self._input_preview, 60),
            output_preview=_truncate_preview("".join(text_buffer), 60),
        )
        self.usage_recorded.emit(record)
        self.finished_ok.emit()
