# Token cost tracking & debug panel — design

**Status:** Approved
**Date:** 2026-05-17
**Scope:** Add per-call token accounting and a session-wide cost indicator to SpireSight. No persistence — session resets on every app launch.

## 1. Goals

1. After every inference call, the user can see in the Logs tab: timestamp, model, input/output tokens, estimated USD cost, and a short preview of both the user prompt and the assistant reply.
2. A bottom-right status bar element shows, at a glance, the **current** model, a **connection-status light**, and the **session cumulative** input tokens, output tokens, and cost in `00k` format.
3. The token counts come from the API's own `usage` report — they are accurate, not estimated.
4. Pricing is sourced from a hardcoded `prices.yaml` in the repo. Models not in the table render `~$—` rather than blocking the flow.
5. App restart clears all session state.

Out of scope: persisted usage history, per-model breakdown in the UI, user-configurable pricing in Settings, dynamic price fetching, image-token surcharge modelling.

## 2. Non-goals & known limitations

- **No dynamic pricing fetch.** OpenAI does not expose a pricing API. LiteLLM's community JSON was considered and rejected for MVP because the codebase ships placeholder future-model names (`gpt-5.5`, `gpt-5.4`, etc.) that won't be in that file, and a network dependency at startup adds a failure mode for no clear benefit at this scale.
- **No image-token line item.** OpenAI rolls image-input tokens into `prompt_tokens` on vision-capable models. We surface `prompt_tokens` as-is; we do not separately attribute or surcharge image tokens.
- **No mid-stream cost preview.** The `usage` block arrives in the final SSE chunk only. Cost appears once the stream finishes.
- **Future-model prices are placeholders.** Entries for `gpt-5`, `gpt-5.1`, etc. in `prices.yaml` are hand-written guesses and labelled as such; they should be reviewed before they're treated as truth.

## 3. Architecture

### 3.1 File layout

```
src/spiresight/
  core/
    usage.py                    NEW   TokenUsage, CallRecord, PricingTable, UsageTracker (QObject)
  llm/
    provider.py                 CHG   StreamChunk gains optional `usage: TokenUsage | None`
    providers/
      openai_provider.py        CHG   add stream_options.include_usage=true, parse usage chunk
  ui/
    widgets/
      usage_bar.py              NEW   QStatusBar permanent widget (light + model + tokens + $)
    tabs/
      logs_tab.py               CHG   QPlainTextEdit → QTextEdit; add log_cost(record)
    workers/
      inference_worker.py       CHG   capture usage chunk, emit usage_recorded signal
    windows/
      main_window.py            CHG   instantiate UsageTracker, mount UsageBar, wire signals
    theme.py                    CHG   add cost/light color palette
config/
  prices.yaml                   NEW   { model_id: { input_per_1m, output_per_1m } }
prompts/locales/{en,zh}.yaml    CHG   add usage.* i18n keys

tests/
  test_pricing_table.py         NEW
  test_usage_tracker.py         NEW
  test_openai_provider_usage.py NEW
  test_logs_tab_cost.py         NEW
  test_usage_bar.py             NEW
  test_inference_worker_usage_flow.py NEW
```

### 3.2 Module boundaries

- **`core/usage.py`** holds the in-memory state and the pricing lookup. It exposes a `QObject` (`UsageTracker`) for Qt signal/slot use, following the precedent set by `core/inspect_session.py`. It does not import anything from `ui/`.
- **`llm/`** providers stay UI-agnostic. The only addition is the `usage` field on `StreamChunk`, populated by the OpenAI provider's parser. Stub providers (`anthropic`, `gemini`) leave it `None`.
- **`ui/`** widgets (`usage_bar`, `logs_tab`) are pure consumers. They subscribe to tracker signals and re-render; they do not own usage state.
- **`config/prices.yaml`** is repo-managed plain data; no schema-aware loader beyond what `PricingTable.load` provides.

## 4. Data flow

### 4.1 OpenAI SSE shape with `stream_options.include_usage=true`

The usage block arrives in a **separate trailing chunk**, after the `finish_reason` chunk, before `[DONE]`:

```
data: {"choices":[{"delta":{"content":"Hello"},"index":0}], ...}
data: {"choices":[{"delta":{"content":" world"},"index":0}], ...}
data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}], ...}
data: {"choices":[], "usage":{"prompt_tokens":12,"completion_tokens":34,"total_tokens":46}}
data: [DONE]
```

Two implications:

- `OpenAIProvider._parse_sse` must look for a top-level `usage` field on **every** parsed payload, not just inside `choices[0].delta`. When found, it yields a `StreamChunk(text_delta="", finish_reason=None, usage=TokenUsage(prompt_tokens, completion_tokens))`.
- The worker must **not** break on `finish_reason`; it must continue iterating until the provider's iterator naturally ends. The `usage`-bearing chunk will be the last (or near-last) chunk yielded.

