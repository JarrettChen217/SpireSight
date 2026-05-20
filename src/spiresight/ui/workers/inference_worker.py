"""QThread wrapping InferenceRunner.

Two factory classmethods produce workers for quick-action vs follow-up
requests. The worker calls the appropriate runner method, emits text deltas,
and at end-of-stream emits a usage_recorded(CallRecord) plus the logging
signals request_logged + response_logged.
"""
from __future__ import annotations

import io
import logging
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from uuid import uuid4

from PIL import Image
from PySide6.QtCore import QThread, Signal

from spiresight.core.request import QuickActionRequest, FollowUpRequest
from spiresight.core.messages import Message
from spiresight.core.runner import InferenceRunner, RequestSnapshot
from spiresight.core.usage import CallRecord, LoggedMessage, LogStatus, RequestLog, TokenUsage, _truncate_preview
from spiresight.llm.errors import RequestTimeoutError
from spiresight.llm.provider import StreamChunk

_log = logging.getLogger(__name__)

RunFn = Callable[[threading.Event], Iterator[StreamChunk]]


def _image_summary(png: bytes | None) -> str | None:
    if not png:
        return None
    try:
        with Image.open(io.BytesIO(png)) as im:
            return f"PNG, {len(png)//1024} KB, {im.width}×{im.height}"
    except Exception:  # noqa: BLE001
        return f"PNG, {len(png)//1024} KB"


def _snapshot_to_logged_messages(snap: RequestSnapshot) -> list[LoggedMessage]:
    return [
        LoggedMessage(role=m.role, text=m.text, image_summary=_image_summary(m.image_png))
        for m in snap.messages
    ]


class InferenceWorker(QThread):
    chunk = Signal(str)
    finished_ok = Signal()
    failed = Signal(object)
    run_started = Signal(str, str)          # model_id, input_preview
    usage_recorded = Signal(object)         # CallRecord
    cancelled = Signal()
    request_logged = Signal(object)         # RequestLog (status="sent")
    response_logged = Signal(str, str, str, object)
    # (correlation_id, status: LogStatus, response_text, error_or_None)

    def __init__(
        self,
        runner: InferenceRunner,
        run_fn: RunFn,
        *,
        model_id: str,
        input_preview: str,
        snapshot: RequestSnapshot,
        correlation_id: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._runner = runner
        self._run_fn = run_fn
        self._model_id = model_id
        self._input_preview = input_preview
        self._snapshot = snapshot
        self._correlation_id = correlation_id
        self._cancel = threading.Event()

    @classmethod
    def for_quick_action(
        cls,
        runner: InferenceRunner,
        request: QuickActionRequest,
        *,
        history: tuple[Message, ...] = (),
        model_id: str,
        input_preview: str,
        parent=None,
    ) -> "InferenceWorker":
        snap = runner.snapshot_quick_action(request, history=history)

        def run_fn(cancel: threading.Event) -> Iterator[StreamChunk]:
            yield from runner.run_quick_action(request, cancel_event=cancel)

        return cls(
            runner, run_fn,
            model_id=model_id, input_preview=input_preview,
            snapshot=snap, correlation_id=uuid4().hex[:8],
            parent=parent,
        )

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
        snap = runner.snapshot_follow_up(request, history)

        def run_fn(cancel: threading.Event) -> Iterator[StreamChunk]:
            yield from runner.run_follow_up(request, history, cancel_event=cancel)

        return cls(
            runner, run_fn,
            model_id=model_id, input_preview=input_preview,
            snapshot=snap, correlation_id=uuid4().hex[:8],
            parent=parent,
        )

    def cancel(self) -> None:
        self._cancel.set()

    def _build_request_log(self) -> RequestLog:
        return RequestLog(
            correlation_id=self._correlation_id,
            timestamp=datetime.now(tz=timezone.utc),
            provider=self._snapshot.provider,
            model=self._snapshot.model,
            system=self._snapshot.system,
            messages=_snapshot_to_logged_messages(self._snapshot),
            params=dict(self._snapshot.params),
        )

    def run(self) -> None:
        t0 = time.monotonic()
        _log.info(
            "InferenceWorker.run started  corr=%s model=%s",
            self._correlation_id, self._model_id,
        )
        self.run_started.emit(self._model_id, self._input_preview)
        self.request_logged.emit(self._build_request_log())

        captured_usage: TokenUsage | None = None
        text_buffer: list[str] = []
        status: LogStatus = "ok"
        error_msg: str | None = None
        exc_to_emit: Exception | None = None
        first_chunk_logged = False

        try:
            for c in self._run_fn(self._cancel):
                if self._cancel.is_set():
                    status = "cancelled"
                    break
                if c.text_delta:
                    if not first_chunk_logged:
                        _log.info(
                            "InferenceWorker first chunk arrived  corr=%s T+%.3fs",
                            self._correlation_id, time.monotonic() - t0,
                        )
                        first_chunk_logged = True
                    text_buffer.append(c.text_delta)
                    self.chunk.emit(c.text_delta)
                if c.usage is not None:
                    captured_usage = c.usage
            if self._cancel.is_set():
                status = "cancelled"
        except RequestTimeoutError as exc:
            status, error_msg = "timeout", str(exc)
            exc_to_emit = exc
        except Exception as exc:  # noqa: BLE001
            status, error_msg = "error", f"{type(exc).__name__}: {exc}"
            exc_to_emit = exc
        finally:
            full_text = "".join(text_buffer)
            _log.info(
                "InferenceWorker.run done  corr=%s status=%s total=%.3fs chars=%d",
                self._correlation_id, status, time.monotonic() - t0, len(full_text),
            )
            self.response_logged.emit(self._correlation_id, status, full_text, error_msg)
            if status == "cancelled":
                self.cancelled.emit()
            elif status == "ok":
                record = CallRecord(
                    timestamp=datetime.now(tz=timezone.utc),
                    model=self._model_id,
                    usage=captured_usage if captured_usage is not None else TokenUsage(0, 0),
                    usage_known=captured_usage is not None,
                    cost_usd=None,
                    input_preview=_truncate_preview(self._input_preview, 60),
                    output_preview=_truncate_preview(full_text, 60),
                )
                self.usage_recorded.emit(record)
                self.finished_ok.emit()
            else:
                assert exc_to_emit is not None
                self.failed.emit(exc_to_emit)
