from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from uuid import uuid4

from PySide6.QtCore import QThread, Signal

from spiresight.core.run_state import RunState
from spiresight.core.runner import InferenceRunner
from spiresight.core.usage import LogStatus, RequestLog
from spiresight.llm.errors import RequestTimeoutError
from spiresight.ui.workers.inference_worker import _snapshot_to_logged_messages

_log = logging.getLogger(__name__)


class InspectWorker(QThread):
    ready = Signal(object)               # RunState
    failed = Signal(object)              # Exception
    request_logged = Signal(object)      # RequestLog
    response_logged = Signal(str, str, str, object)
    # (correlation_id, status, response_text, error_or_None)

    def __init__(
        self,
        runner: InferenceRunner,
        frames: list[bytes],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._runner = runner
        self._frames = list(frames)
        self._cancel = threading.Event()
        self._snapshot = runner.snapshot_inspect(self._frames)
        self._correlation_id = uuid4().hex[:8]

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
        self.request_logged.emit(self._build_request_log())
        status: LogStatus = "ok"
        error_msg: str | None = None
        response_text = ""
        try:
            state: RunState = self._runner.inspect(
                images=self._frames, cancel_event=self._cancel
            )
            response_text = state.model_dump_json()
            self.ready.emit(state)
        except RequestTimeoutError as exc:
            status, error_msg = "timeout", str(exc)
            self.failed.emit(exc)
        except Exception as exc:  # noqa: BLE001
            status, error_msg = "error", f"{type(exc).__name__}: {exc}"
            self.failed.emit(exc)
        finally:
            self.response_logged.emit(
                self._correlation_id, status, response_text, error_msg
            )