### 4.2 End-to-end sequence

```
User clicks Send
   │
   ▼
InferenceWorker.run()  (QThread)
   ├─► emits run_started(model_id, input_preview)
   │       ↳ tracker.call_started(...) → status_changed("running") → UsageBar light yellow
   │
   ├─► runner.run(request) yields StreamChunk's
   │   OpenAIProvider.stream() sends stream_options={"include_usage": true}
   │   Worker accumulates text_delta into output_buffer (existing behavior — still emits chunk(str) for ChatTab).
   │   Worker captures chunk.usage if a chunk carries it.
   │   Worker does NOT break on finish_reason; loops until the iterator ends.
   │
   ├─► on iterator end (success):
   │     record = CallRecord(
   │       timestamp=now(), model=model_id,
   │       usage=captured_usage or TokenUsage(0, 0),
   │       usage_known=(captured_usage is not None),
   │       cost_usd=PricingTable.compute(model_id, usage) if usage_known else None,
   │       input_preview=_truncate_preview(input_preview_source, 60),
   │       output_preview=_truncate_preview(output_buffer, 60),
   │     )
   │     emits usage_recorded(record)
   │       ↳ tracker.call_completed_ok(record)
   │           - appends to deque(maxlen=200)
   │           - increments totals (input, output, cost-if-priced)
   │           - emits call_recorded(record) → LogsTab.log_cost(record)
   │           - emits totals_changed() → UsageBar refresh
   │           - status_changed("ok") → light green
   │
   ├─► on cancel (worker._cancel.set() observed by provider):
   │     emits cancelled()
   │       ↳ tracker.call_cancelled()
   │           - status restored to pre-running value (gray/green/red), not red
   │           - no record appended, totals unchanged
   │     LogsTab gets a plain non-cost line via existing log(): "[hh:mm:ss] run cancelled by user".
   │
   └─► on exception:
         emits failed(exc)        (existing signal — reused)
           ↳ MainWindow handler builds reason string and calls tracker.call_failed(reason)
               - status_changed("error") → light red
               - no record appended, totals unchanged
```

### 4.3 Worker signal additions

| Signal | Status | Payload | Purpose |
|---|---|---|---|
| `chunk(str)` | existing | text delta | unchanged — still drives ChatTab streaming |
| `finished_ok()` | existing | — | unchanged — fires after iterator ends |
| `failed(object)` | existing | exception | unchanged — MainWindow converts to reason string for tracker |
| `run_started(str, str)` | **new** | `(model_id, input_preview)` | tracker enters "running" state and stores model + Q preview |
| `usage_recorded(object)` | **new** | `CallRecord` | tracker appends and updates totals |
| `cancelled()` | **new** | — | tracker restores prior status without going red |

### 4.4 Where the worker gets `model_id` and `input_preview`

The runner currently resolves the model and user_text **inside** `runner.run()`, so the worker doesn't naturally see them. To keep the runner pure and avoid a multi-return refactor, the worker is constructed with two extra arguments captured at the call site (`MainWindow` already has both):

```python
InferenceWorker(
    runner, request,
    model_id=config.active_model,
    input_preview=_compose_input_preview(request, prompt_loader),
)
```

where `_compose_input_preview` is a small helper that prefers `request.custom_text` if present, else the quick action's title. This is a UI-layer concern (it's what the user sees as "their input"); the runner remains unchanged.

If the worker observes a final `model_id` mismatch — e.g., the runner internally falls back to a different model — that's already a `KeyError` today, so no new handling is needed.

## 5. Public APIs

### 5.1 `core/usage.py`

```python
@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int

@dataclass(frozen=True)
class CallRecord:
    timestamp: datetime
    model: str
    usage: TokenUsage
    usage_known: bool            # False when provider didn't return a usage block
    cost_usd: float | None       # None when model_id not in prices.yaml, or when usage_known is False
    input_preview: str           # already truncated; trailing "…" if cut
    output_preview: str

class PricingTable:
    @classmethod
    def load(cls, yaml_path: Path) -> "PricingTable": ...
    def compute(self, model_id: str, usage: TokenUsage) -> float | None: ...
    # returns None when model_id missing from table

class UsageTracker(QObject):
    call_recorded   = Signal(object)  # CallRecord
    totals_changed  = Signal()
    status_changed  = Signal(str)     # "idle" | "running" | "ok" | "error"

    @property
    def totals(self) -> TokenUsage: ...
    @property
    def total_cost_usd(self) -> float | None: ...     # None iff no priced calls
    @property
    def has_unpriced_calls(self) -> bool: ...         # surfaced in tooltip
    @property
    def last_status(self) -> str: ...
    @property
    def records(self) -> list[CallRecord]: ...        # most-recent-first, ≤200

    def call_started(self, model: str, input_preview: str) -> None: ...
    def call_completed_ok(self, record: CallRecord) -> None: ...
    def call_failed(self, reason: str) -> None: ...
    def call_cancelled(self) -> None: ...   # restores prior status, not error

def _truncate_preview(text: str, max_chars: int = 60) -> str: ...
```

