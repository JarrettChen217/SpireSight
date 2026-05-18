# Token Cost Tracking & Debug Panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-call token accounting (LogsTab `[cost]` rows) and a session-cumulative `UsageBar` in the bottom status bar, fed by exact `usage` numbers returned by OpenAI's streaming API, with cost computed from a hardcoded `prices.yaml`.

**Architecture:** New pure-Python `core/usage.py` (`TokenUsage`, `CallRecord`, `PricingTable`, `UsageTracker(QObject)`) owns all session state. `StreamChunk` gains an optional `usage` field; the OpenAI provider sets `stream_options.include_usage=true` and parses the trailing usage chunk. `InferenceWorker` gains three signals (`run_started`, `usage_recorded`, `cancelled`). `LogsTab` switches to `QTextEdit` to support color; `UsageBar` is a new permanent widget mounted via `QStatusBar.addPermanentWidget`. Session resets on app restart (no persistence).

**Tech Stack:** Python 3, PySide6, pydantic, PyYAML, httpx, pytest, respx. Repo uses ruff + pytest-qt offscreen.

**Branch:** `feat/token-cost-debug` (already checked out).

**Spec:** `docs/superpowers/specs/2026-05-17-token-cost-debug-design.md`.

---

## File map

**Create:**
- `src/spiresight/core/usage.py` — `TokenUsage`, `CallRecord`, `_truncate_preview`, `PricingTable`, `UsageTracker`
- `src/spiresight/ui/widgets/usage_bar.py` — bottom-bar widget
- `config/prices.yaml` — hardcoded pricing table
- `tests/test_pricing_table.py`
- `tests/test_usage_tracker.py`
- `tests/test_usage_helpers.py` — covers `TokenUsage`, `CallRecord`, `_truncate_preview`
- `tests/test_usage_bar.py`
- `tests/test_inference_worker_usage_flow.py`

