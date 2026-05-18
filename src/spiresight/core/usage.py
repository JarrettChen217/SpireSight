"""Pure-Python token usage data types and helpers.

Qt-aware classes (UsageTracker) live in this file too, but the dataclasses
below have no Qt dependencies and are safe to import from headless tests.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from PySide6.QtCore import QObject, Signal

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class CallRecord:
    timestamp: datetime
    model: str
    usage: TokenUsage
    usage_known: bool
    cost_usd: float | None
    input_preview: str
    output_preview: str


def _truncate_preview(text: str, max_chars: int = 60) -> str:
    """Collapse whitespace, then cut to max_chars on a word boundary.

    Returns text unchanged when shorter than the limit. Appends "…" only
    when the text was actually truncated. Newlines are flattened to spaces
    so a multi-line prompt shows as a single readable line.
    """
    flat = " ".join(text.split())
    if len(flat) <= max_chars:
        return flat
    head = flat[:max_chars]
    # Snap back to the last whitespace within the head, if any.
    cut = head.rfind(" ")
    if cut > 0:
        head = head[:cut]
    return f"{head.rstrip()}…"


class PricingTable:
    """USD-per-1M-token lookup, loaded from a YAML file.

    Schema per entry:
        <model_id>:
          input_per_1m: <non-negative float>
          output_per_1m: <non-negative float>

    Missing file, malformed YAML, or invalid entries do NOT raise — they
    yield an empty (or partial) table and log a single warning. Callers
    receive None from compute() when a model isn't priced, and render
    that as a dash in the UI.
    """

    def __init__(self, rates: dict[str, tuple[float, float]]) -> None:
        self._rates = rates

    @classmethod
    def load(cls, yaml_path: Path) -> "PricingTable":
        try:
            text = yaml_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            _log.warning("prices file not found: %s — pricing disabled", yaml_path)
            return cls({})
        except OSError as exc:
            _log.warning("prices file unreadable (%s): %s — pricing disabled", yaml_path, exc)
            return cls({})

        try:
            raw = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            _log.warning("prices file malformed (%s): %s — pricing disabled", yaml_path, exc)
            return cls({})

        rates: dict[str, tuple[float, float]] = {}
        if not isinstance(raw, dict):
            _log.warning("prices file top-level is not a mapping: %s", yaml_path)
            return cls({})

        for model_id, entry in raw.items():
            if not isinstance(entry, dict):
                _log.warning("prices entry for %r is not a mapping; skipped", model_id)
                continue
            inp = entry.get("input_per_1m")
            out = entry.get("output_per_1m")
            if not _is_non_negative_number(inp) or not _is_non_negative_number(out):
                _log.warning(
                    "prices entry for %r has invalid input/output rates; skipped",
                    model_id,
                )
                continue
            rates[str(model_id)] = (float(inp), float(out))

        return cls(rates)

    def compute(self, model_id: str, usage: TokenUsage) -> float | None:
        rate = self._rates.get(model_id)
        if rate is None:
            return None
        in_rate, out_rate = rate
        return (usage.input_tokens / 1_000_000) * in_rate + (usage.output_tokens / 1_000_000) * out_rate


def _is_non_negative_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


Status = Literal["idle", "running", "ok", "error"]
_MAX_RECORDS = 200


class UsageTracker(QObject):
    """In-memory session usage store.

    Owns the deque of recent CallRecords, running totals (sum of input
    tokens, sum of output tokens, sum of cost across priced calls only),
    and a status string that drives the UsageBar's light. Emits Qt
    signals on every mutation so UI surfaces re-render.

    The tracker is intentionally per-process and per-session: it has no
    persistence layer, so an app restart begins with a clean slate.
    """

    call_recorded = Signal(object)   # CallRecord
    totals_changed = Signal()
    status_changed = Signal(str)     # one of: idle | running | ok | error

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._records: deque[CallRecord] = deque(maxlen=_MAX_RECORDS)
        self._sum_input = 0
        self._sum_output = 0
        self._sum_cost_priced = 0.0
        self._has_unpriced = False
        self._status: Status = "idle"
        self._prior_status: Status = "idle"

    # ---- read-only state ----

    @property
    def totals(self) -> TokenUsage:
        return TokenUsage(self._sum_input, self._sum_output)

    @property
    def total_cost_usd(self) -> float | None:
        # None when nothing priced has been recorded yet.
        if self._sum_cost_priced == 0.0 and not any(
            r.cost_usd is not None for r in self._records
        ):
            return None
        return self._sum_cost_priced

    @property
    def has_unpriced_calls(self) -> bool:
        return self._has_unpriced

    @property
    def last_status(self) -> str:
        return self._status

    @property
    def records(self) -> list[CallRecord]:
        # most-recent-first
        return list(reversed(self._records))

    # ---- mutations ----

    def call_started(self, model: str, input_preview: str) -> None:
        # `model` and `input_preview` are not stored on the tracker — the
        # worker carries them and supplies them again on completion. They
        # are accepted here so future telemetry can attribute the running
        # call without changing the public API.
        del model, input_preview
        self._prior_status = self._status
        self._set_status("running")

    def call_completed_ok(self, record: CallRecord) -> None:
        self._records.append(record)
        self._sum_input += record.usage.input_tokens
        self._sum_output += record.usage.output_tokens
        if record.cost_usd is not None:
            self._sum_cost_priced += record.cost_usd
        else:
            self._has_unpriced = True
        self.call_recorded.emit(record)
        self.totals_changed.emit()
        self._set_status("ok")

    def call_failed(self, reason: str) -> None:
        del reason
        self._set_status("error")

    def call_cancelled(self) -> None:
        self._set_status(self._prior_status)

    def _set_status(self, new: Status) -> None:
        if new == self._status:
            return
        self._status = new
        self.status_changed.emit(new)