### 5.2 `llm/provider.py` extension

```python
@dataclass
class StreamChunk:
    text_delta: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None   # NEW; populated by provider on the final chunk
```

### 5.3 `prices.yaml` schema

```yaml
# USD per 1M tokens. Hand-maintained.
# Future-model rates marked TBD; verify before relying on them.
gpt-4o:
  input_per_1m: 2.50
  output_per_1m: 10.00
gpt-4o-mini:
  input_per_1m: 0.15
  output_per_1m: 0.60
# ...
gpt-5:           # TBD placeholder
  input_per_1m: 5.00
  output_per_1m: 15.00
```

Per-entry validation: both keys must exist and be non-negative numbers. Invalid entries are skipped with a one-time warning at load. Missing file or malformed YAML → empty table (logged once, app still runs).

## 6. UI rendering

### 6.1 LogsTab

The inner widget switches from `QPlainTextEdit` to `QTextEdit` so we can use HTML-styled rows. The existing `log(message)` API stays (plain text, no color). A new `log_cost(record)` method appends an HTML-styled row:

```python
def log_cost(self, record: CallRecord) -> None:
    ts = record.timestamp.strftime("%H:%M:%S")
    in_tok = str(record.usage.input_tokens) if record.usage_known else "?"
    out_tok = str(record.usage.output_tokens) if record.usage_known else "?"
    cost = f"~${record.cost_usd:.4f}" if record.cost_usd is not None else "~$—"
    line_html = (
        f'<span style="color:{COST_TAG_COLOR};">[{ts}] [cost]</span> '
        f'<b>{escape(record.model)}</b> '
        f'↑ {in_tok} ↓ {out_tok} {cost} | '
        f'Q: "<i>{escape(record.input_preview)}</i>" | '
        f'A: "<i>{escape(record.output_preview)}</i>"'
    )
    self._buffer.appendleft(line_html)
    self._redraw_html()
```

`_redraw_html()` joins entries with `<br>` and calls `setHtml(...)`. The existing Copy button uses `QTextDocument.toPlainText()` so it produces a clean plain-text dump of the whole buffer.

Buffer cap stays at 200 entries (shared between plain log lines and cost lines).

### 6.2 UsageBar widget

```
┌────────────────────────────────────────────┐
│ ● gpt-5  ↑ 12.3k  ↓ 4.5k  ~$0.18           │
└────────────────────────────────────────────┘
```

- Mounted via `MainWindow.statusBar().addPermanentWidget(usage_bar)` — right-aligned by default.
- `●` is a 10×10 `QLabel` styled with `border-radius: 5px; background-color: {color}`.
- Tooltip on the whole widget shows exact integers and 4-dp cost, plus an `(some calls unpriced)` line when `tracker.has_unpriced_calls` is true.
- Model label reads from `config.active_model` and refreshes on `config.changed`.

### 6.3 Number formatting

```python
def _format_k(n: int) -> str:
    if n < 1000:        return f"{n}"
    if n < 100_000:     return f"{n/1000:.1f}k"
    return f"{n//1000}k"
```

Examples: `312 → "312"`, `1500 → "1.5k"`, `12_345 → "12.3k"`, `123_456 → "123k"`.

### 6.4 Color palette (theme.py)

| Tag / state | Light hex | Dark hex |
|---|---|---|
| `[cost]` prefix | `#0a7d3a` | `#7ee2a8` |
| Light: idle | `#9ca3af` | `#6b7280` |
| Light: running | `#f59e0b` | `#fbbf24` |
| Light: ok | `#22c55e` | `#4ade80` |
| Light: error | `#ef4444` | `#f87171` |

### 6.5 i18n keys

Added to `prompts/locales/{en,zh}.yaml`:

```
usage.tooltip.input        "Session input tokens"        "本次会话输入 tokens"
usage.tooltip.output       "Session output tokens"       "本次会话输出 tokens"
usage.tooltip.cost         "Estimated session cost"      "本次会话估算费用"
usage.tooltip.unpriced     "(some calls unpriced)"       "（部分模型无报价）"
usage.light.idle           "No requests yet"             "尚未发送请求"
usage.light.running        "Request in progress"         "正在请求"
usage.light.ok             "Last request succeeded"      "上次请求成功"
usage.light.error          "Last request failed"         "上次请求失败"
```