**Modify:**
- `src/spiresight/llm/provider.py` — add `usage: TokenUsage | None` to `StreamChunk`
- `src/spiresight/llm/providers/openai_provider.py` — add `stream_options.include_usage=true`, parse trailing usage chunk
- `src/spiresight/ui/workers/inference_worker.py` — new signals, don't break on `finish_reason`, capture usage, accept `model_id` + `input_preview`
- `src/spiresight/ui/tabs/logs_tab.py` — `QPlainTextEdit` → `QTextEdit`, add `log_cost(record)`
- `src/spiresight/ui/theme.py` — add color tokens
- `src/spiresight/ui/windows/main_window.py` — instantiate `UsageTracker`, mount `UsageBar`, wire signals, update worker construction sites
- `src/spiresight/app.py` — load `PricingTable` at startup, pass through to `MainWindow`
- `prompts/locales/en/ui_strings.yaml` — add `usage.*` keys
- `prompts/locales/zh/ui_strings.yaml` — add `usage.*` keys
- `tests/test_openai_provider.py` — add three new tests for usage (include the existing chunk's payload format)
- `tests/test_logs_tab.py` — add tests for `log_cost`

---

## Task 1: TokenUsage, CallRecord, _truncate_preview

**Files:**
- Create: `src/spiresight/core/usage.py`
- Test: `tests/test_usage_helpers.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_usage_helpers.py`:

```python
from datetime import datetime, timezone

import pytest

from spiresight.core.usage import CallRecord, TokenUsage, _truncate_preview


def test_token_usage_is_frozen_and_holds_ints():
    u = TokenUsage(input_tokens=12, output_tokens=34)
    assert u.input_tokens == 12
    assert u.output_tokens == 34
    with pytest.raises(Exception):  # FrozenInstanceError subclass of Exception
        u.input_tokens = 99  # type: ignore[misc]


def test_call_record_minimal_construction():
    ts = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)
    r = CallRecord(
        timestamp=ts,
        model="gpt-4o",
        usage=TokenUsage(10, 20),
        usage_known=True,
        cost_usd=0.0005,
        input_preview="hi",
        output_preview="there",
    )
    assert r.model == "gpt-4o"
    assert r.usage_known is True
    assert r.cost_usd == 0.0005


def test_truncate_preview_short_returns_unchanged():
    assert _truncate_preview("hello world", 60) == "hello world"


def test_truncate_preview_long_cuts_with_ellipsis():
    text = "a" * 80
    out = _truncate_preview(text, 60)
    assert out.endswith("…")
    assert len(out) <= 61  # 60 chars + the ellipsis


def test_truncate_preview_snaps_to_word_boundary():
    text = "the quick brown fox jumps over the lazy dog three times today"
    out = _truncate_preview(text, 25)
    # should not end mid-word; should end on a whitespace boundary, then "…"
    assert out.endswith("…")
    before = out[:-1].rstrip()
    assert " " not in before[-3:] or before.endswith(" ") is False
    # the word boundary rule: prefer trimming back to the last whitespace before max
    assert before in text


def test_truncate_preview_empty_string():
    assert _truncate_preview("", 60) == ""


def test_truncate_preview_collapses_newlines_to_spaces():
    out = _truncate_preview("line1\nline2\nline3", 60)
    assert "\n" not in out
    assert "line1 line2 line3" == out
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_usage_helpers.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'spiresight.core.usage'`.

- [ ] **Step 1.3: Create `src/spiresight/core/usage.py` with minimal implementation**

```python
# src/spiresight/core/usage.py
"""Pure-Python token usage data types and helpers.

Qt-aware classes (UsageTracker) live in this file too, but the dataclasses
below have no Qt dependencies and are safe to import from headless tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_usage_helpers.py -v
```

Expected: 6 passed.

- [ ] **Step 1.5: Commit**

```bash
git add src/spiresight/core/usage.py tests/test_usage_helpers.py
git commit -m "feat(usage): add TokenUsage, CallRecord, _truncate_preview"
```

---

## Task 2: PricingTable + config/prices.yaml

**Files:**
- Modify: `src/spiresight/core/usage.py`
- Create: `config/prices.yaml`
- Create: `tests/test_pricing_table.py`

- [ ] **Step 2.1: Write the failing tests**

Create `tests/test_pricing_table.py`:

```python
from pathlib import Path

import pytest

from spiresight.core.usage import PricingTable, TokenUsage


def _write_yaml(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_load_valid_yaml(tmp_path: Path):
    p = _write_yaml(tmp_path / "prices.yaml", """
gpt-4o:
  input_per_1m: 2.50
  output_per_1m: 10.00
gpt-4o-mini:
  input_per_1m: 0.15
  output_per_1m: 0.60
""")
    table = PricingTable.load(p)
    cost = table.compute("gpt-4o", TokenUsage(1_000_000, 1_000_000))
    assert cost == pytest.approx(12.50)


def test_compute_returns_none_for_unknown_model(tmp_path: Path):
    p = _write_yaml(tmp_path / "prices.yaml", """
gpt-4o:
  input_per_1m: 2.50
  output_per_1m: 10.00
""")
    table = PricingTable.load(p)
    assert table.compute("mystery-model", TokenUsage(100, 100)) is None


def test_compute_math(tmp_path: Path):
    p = _write_yaml(tmp_path / "prices.yaml", """
m:
  input_per_1m: 5.00
  output_per_1m: 15.00
""")
    table = PricingTable.load(p)
    cost = table.compute("m", TokenUsage(2_000_000, 1_000_000))
    assert cost == pytest.approx(2_000_000 / 1_000_000 * 5.00 + 1_000_000 / 1_000_000 * 15.00)
    assert cost == pytest.approx(25.00)


def test_load_missing_file_returns_empty_table(tmp_path: Path):
    table = PricingTable.load(tmp_path / "nonexistent.yaml")
    assert table.compute("gpt-4o", TokenUsage(100, 100)) is None


def test_load_malformed_yaml_returns_empty_table(tmp_path: Path):
    p = _write_yaml(tmp_path / "bad.yaml", ": ::: not yaml ::: :")
    table = PricingTable.load(p)
    assert table.compute("gpt-4o", TokenUsage(100, 100)) is None


def test_invalid_entries_are_skipped_but_valid_ones_kept(tmp_path: Path):
    p = _write_yaml(tmp_path / "mixed.yaml", """
good:
  input_per_1m: 1.0
  output_per_1m: 2.0
bad_missing_key:
  input_per_1m: 1.0
bad_negative:
  input_per_1m: -1.0
  output_per_1m: 2.0
bad_string_value:
  input_per_1m: "not a number"
  output_per_1m: 2.0
""")
    table = PricingTable.load(p)
    assert table.compute("good", TokenUsage(1_000_000, 0)) == pytest.approx(1.0)
    assert table.compute("bad_missing_key", TokenUsage(100, 100)) is None
    assert table.compute("bad_negative", TokenUsage(100, 100)) is None
    assert table.compute("bad_string_value", TokenUsage(100, 100)) is None


def test_zero_tokens_returns_zero_cost(tmp_path: Path):
    p = _write_yaml(tmp_path / "p.yaml", """
m:
  input_per_1m: 5.0
  output_per_1m: 15.0
""")
    table = PricingTable.load(p)
    assert table.compute("m", TokenUsage(0, 0)) == 0.0
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_pricing_table.py -v
```

Expected: FAIL with `ImportError: cannot import name 'PricingTable'`.

- [ ] **Step 2.3: Add `PricingTable` to `core/usage.py`**

Append to `src/spiresight/core/usage.py` (after `_truncate_preview`):

```python
import logging
from pathlib import Path

import yaml

_log = logging.getLogger(__name__)


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
```

- [ ] **Step 2.4: Create `config/prices.yaml` with seed data**

Create the directory if it doesn't exist:

```bash
mkdir -p config
```

Create `config/prices.yaml`:

```yaml
# USD per 1M tokens. Hand-maintained.
# Sourced from OpenAI's public pricing page (as of 2026-05-17).
# Future-model entries (gpt-5.x) are placeholders — verify before relying on them.

gpt-4o:
  input_per_1m: 2.50
  output_per_1m: 10.00

gpt-4o-mini:
  input_per_1m: 0.15
  output_per_1m: 0.60

gpt-4-turbo:
  input_per_1m: 10.00
  output_per_1m: 30.00

gpt-4.1:
  input_per_1m: 2.00
  output_per_1m: 8.00

gpt-4.5:
  input_per_1m: 5.00
  output_per_1m: 15.00

gpt-3.5-turbo:
  input_per_1m: 0.50
  output_per_1m: 1.50

o3:
  input_per_1m: 10.00
  output_per_1m: 40.00

o4-mini:
  input_per_1m: 1.10
  output_per_1m: 4.40

# Placeholders — replace with real numbers when these models launch:
gpt-5:
  input_per_1m: 5.00
  output_per_1m: 15.00

gpt-5.1:
  input_per_1m: 5.00
  output_per_1m: 15.00

gpt-5.2:
  input_per_1m: 5.00
  output_per_1m: 15.00

gpt-5.4:
  input_per_1m: 5.00
  output_per_1m: 15.00

gpt-5.5:
  input_per_1m: 5.00
  output_per_1m: 15.00
```

- [ ] **Step 2.5: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_pricing_table.py -v
```

Expected: 7 passed.

- [ ] **Step 2.6: Commit**

```bash
git add src/spiresight/core/usage.py config/prices.yaml tests/test_pricing_table.py
git commit -m "feat(usage): add PricingTable + hardcoded prices.yaml"
```

---

## Task 3: UsageTracker (QObject)

**Files:**
- Modify: `src/spiresight/core/usage.py`
- Create: `tests/test_usage_tracker.py`

- [ ] **Step 3.1: Write the failing tests**

Create `tests/test_usage_tracker.py`:

```python
from datetime import datetime, timezone

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.core.usage import CallRecord, TokenUsage, UsageTracker


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_record(model: str = "gpt-4o", input_t: int = 100, output_t: int = 200,
                 cost: float | None = 0.001, known: bool = True) -> CallRecord:
    return CallRecord(
        timestamp=datetime(2026, 5, 17, tzinfo=timezone.utc),
        model=model,
        usage=TokenUsage(input_t, output_t),
        usage_known=known,
        cost_usd=cost,
        input_preview="q",
        output_preview="a",
    )


def test_initial_state(qtwidgets_app):
    t = UsageTracker()
    assert t.totals == TokenUsage(0, 0)
    assert t.total_cost_usd is None
    assert t.last_status == "idle"
    assert t.records == []
    assert t.has_unpriced_calls is False


def test_call_started_emits_running_and_remembers_prior(qtwidgets_app):
    t = UsageTracker()
    statuses: list[str] = []
    t.status_changed.connect(statuses.append)

    t.call_started("gpt-4o", "hello")
    assert t.last_status == "running"
    assert statuses == ["running"]


def test_call_completed_ok_updates_totals_and_signals(qtwidgets_app):
    t = UsageTracker()
    seen_records: list[CallRecord] = []
    totals_signals: list[None] = []
    statuses: list[str] = []
    t.call_recorded.connect(seen_records.append)
    t.totals_changed.connect(lambda: totals_signals.append(None))
    t.status_changed.connect(statuses.append)

    t.call_started("gpt-4o", "q1")
    t.call_completed_ok(_make_record(input_t=100, output_t=200, cost=0.01))
    t.call_started("gpt-4o", "q2")
    t.call_completed_ok(_make_record(input_t=50, output_t=75, cost=0.005))

    assert t.totals == TokenUsage(150, 275)
    assert t.total_cost_usd == pytest.approx(0.015)
    assert len(seen_records) == 2
    assert len(totals_signals) == 2
    assert statuses[-1] == "ok"


def test_call_failed_sets_error_no_record(qtwidgets_app):
    t = UsageTracker()
    t.call_started("gpt-4o", "q")
    t.call_failed("HTTP 429")
    assert t.last_status == "error"
    assert t.records == []
    assert t.totals == TokenUsage(0, 0)


def test_call_cancelled_restores_prior_status(qtwidgets_app):
    t = UsageTracker()
    # one successful call → status ok
    t.call_started("gpt-4o", "q1")
    t.call_completed_ok(_make_record(cost=0.01))
    assert t.last_status == "ok"

    # second run cancelled → status returns to ok, not error
    t.call_started("gpt-4o", "q2")
    assert t.last_status == "running"
    t.call_cancelled()
    assert t.last_status == "ok"
    assert len(t.records) == 1  # cancelled run did not append


def test_records_capped_at_200_but_totals_accumulate(qtwidgets_app):
    t = UsageTracker()
    for _ in range(250):
        t.call_started("gpt-4o", "q")
        t.call_completed_ok(_make_record(input_t=1, output_t=1, cost=0.0001))
    assert len(t.records) == 200
    assert t.totals == TokenUsage(250, 250)
    assert t.total_cost_usd == pytest.approx(250 * 0.0001)


def test_total_cost_is_none_when_no_priced_calls(qtwidgets_app):
    t = UsageTracker()
    t.call_started("mystery", "q")
    t.call_completed_ok(_make_record(model="mystery", cost=None))
    assert t.total_cost_usd is None
    assert t.has_unpriced_calls is True


def test_total_cost_sums_priced_only_when_mixed(qtwidgets_app):
    t = UsageTracker()
    t.call_started("gpt-4o", "q")
    t.call_completed_ok(_make_record(cost=0.01))
    t.call_started("mystery", "q")
    t.call_completed_ok(_make_record(model="mystery", cost=None))
    assert t.total_cost_usd == pytest.approx(0.01)
    assert t.has_unpriced_calls is True


def test_records_are_most_recent_first(qtwidgets_app):
    t = UsageTracker()
    t.call_started("gpt-4o", "q1")
    t.call_completed_ok(_make_record(model="first"))
    t.call_started("gpt-4o", "q2")
    t.call_completed_ok(_make_record(model="second"))
    assert t.records[0].model == "second"
    assert t.records[1].model == "first"
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_usage_tracker.py -v
```

Expected: FAIL with `ImportError: cannot import name 'UsageTracker'`.

- [ ] **Step 3.3: Append `UsageTracker` to `core/usage.py`**

Append to `src/spiresight/core/usage.py`:

```python
from collections import deque
from typing import Literal

from PySide6.QtCore import QObject, Signal


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
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_usage_tracker.py -v
```

Expected: 9 passed.

- [ ] **Step 3.5: Commit**

```bash
git add src/spiresight/core/usage.py tests/test_usage_tracker.py
git commit -m "feat(usage): add UsageTracker QObject"
```

---

## Task 4: Extend StreamChunk with usage

**Files:**
- Modify: `src/spiresight/llm/provider.py`

- [ ] **Step 4.1: Modify `StreamChunk`**

Edit `src/spiresight/llm/provider.py`. Replace the `StreamChunk` dataclass:

```python
# src/spiresight/llm/provider.py
from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from spiresight.core.usage import TokenUsage
from .models import ModelInfo


@dataclass
class StreamChunk:
    text_delta: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def list_models(self) -> list[ModelInfo]: ...

    def stream(
        self,
        *,
        model: str,
        system: str,
        user_text: str,
        images: list[bytes],
        cancel_event: threading.Event,
        json_mode: bool = False,
    ) -> Iterator[StreamChunk]: ...
```

- [ ] **Step 4.2: Run all existing tests to make sure nothing breaks**

```bash
.venv/bin/pytest tests/ -q
```

Expected: all previously-passing tests still pass (the new field is optional with a default of `None`).

- [ ] **Step 4.3: Commit**

```bash
git add src/spiresight/llm/provider.py
git commit -m "feat(provider): add optional usage field on StreamChunk"
```

---

## Task 5: OpenAI provider — request usage + parse usage chunk

**Files:**
- Modify: `src/spiresight/llm/providers/openai_provider.py`
- Modify: `tests/test_openai_provider.py`

- [ ] **Step 5.1: Add failing tests at the bottom of `tests/test_openai_provider.py`**

Append to `tests/test_openai_provider.py`:

```python
import json as _json


@respx.mock
def test_stream_request_includes_stream_options_include_usage():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse('{"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}'),
        )
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-test"))
    list(p.stream(
        model="gpt-4o", system="s", user_text="u",
        images=[], cancel_event=threading.Event(),
    ))
    body = _json.loads(route.calls.last.request.content.decode())
    assert body.get("stream_options") == {"include_usage": True}


