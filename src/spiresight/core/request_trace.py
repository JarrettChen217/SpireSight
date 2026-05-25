from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

TraceStatus = Literal["pending", "running", "done", "skipped", "failed"]


@dataclass(frozen=True)
class RequestTraceStep:
    key: str
    label: str
    status: TraceStatus
    detail: str = ""
    elapsed_ms: int | None = None


@dataclass(frozen=True)
class RequestTrace:
    started_at: float
    finished_at: float | None
    summary: str
    steps: tuple[RequestTraceStep, ...]

    @property
    def elapsed_seconds(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return max(0.0, end - self.started_at)

    @property
    def is_finished(self) -> bool:
        return self.finished_at is not None


def format_elapsed(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"