The `[cost]` tag itself in LogsTab is not localized (treated as a stable marker).

## 7. Error handling & edge cases

1. **Provider returns no `usage` block.** Worker emits a `CallRecord` with `TokenUsage(0, 0)`, `usage_known=False`, and `cost_usd=None`. LogsTab and UsageBar check `usage_known` and substitute `?` for the token counts; cost renders as `~$—`. Light still goes green (the call itself succeeded).
2. **Stream cancelled.** No record appended; status returns to previous value. Plain log line emitted.
3. **Network/auth/rate-limit errors.** Tracker status goes red, totals unchanged, no record. Existing error log line stays as today.
4. **Image tokens.** Folded into `prompt_tokens` by OpenAI; not separately tracked or surcharged.
5. **Malformed/missing `prices.yaml`.** Empty table; calls render `~$—`; one-time warning logged.
6. **Mid-session model switch.** Each `CallRecord` carries its own `model`. Session totals sum across all models. UsageBar shows the **currently selected** model; totals do not reset on switch.
7. **Empty/very short input.** No special casing; preview is just the empty/short string.
8. **HTML injection in previews.** All preview text passes through `html.escape()` before insertion into HTML rows.
9. **Buffer overflow.** Tracker `_records` is `deque(maxlen=200)`; totals are maintained incrementally so dropped records don't affect cumulative numbers. LogsTab buffer is independent, also `maxlen=200`.
10. **App restart.** Tracker has no persistence layer; starts empty every launch.
11. **"Previous status" on cancel.** `UsageTracker` keeps a private `_prior_status` that is captured the moment `call_started` is invoked. `call_cancelled` restores from it. So cancelling a run after one prior success returns the light to green, not gray.
12. **Pricing file location.** `PricingTable.load` is called by `app.py` startup with the path `Path(__file__).parent.parent.parent / "config" / "prices.yaml"` (relative to the installed package). When packaged via PyInstaller, the file ships alongside under the same relative layout (PyInstaller datas spec to be added in the implementation plan).

## 8. Testing

Headless-friendly; works under the existing `QT_QPA_PLATFORM=offscreen` CI setup.

**`tests/test_pricing_table.py`** (pure Python):
- `test_load_valid_yaml` — two-model YAML loads, lookups succeed.
- `test_compute_returns_none_for_unknown_model`.
- `test_compute_math` — exact math against known rates.
- `test_load_missing_file_returns_empty` — no exception.
- `test_load_malformed_yaml_skips_bad_entries`.
- `test_negative_rates_rejected`.

**`tests/test_usage_tracker.py`** (Qt signals):
- `test_initial_state` — empty records, zero totals, status idle.
- `test_call_started_sets_running_status`.
- `test_call_completed_ok_appends_record_and_updates_totals`.
- `test_call_failed_sets_error_no_record`.
- `test_records_capped_at_200_but_totals_reflect_all`.
- `test_total_cost_is_none_when_no_priced_calls`.
- `test_has_unpriced_calls_flag`.
- `test_truncate_preview` — boundary, word-snapping, ellipsis only when cut.

**`tests/test_openai_provider_usage.py`**:
- `test_stream_includes_usage_request_param` — assert request JSON contains `stream_options.include_usage = true`.
- `test_stream_yields_usage_on_final_chunk` — fake SSE with usage block.
- `test_stream_without_usage_yields_none` — graceful when missing.

**`tests/test_logs_tab_cost.py`** (offscreen Qt):
- `test_log_cost_renders_html_row` — toPlainText contains all expected fields.
- `test_log_cost_escapes_html` — `<script>` rendered as literal text.
- `test_log_falls_back_to_dash_when_cost_none`.
- `test_log_renders_question_marks_when_usage_unknown`.

**`tests/test_usage_bar.py`** (offscreen Qt):
- `test_format_k_boundaries` — table of inputs/outputs.
- `test_dot_color_matches_status`.
- `test_tooltip_contents`.
- `test_unpriced_session_shows_dash`.

**`tests/test_inference_worker_usage_flow.py`** (integration):
- Mock provider yields known text chunks + final usage chunk.
- Assert tracker receives `call_started` → `call_recorded` → status `ok` in order.

## 9. Follow-ups (deferred)

- Settings UI for per-model price overrides (file-backed in `config.json`).
- Optional refresh of pricing from a community source (LiteLLM JSON) behind an opt-in button.
- Per-model session breakdown in the UsageBar tooltip.
- Persisted usage history across sessions (would need a small SQLite layer or a JSONL log).