@respx.mock
def test_stream_yields_usage_on_trailing_chunk():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse(
                '{"choices":[{"delta":{"content":"Hello"}}]}',
                '{"choices":[{"delta":{},"finish_reason":"stop"}]}',
                '{"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":34,"total_tokens":46}}',
            ),
        )
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-test"))
    chunks = list(p.stream(
        model="gpt-4o", system="s", user_text="hi",
        images=[], cancel_event=threading.Event(),
    ))
    # text + finish + usage = at least 3 yielded chunks (text chunk, finish chunk, usage chunk)
    usage_chunks = [c for c in chunks if c.usage is not None]
    assert len(usage_chunks) == 1
    assert usage_chunks[0].usage.input_tokens == 12
    assert usage_chunks[0].usage.output_tokens == 34


@respx.mock
def test_stream_without_usage_field_yields_no_usage_chunk():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse(
                '{"choices":[{"delta":{"content":"x"},"finish_reason":"stop"}]}',
            ),
        )
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-test"))
    chunks = list(p.stream(
        model="gpt-4o", system="s", user_text="hi",
        images=[], cancel_event=threading.Event(),
    ))
    assert all(c.usage is None for c in chunks)
```

- [ ] **Step 5.2: Run new tests to verify they fail**

```bash
.venv/bin/pytest tests/test_openai_provider.py::test_stream_request_includes_stream_options_include_usage tests/test_openai_provider.py::test_stream_yields_usage_on_trailing_chunk -v
```

Expected: both FAIL — the request doesn't include `stream_options`, and the parser drops the usage-only chunk.

- [ ] **Step 5.3: Modify `openai_provider.py` to request and parse usage**

In `src/spiresight/llm/providers/openai_provider.py`:

A. Add the import:

```python
from spiresight.core.usage import TokenUsage
```

B. Update the payload to include `stream_options`. Find the `payload = {...}` block in `stream()` and replace it with:

```python
        payload = {
            "model": model,
            "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": self._build_user_content(user_text, images)},
            ],
        }
```

C. Replace the entire `_parse_sse` static method with:

```python
    @staticmethod
    def _parse_sse(resp: httpx.Response, cancel_event: threading.Event) -> Iterator[StreamChunk]:
        for line in resp.iter_lines():
            if cancel_event.is_set():
                return
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                return
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue

            # Usage block arrives in a trailing chunk whose `choices` is empty.
            # When `stream_options.include_usage` is true, OpenAI sends one such
            # chunk after the finish_reason chunk. We always yield it as a
            # standalone StreamChunk so the caller can attribute totals.
            usage_obj = obj.get("usage")
            if usage_obj:
                yield StreamChunk(
                    text_delta="",
                    finish_reason=None,
                    usage=TokenUsage(
                        input_tokens=int(usage_obj.get("prompt_tokens", 0)),
                        output_tokens=int(usage_obj.get("completion_tokens", 0)),
                    ),
                )

            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            finish = choices[0].get("finish_reason")
            text = delta.get("content") or ""
            if text or finish:
                yield StreamChunk(text_delta=text, finish_reason=finish)
```

- [ ] **Step 5.4: Run the full OpenAI provider test file**

```bash
.venv/bin/pytest tests/test_openai_provider.py -v
```

Expected: all existing tests pass + the 3 new tests pass.

- [ ] **Step 5.5: Commit**

```bash
git add src/spiresight/llm/providers/openai_provider.py tests/test_openai_provider.py
git commit -m "feat(openai): request and parse usage in streaming responses"
```

---

## Task 6: Theme color tokens

**Files:**
- Modify: `src/spiresight/ui/theme.py`

- [ ] **Step 6.1: Add color tokens**

Replace the contents of `src/spiresight/ui/theme.py` with:

```python
# src/spiresight/ui/theme.py
"""QSS loader, color tokens, and icon paths.

Tokens here must match the values in resources/qss/dark_fantasy.qss.
"""
from __future__ import annotations

from importlib import resources

COLORS = {
    "bg": "#090c12",
    "panel": "#0d1018",
    "border": "#1d2233",
    "text": "#d5cebf",
    "muted": "#6e7a89",
    "accent": "#d4a54a",
    "ember": "#d4743a",
}

# Color tokens for the UsageBar status light and LogsTab cost rows.
# The current QSS is dark-themed only, so we ship one palette. If a
# light theme is ever added, swap these via a theme-aware lookup.
USAGE_COLORS = {
    "cost_tag": "#7ee2a8",        # green-300, used for "[cost]" prefix in LogsTab
    "light_idle": "#6b7280",      # gray-500
    "light_running": "#fbbf24",   # amber-400
    "light_ok": "#4ade80",        # green-400
    "light_error": "#f87171",     # red-400
}


def load_qss(name: str = "dark_fantasy") -> str:
    return resources.files("spiresight.resources.qss").joinpath(f"{name}.qss").read_text(
        encoding="utf-8"
    )


def icon_path(name: str) -> str:
    """Absolute path to a named SVG icon in resources/icons/."""
    return str(
        resources.files("spiresight.resources.icons").joinpath(f"{name}.svg")
    )
```

- [ ] **Step 6.2: Run existing test suite to make sure nothing imports broken**

```bash
.venv/bin/pytest tests/ -q
```

Expected: all tests still pass.

- [ ] **Step 6.3: Commit**

```bash
git add src/spiresight/ui/theme.py
git commit -m "feat(theme): add USAGE_COLORS tokens for cost tag and status light"
```

---

## Task 7: LogsTab — QTextEdit + log_cost

**Files:**
- Modify: `src/spiresight/ui/tabs/logs_tab.py`
- Modify: `tests/test_logs_tab.py`

- [ ] **Step 7.1: Add failing tests**

Append to `tests/test_logs_tab.py`:

```python
from datetime import datetime, timezone

from spiresight.core.usage import CallRecord, TokenUsage


def _record(model: str = "gpt-4o", in_t: int = 312, out_t: int = 421,
            cost: float | None = 0.005, known: bool = True,
            qprev: str = "How do I survive elite",
            aprev: str = "You should drop two energy") -> CallRecord:
    return CallRecord(
        timestamp=datetime(2026, 5, 17, 12, 1, 23, tzinfo=timezone.utc),
        model=model,
        usage=TokenUsage(in_t, out_t),
        usage_known=known,
        cost_usd=cost,
        input_preview=qprev,
        output_preview=aprev,
    )


def test_log_cost_renders_all_fields(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log_cost(_record())
    text = tab._view.toPlainText()
    assert "[cost]" in text
    assert "gpt-4o" in text
    assert "312" in text
    assert "421" in text
    assert "~$0.0050" in text
    assert "How do I survive elite" in text
    assert "You should drop two energy" in text


def test_log_cost_falls_back_to_dash_when_cost_none(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log_cost(_record(cost=None))
    text = tab._view.toPlainText()
    assert "~$—" in text


def test_log_cost_renders_question_marks_when_usage_unknown(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log_cost(_record(in_t=0, out_t=0, known=False, cost=None))
    text = tab._view.toPlainText()
    assert "↑ ?" in text
    assert "↓ ?" in text


def test_log_cost_escapes_html_in_previews(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log_cost(_record(qprev="<script>alert(1)</script>", aprev="<b>bold</b>"))
    text = tab._view.toPlainText()
    # script tag text should appear literally in plain text — not be executed/stripped
    assert "<script>alert(1)</script>" in text
    assert "<b>bold</b>" in text


def test_log_and_log_cost_share_buffer_cap(qtwidgets_app, locale):
    tab = LogsTab(locale)
    for i in range(150):
        tab.log(f"plain-{i}")
    for i in range(100):
        tab.log_cost(_record(model=f"m-{i}"))
    # cap is 200; combined inserts (250) → oldest evicted
    text = tab._view.toPlainText()
    assert "plain-0" not in text
    # newest cost row visible
    assert "m-99" in text
```

Note: `test_ring_buffer_caps_at_200` already exists in `test_logs_tab.py` and checks `.toPlainText().splitlines()` length — that test still needs to pass after the switch to QTextEdit. The new tests above use `.toPlainText()` to dodge HTML-specific behavior.

- [ ] **Step 7.2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_logs_tab.py -v
```

Expected: the 5 new tests FAIL with `AttributeError: 'LogsTab' object has no attribute 'log_cost'`.

- [ ] **Step 7.3: Replace `src/spiresight/ui/tabs/logs_tab.py`**

```python
"""Lightweight in-memory log viewer.

Owns its own ring buffer (max 200 entries). MainWindow calls `log()` for
plain text events (errors, status), and `log_cost(record)` for a
structured per-call usage row. Cost rows are HTML-styled so the [cost]
prefix can be color-tinted to scan quickly.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from html import escape

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from spiresight.core.usage import CallRecord
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.theme import USAGE_COLORS


MAX_LINES = 200


class LogsTab(QWidget):
    def __init__(
        self,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._locale = locale
        # Buffer holds HTML fragments (one per row). Plain-text rows are
        # html.escape()'d before insertion so they round-trip safely.
        self._buffer: deque[str] = deque(maxlen=MAX_LINES)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        bar = QHBoxLayout()
        self._copy_btn = QPushButton(locale.get("logs.copy_all"))
        self._copy_btn.clicked.connect(self._on_copy)
        self._clear_btn = QPushButton(locale.get("logs.clear"))
        self._clear_btn.clicked.connect(self._on_clear)
        bar.addWidget(self._copy_btn)
        bar.addWidget(self._clear_btn)
        bar.addStretch(1)
        outer.addLayout(bar)

        self._view = QTextEdit()
        self._view.setReadOnly(True)
        self._view.setStyleSheet("font-family: ui-monospace, Menlo, monospace; font-size:11.5px;")
        outer.addWidget(self._view, stretch=1)

        locale.changed.connect(self._retranslate)

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._buffer.appendleft(escape(f"[{ts}] {message}"))
        self._redraw()

    def log_cost(self, record: CallRecord) -> None:
        ts = record.timestamp.strftime("%H:%M:%S")
        in_tok = str(record.usage.input_tokens) if record.usage_known else "?"
        out_tok = str(record.usage.output_tokens) if record.usage_known else "?"
        cost = f"~${record.cost_usd:.4f}" if record.cost_usd is not None else "~$—"
        line_html = (
            f'<span style="color:{USAGE_COLORS["cost_tag"]};">[{escape(ts)}] [cost]</span> '
            f'<b>{escape(record.model)}</b> '
            f'↑ {escape(in_tok)} ↓ {escape(out_tok)} {escape(cost)} | '
            f'Q: "<i>{escape(record.input_preview)}</i>" | '
            f'A: "<i>{escape(record.output_preview)}</i>"'
        )
        self._buffer.appendleft(line_html)
        self._redraw()

    def _redraw(self) -> None:
        self._view.setHtml("<br>".join(self._buffer))

    def _on_copy(self) -> None:
        # QTextEdit's toPlainText strips HTML automatically.
        QGuiApplication.clipboard().setText(self._view.toPlainText())

    def _on_clear(self) -> None:
        self._buffer.clear()
        self._view.clear()

    def _retranslate(self) -> None:
        loc = self._locale
        self._copy_btn.setText(loc.get("logs.copy_all"))
        self._clear_btn.setText(loc.get("logs.clear"))
```

- [ ] **Step 7.4: Run all LogsTab tests**

```bash
.venv/bin/pytest tests/test_logs_tab.py -v
```

Expected: all tests pass.

Note: The existing `test_ring_buffer_caps_at_200` checks `.toPlainText().splitlines()` length — `QTextEdit.toPlainText()` returns each `<br>`-separated row on its own line, so the count remains 200.

- [ ] **Step 7.5: Commit**

```bash
git add src/spiresight/ui/tabs/logs_tab.py tests/test_logs_tab.py
git commit -m "feat(logs): add log_cost(record) with HTML styling and ? fallback"
```

---

## Task 8: UsageBar widget

**Files:**
- Create: `src/spiresight/ui/widgets/usage_bar.py`
- Create: `tests/test_usage_bar.py`

- [ ] **Step 8.1: Write failing tests**

Create `tests/test_usage_bar.py`:

```python
from datetime import datetime, timezone

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.core.usage import CallRecord, TokenUsage, UsageTracker
from spiresight.ui.widgets.usage_bar import UsageBar, _format_k


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_format_k_under_1000_is_raw():
    assert _format_k(0) == "0"
    assert _format_k(312) == "312"
    assert _format_k(999) == "999"


def test_format_k_thousands_one_decimal():
    assert _format_k(1000) == "1.0k"
    assert _format_k(1500) == "1.5k"
    assert _format_k(12_345) == "12.3k"
    assert _format_k(99_999) == "100.0k"


def test_format_k_hundred_thousands_no_decimal():
    assert _format_k(100_000) == "100k"
    assert _format_k(123_456) == "123k"
    assert _format_k(1_500_000) == "1500k"


def _record(model: str = "gpt-4o", in_t: int = 12_345, out_t: int = 4_567,
            cost: float | None = 0.1834) -> CallRecord:
    return CallRecord(
        timestamp=datetime(2026, 5, 17, tzinfo=timezone.utc),
        model=model,
        usage=TokenUsage(in_t, out_t),
        usage_known=True,
        cost_usd=cost,
        input_preview="q",
        output_preview="a",
    )


def test_initial_render_shows_zero_tokens_and_dash_cost(qtwidgets_app):
    tracker = UsageTracker()
    bar = UsageBar(tracker, model_label="gpt-4o")
    assert "gpt-4o" in bar.text_for_test()
    assert "↑ 0" in bar.text_for_test()
    assert "↓ 0" in bar.text_for_test()
    assert "~$—" in bar.text_for_test()


def test_compact_format_after_recorded_call(qtwidgets_app):
    tracker = UsageTracker()
    bar = UsageBar(tracker, model_label="gpt-4o")
    tracker.call_started("gpt-4o", "q")
    tracker.call_completed_ok(_record(in_t=12_345, out_t=4_567, cost=0.1834))
    txt = bar.text_for_test()
    assert "↑ 12.3k" in txt
    assert "↓ 4.5k" in txt
    assert "~$0.18" in txt


def test_dot_color_changes_with_status(qtwidgets_app):
    tracker = UsageTracker()
    bar = UsageBar(tracker, model_label="gpt-4o")
    assert "6b7280" in bar.dot_stylesheet_for_test().lower()  # idle gray

    tracker.call_started("gpt-4o", "q")
    assert "fbbf24" in bar.dot_stylesheet_for_test().lower()  # running amber

    tracker.call_completed_ok(_record())
    assert "4ade80" in bar.dot_stylesheet_for_test().lower()  # ok green

    tracker.call_started("gpt-4o", "q")
    tracker.call_failed("boom")
    assert "f87171" in bar.dot_stylesheet_for_test().lower()  # error red


def test_unpriced_session_shows_dash(qtwidgets_app):
    tracker = UsageTracker()
    bar = UsageBar(tracker, model_label="mystery")
    tracker.call_started("mystery", "q")
    tracker.call_completed_ok(_record(model="mystery", cost=None))
    assert "~$—" in bar.text_for_test()


def test_set_model_label_updates_display(qtwidgets_app):
    tracker = UsageTracker()
    bar = UsageBar(tracker, model_label="gpt-4o")
    bar.set_model_label("gpt-4o-mini")
    assert "gpt-4o-mini" in bar.text_for_test()


def test_tooltip_contains_precise_numbers_and_cost(qtwidgets_app):
    tracker = UsageTracker()
    bar = UsageBar(tracker, model_label="gpt-4o")
    tracker.call_started("gpt-4o", "q")
    tracker.call_completed_ok(_record(in_t=12_345, out_t=4_567, cost=0.1834))
    tip = bar.toolTip()
    assert "12,345" in tip or "12345" in tip
    assert "4,567" in tip or "4567" in tip
    assert "0.1834" in tip


def test_tooltip_notes_unpriced_when_mixed(qtwidgets_app):
    tracker = UsageTracker()
    bar = UsageBar(tracker, model_label="gpt-4o")
    tracker.call_started("gpt-4o", "q")
    tracker.call_completed_ok(_record(cost=0.01))
    tracker.call_started("mystery", "q")
    tracker.call_completed_ok(_record(model="mystery", cost=None))
    assert "unpriced" in bar.toolTip().lower()
```

- [ ] **Step 8.2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_usage_bar.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'spiresight.ui.widgets.usage_bar'`.

- [ ] **Step 8.3: Create `src/spiresight/ui/widgets/usage_bar.py`**

```python
"""Bottom-bar widget showing current model, status light, and session totals.

Mounted via `QStatusBar.addPermanentWidget`. Subscribes to a UsageTracker's
signals and re-renders on `status_changed` / `totals_changed`. Session
state lives on the tracker; this widget is a pure view.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from spiresight.core.usage import UsageTracker
from spiresight.ui.theme import USAGE_COLORS


_STATUS_COLOR = {
    "idle":    USAGE_COLORS["light_idle"],
    "running": USAGE_COLORS["light_running"],
    "ok":      USAGE_COLORS["light_ok"],
    "error":   USAGE_COLORS["light_error"],
}


def _format_k(n: int) -> str:
    """Render token counts compactly. Examples:
        312        → "312"
        1_500      → "1.5k"
        12_345     → "12.3k"
        100_000    → "100k"   (no decimal once we're at or above 100k)
        1_500_000  → "1500k"
    """
    if n < 1000:
        return f"{n}"
    if n < 100_000:
        return f"{n / 1000:.1f}k"
    return f"{n // 1000}k"


def _dot_stylesheet(status: str) -> str:
    color = _STATUS_COLOR.get(status, _STATUS_COLOR["idle"])
    return (
        f"background-color: {color};"
        " border-radius: 5px;"
        " min-width: 10px; max-width: 10px;"
        " min-height: 10px; max-height: 10px;"
    )


class UsageBar(QWidget):
    def __init__(
        self,
        tracker: UsageTracker,
        *,
        model_label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tracker = tracker
        self._model_label = model_label

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(8)

        self._dot = QLabel()
        self._dot.setStyleSheet(_dot_stylesheet("idle"))
        layout.addWidget(self._dot, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._label = QLabel()
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._label, alignment=Qt.AlignmentFlag.AlignVCenter)

        tracker.totals_changed.connect(self._refresh_text)
        tracker.status_changed.connect(self._on_status_changed)

        self._refresh_text()

    # ---- public ----

    def set_model_label(self, model: str) -> None:
        self._model_label = model
        self._refresh_text()

    # ---- internals ----

    def _on_status_changed(self, status: str) -> None:
        self._dot.setStyleSheet(_dot_stylesheet(status))

    def _refresh_text(self) -> None:
        totals = self._tracker.totals
        cost = self._tracker.total_cost_usd
        cost_text = f"~${cost:.2f}" if cost is not None else "~$—"
        self._label.setText(
            f"{self._model_label}  "
            f"↑ {_format_k(totals.input_tokens)}  "
            f"↓ {_format_k(totals.output_tokens)}  "
            f"{cost_text}"
        )
        self._refresh_tooltip()

    def _refresh_tooltip(self) -> None:
        totals = self._tracker.totals
        cost = self._tracker.total_cost_usd
        cost_line = f"cost: ${cost:.4f}" if cost is not None else "cost: —"
        unpriced = ""
        if self._tracker.has_unpriced_calls:
            unpriced = "\n(some calls unpriced)"
        self.setToolTip(
            f"input: {totals.input_tokens:,} tokens\n"
            f"output: {totals.output_tokens:,} tokens\n"
            f"{cost_line}{unpriced}"
        )

    # ---- test hooks ----

    def text_for_test(self) -> str:
        return self._label.text()

    def dot_stylesheet_for_test(self) -> str:
        return self._dot.styleSheet()
```

- [ ] **Step 8.4: Run UsageBar tests**

```bash
.venv/bin/pytest tests/test_usage_bar.py -v
```

Expected: all 10 tests pass.

- [ ] **Step 8.5: Commit**

```bash
git add src/spiresight/ui/widgets/usage_bar.py tests/test_usage_bar.py
git commit -m "feat(ui): add UsageBar status-bar widget"
```

---

## Task 9: InferenceWorker — new signals + usage capture

**Files:**
- Modify: `src/spiresight/ui/workers/inference_worker.py`
- Create: `tests/test_inference_worker_usage_flow.py`

- [ ] **Step 9.1: Write failing tests**

Create `tests/test_inference_worker_usage_flow.py`:

```python
import threading
from collections.abc import Iterator

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from spiresight.core.usage import CallRecord, TokenUsage
from spiresight.llm.provider import StreamChunk
from spiresight.ui.workers.inference_worker import InferenceWorker


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeRunner:
    def __init__(self, chunks: list[StreamChunk]) -> None:
        self._chunks = chunks

    def run(self, request, *, cancel_event: threading.Event) -> Iterator[StreamChunk]:
        for c in self._chunks:
            if cancel_event.is_set():
                return
            yield c


def _drain(worker: InferenceWorker, timeout_ms: int = 2000) -> None:
    """Spin a Qt event loop until the worker thread emits finished_ok or failed."""
    loop = QEventLoop()
    done = {"flag": False}

    def stop():
        done["flag"] = True
        loop.quit()

    worker.finished_ok.connect(stop)
    worker.failed.connect(stop)
    worker.cancelled.connect(stop)
    QTimer.singleShot(timeout_ms, loop.quit)
    worker.start()
    loop.exec()
    worker.wait(1000)
    assert done["flag"], "worker did not finish within timeout"


def test_worker_emits_run_started_then_usage_recorded(qtwidgets_app):
    chunks = [
        StreamChunk(text_delta="hello "),
        StreamChunk(text_delta="world", finish_reason="stop"),
        StreamChunk(text_delta="", usage=TokenUsage(12, 34)),
    ]
    runner = _FakeRunner(chunks)
    worker = InferenceWorker(
        runner, request=object(),
        model_id="gpt-4o",
        input_preview="How do I survive elite",
    )
    started: list[tuple[str, str]] = []
    records: list[CallRecord] = []
    finished: list[None] = []
    worker.run_started.connect(lambda m, q: started.append((m, q)))
    worker.usage_recorded.connect(records.append)
    worker.finished_ok.connect(lambda: finished.append(None))

    _drain(worker)

    assert started == [("gpt-4o", "How do I survive elite")]
    assert len(records) == 1
    rec = records[0]
    assert rec.model == "gpt-4o"
    assert rec.usage == TokenUsage(12, 34)
    assert rec.usage_known is True
    assert rec.cost_usd is None  # worker doesn't price; MainWindow does (see Task 10)
    assert rec.input_preview == "How do I survive elite"
    assert rec.output_preview == "hello world"
    assert finished == [None]


def test_worker_emits_usage_known_false_when_no_usage_chunk(qtwidgets_app):
    chunks = [
        StreamChunk(text_delta="bye", finish_reason="stop"),
    ]
    runner = _FakeRunner(chunks)
    worker = InferenceWorker(
        runner, request=object(), model_id="gpt-4o", input_preview="hi",
    )
    records: list[CallRecord] = []
    worker.usage_recorded.connect(records.append)

    _drain(worker)

    assert len(records) == 1
    assert records[0].usage_known is False
    assert records[0].usage == TokenUsage(0, 0)


def test_worker_continues_iterating_past_finish_reason(qtwidgets_app):
    """The usage chunk comes after finish_reason; worker must NOT break early."""
    chunks = [
        StreamChunk(text_delta="text"),
        StreamChunk(text_delta="", finish_reason="stop"),
        StreamChunk(text_delta="", usage=TokenUsage(5, 7)),
    ]
    runner = _FakeRunner(chunks)
    worker = InferenceWorker(
        runner, request=object(), model_id="gpt-4o", input_preview="hi",
    )
    records: list[CallRecord] = []
    worker.usage_recorded.connect(records.append)

    _drain(worker)

    assert records[0].usage == TokenUsage(5, 7)


def test_worker_emits_cancelled_when_cancelled_mid_stream(qtwidgets_app):
    """A canceled run does not append a record."""
    # Long-running fake: a generator that respects the cancel event.
    class _SlowRunner:
        def run(self, request, *, cancel_event: threading.Event):
            # Yield one chunk, then check cancel.
            yield StreamChunk(text_delta="partial")
            # Wait briefly, allowing the caller to set cancel_event.
            for _ in range(20):
                if cancel_event.is_set():
                    return
                cancel_event.wait(0.01)
            yield StreamChunk(text_delta="", finish_reason="stop")
            yield StreamChunk(text_delta="", usage=TokenUsage(1, 1))

    worker = InferenceWorker(
        _SlowRunner(), request=object(), model_id="gpt-4o", input_preview="hi",
    )
    cancelled_signals: list[None] = []
    records: list[CallRecord] = []
    worker.cancelled.connect(lambda: cancelled_signals.append(None))
    worker.usage_recorded.connect(records.append)

    # Cancel shortly after starting.
    QTimer.singleShot(20, worker.cancel)
    _drain(worker, timeout_ms=2000)

    assert cancelled_signals == [None]
    assert records == []


def test_worker_emits_failed_on_exception(qtwidgets_app):
    class _BoomRunner:
        def run(self, request, *, cancel_event: threading.Event):
            raise RuntimeError("boom")
            yield  # pragma: no cover  (make it a generator)

    worker = InferenceWorker(
        _BoomRunner(), request=object(), model_id="gpt-4o", input_preview="hi",
    )
    excs: list[BaseException] = []
    worker.failed.connect(excs.append)

    _drain(worker)

    assert len(excs) == 1
    assert isinstance(excs[0], RuntimeError)
```

- [ ] **Step 9.2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_inference_worker_usage_flow.py -v
```

Expected: FAIL — `InferenceWorker.__init__` doesn't accept `model_id`/`input_preview`, and the new signals don't exist.

- [ ] **Step 9.3: Replace `src/spiresight/ui/workers/inference_worker.py`**

```python
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
```

- [ ] **Step 9.4: Run the new tests**

```bash
.venv/bin/pytest tests/test_inference_worker_usage_flow.py -v
```

Expected: 5 passed.

- [ ] **Step 9.5: Commit**

```bash
git add src/spiresight/ui/workers/inference_worker.py tests/test_inference_worker_usage_flow.py
git commit -m "feat(worker): add usage capture and run_started/usage_recorded/cancelled signals"
```

---

## Task 10: i18n keys

**Files:**
- Modify: `prompts/locales/en/ui_strings.yaml`
- Modify: `prompts/locales/zh/ui_strings.yaml`

- [ ] **Step 10.1: Append `usage:` block to `prompts/locales/en/ui_strings.yaml`**

Open `prompts/locales/en/ui_strings.yaml` and append at the end (preserving the existing top-level structure):

```yaml

usage:
  tooltip:
    input: "Session input tokens"
    output: "Session output tokens"
    cost: "Estimated session cost"
    unpriced: "(some calls unpriced)"
  light:
    idle: "No requests yet"
    running: "Request in progress"
    ok: "Last request succeeded"
    error: "Last request failed"
```

- [ ] **Step 10.2: Append the matching block to `prompts/locales/zh/ui_strings.yaml`**

Open `prompts/locales/zh/ui_strings.yaml` and append at the end:

```yaml

usage:
  tooltip:
    input: "本次会话输入 tokens"
    output: "本次会话输出 tokens"
    cost: "本次会话估算费用"
    unpriced: "（部分模型无报价）"
  light:
    idle: "尚未发送请求"
    running: "正在请求"
    ok: "上次请求成功"
    error: "上次请求失败"
```

- [ ] **Step 10.3: Run the full test suite to make sure nothing broke**

```bash
.venv/bin/pytest tests/ -q
```

Expected: all tests still pass. (The new keys aren't consumed yet — Task 11 wires them.)

- [ ] **Step 10.4: Commit**

```bash
git add prompts/locales/en/ui_strings.yaml prompts/locales/zh/ui_strings.yaml
git commit -m "feat(i18n): add usage.* keys for status light and tooltip"
```

---

## Task 11: Wire it together in app.py + MainWindow

This is the largest task — it threads PricingTable, UsageTracker, UsageBar, and the new worker signature through `app.py` and `MainWindow`. It also adds the cost-attribution glue (the worker emits a record with `cost_usd=None`; MainWindow looks up the price and forwards a new record to the tracker).

**Files:**
- Modify: `src/spiresight/app.py`
- Modify: `src/spiresight/ui/windows/main_window.py`

- [ ] **Step 11.1: Add `_prices_path` helper to `app.py` and load the table**

Edit `src/spiresight/app.py`. Add this helper near `_prompts_root`:

```python
def _prices_path() -> Path:
    """Locate config/prices.yaml whether running from source or bundle."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "prices.yaml"
        if candidate.exists():
            return candidate
    # Fall through — caller's PricingTable.load handles missing file.
    return Path(__file__).resolve().parent / "config" / "prices.yaml"
```

Update `run()` to load the pricing table and pass it through. Replace the body of `run()` with:

```python
def run() -> int:
    configure_logging()
    paths.ensure_dirs()

    store = ConfigStore()
    config = store.load()

    loader = PromptLoader(_prompts_root())
    loader.reload(language=config.language)

    from spiresight.core.usage import PricingTable
    pricing = PricingTable.load(_prices_path())

    qt_app = QApplication(sys.argv)
    qt_app.setStyleSheet(load_qss(config.theme))

    window = MainWindow(config, store, loader, pricing=pricing)
    window.show()

    hotkey_mgr: HotkeyManager | None = None
    try:
        hotkey_mgr = HotkeyManager(config.hotkey, on_press=window.fire_action_signal.emit)
        hotkey_mgr.start()
    except HotkeyRegistrationFailed as exc:
        log.warning("Hotkey registration failed: %s", exc)
        if sys.platform == "darwin":
            PermissionDialog(window).exec()

    try:
        return qt_app.exec()
    finally:
        if hotkey_mgr is not None:
            hotkey_mgr.stop()
```

- [ ] **Step 11.2: Update `MainWindow.__init__` signature**

Edit `src/spiresight/ui/windows/main_window.py`.

Find `MainWindow.__init__` (currently `def __init__(self, config, store, loader)` — look for the first def after the class). Add a keyword arg `pricing` and instantiate the tracker + bar. Add these imports near the top of the file (next to the existing `from spiresight.ui.tabs.logs_tab import LogsTab`):

```python
from spiresight.core.usage import (
    CallRecord, PricingTable, TokenUsage, UsageTracker, _truncate_preview,
)
from spiresight.ui.widgets.usage_bar import UsageBar
```

Update the signature and body. Insert these lines into `__init__` **after** `self.setStatusBar(QStatusBar())` (line 198):

```python
        # --- usage tracking ---
        self._pricing = pricing
        self._tracker = UsageTracker(self)
        self._usage_bar = UsageBar(self._tracker, model_label=self._config.active_model)
        self.statusBar().addPermanentWidget(self._usage_bar)
        self._tracker.call_recorded.connect(self._logs_tab.log_cost)
```

Change the signature of `__init__` to accept `pricing`. Locate the existing signature (`def __init__(self, config, store, loader)`) and replace it with:

```python
    def __init__(self, config, store, loader, *, pricing: PricingTable) -> None:
```

- [ ] **Step 11.3: Update the worker construction sites to pass model + preview + wire usage signals**

There are two worker construction sites in `main_window.py` (lines ~361 and ~409 in the original file). Each looks like:

```python
        self._worker = InferenceWorker(runner, request, self)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()
```

Replace both occurrences with:

```python
        input_preview = self._compose_input_preview(request)
        self._worker = InferenceWorker(
            runner, request,
            model_id=self._config.active_model,
            input_preview=input_preview,
            parent=self,
        )
        self._worker.chunk.connect(self._on_chunk)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.run_started.connect(self._tracker.call_started)
        self._worker.usage_recorded.connect(self._on_usage_recorded)
        self._worker.cancelled.connect(self._tracker.call_cancelled)
        self._worker.start()
```

- [ ] **Step 11.4: Add `_compose_input_preview` and `_on_usage_recorded` methods**

Add these two methods to `MainWindow` (a good place is near `_on_chunk` at line 367):

```python
    def _compose_input_preview(self, request) -> str:
        """Build the 'input preview' text that the UsageBar / LogsTab show.

        Prefer the user's typed custom_text, since that's what they
        actually want to see attributed to a call. Fall back to the
        quick-action label so quick-fire prompts still get a meaningful
        line in Logs.
        """
        if request.custom_text:
            return request.custom_text
        try:
            qa = self._loader.get_quick_action(request.prompt_id)
            return qa.label
        except Exception:  # noqa: BLE001  — preview is best-effort
            return request.prompt_id

    def _on_usage_recorded(self, record) -> None:
        """Worker emits CallRecord with cost_usd=None; attach a price here, then forward."""
        priced_cost = (
            self._pricing.compute(record.model, record.usage)
            if record.usage_known
            else None
        )
        priced_record = CallRecord(
            timestamp=record.timestamp,
            model=record.model,
            usage=record.usage,
            usage_known=record.usage_known,
            cost_usd=priced_cost,
            input_preview=record.input_preview,
            output_preview=record.output_preview,
        )
        self._tracker.call_completed_ok(priced_record)
```

- [ ] **Step 11.5: Convert worker `failed` to also notify the tracker**

Find `_on_failed` in `main_window.py`. The existing handler renders the error in the UI. **Without changing what's rendered**, add a `self._tracker.call_failed(reason)` call at the top:

Find the handler (the body that processes the `failed` signal — likely `def _on_failed(self, exc)`). At its very top, insert:

```python
        self._tracker.call_failed(str(exc))
```

- [ ] **Step 11.6: Update `UsageBar` model label when the user switches models**

There is already a path that updates `self._config.active_model` (line ~231 in the file). After that assignment, refresh the bar. Find:

```python
            self._config.active_model = model_id
```

And add immediately after it:

```python
            self._usage_bar.set_model_label(model_id)
```

- [ ] **Step 11.7: Run the full test suite**

```bash
.venv/bin/pytest tests/ -q
```

Expected: all tests still pass. Several existing tests construct `MainWindow` — if any of them break because of the new `pricing` kwarg, add a fixture-level `PricingTable({})` to each call site they touch. (Check `tests/test_history_tab.py`, `tests/test_compose_dock.py`, etc. — but only those that actually instantiate `MainWindow`; most tab tests instantiate the tab directly.)

- [ ] **Step 11.8: Manually verify in the running app**

```bash
source .venv/bin/activate
python -m spiresight
```

Expected, end-to-end:
1. App launches, status bar shows `● gpt-X  ↑ 0  ↓ 0  ~$—` (gray dot).
2. Open Settings, paste an OpenAI API key, send a quick action.
3. While streaming, the dot is amber.
4. After the stream completes, the dot turns green and the bar shows non-zero tokens and a `~$0.xx` cost (for a priced model).
5. Open the Logs tab — a single line with `[cost]` (green), the model, tokens, dollar amount, and Q/A previews is visible.
6. Hover the bar — tooltip shows precise integer counts and 4-dp cost.
7. Cancel a streaming run — dot returns to green (or to whatever the prior status was), no cost row added.
8. Force an error (e.g., invalidate the key) and send — dot turns red, no cost row added.
9. Restart the app — bar shows zeros again. ✓

- [ ] **Step 11.9: Commit**

```bash
git add src/spiresight/app.py src/spiresight/ui/windows/main_window.py
git commit -m "feat(ui): wire UsageTracker, UsageBar, and worker cost flow through MainWindow"
```

---

## Task 12: Final verification + push branch

- [ ] **Step 12.1: Run the entire test suite one last time**

```bash
.venv/bin/pytest tests/ -q
```

Expected: 0 failures.

- [ ] **Step 12.2: Run ruff**

```bash
.venv/bin/ruff check src/ tests/
```

Expected: clean. Fix any issues with `.venv/bin/ruff check --fix src/ tests/` and re-run.

- [ ] **Step 12.3: Run the app once more end-to-end (smoke test)**

```bash
source .venv/bin/activate
python -m spiresight
```

Verify the manual checklist from Step 11.8 again.

- [ ] **Step 12.4: Push branch**

```bash
git push -u origin feat/token-cost-debug
```

---

## Notes for the implementer

- **Do not** add a settings UI for editable prices in this branch — that's listed as a follow-up in the spec.
- **Do not** persist usage history. The session-resets-on-restart behavior is intentional.
- The `prices.yaml` placeholder rates for `gpt-5.*` are guesses. Don't treat them as truth; flag any deviation between displayed `~$` and the real billing as expected for those models until updated.
- If you find that two `MainWindow` construction sites in `_on_compose_send` and `_on_resend` (Task 11.3) have drifted apart in the codebase, the pattern is the same — both must get the new worker construction args and the same set of `connect` calls. Don't refactor them into one method as part of this task unless trivial.
- Image tokens are folded into `prompt_tokens` by OpenAI. You don't need to compute or attribute them separately.
- Cancellation does **not** flip the light to red. That's explicit in the spec (§7 item 11) and tested in `test_call_cancelled_restores_prior_status`.
