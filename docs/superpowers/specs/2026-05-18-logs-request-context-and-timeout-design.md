# Logs: Request Context Capture + Configurable Timeout

- **Date:** 2026-05-18
- **Status:** design approved, implementation pending
- **Related specs:** `2026-05-17-token-cost-debug-design.md` (CallRecord/cost row), `2026-05-15-spiresight-mvp-design.md`
- **Sibling specs (future):** model profiles & per-feature model; provider completion + OpenAI-compatible relays

## 1. Motivation

Two pain points share root causes and a single surface:

1. Inference calls frequently time out under thinking models. The current OpenAI provider hardcodes `httpx.Timeout(60.0, connect=10.0)` with no way to raise it short of editing source.
2. When a call hangs, errors, or returns an unexpected answer, there is no in-app view of what was actually sent. The Logs tab today shows only a one-line cost summary plus arbitrary status text.

We will:

- Capture each request's `system` prompt, `messages` array, and a small parameter dict at call dispatch, attach it to a per-call log row, and stream the row's final response (or terminal error) back into the same row when the call completes.
- Render rows as a list of collapsible widgets (one row per call) replacing the current `QTextEdit`-backed view.
- Expose a global `request_timeout_seconds` in Settings (default 180s, range 30–600s) wired through to the OpenAI provider.

## 2. Non-goals

- Persisting logs across restarts. The buffer remains in-memory and capped at 200 entries.
- Searching, filtering, or grouping log rows.
- Per-feature timeout overrides — global only this round. Per-feature config belongs in the upcoming profile spec.
- Implementing Anthropic / Gemini provider streams. Their constructors will accept a `ProviderOptions` parameter but continue to raise `NotImplementedError`.
- Surfacing thinking effort, model tiers, or third-party `base_url` configuration — those are the next two specs.
- Embedding image data in logs. Images render as a one-line summary (`PNG, 245 KB, 1920×1080`).

## 3. Architecture overview

```
┌─────────────────────┐   request_logged(RequestLog)     ┌─────────────────────┐
│  InferenceWorker /  │ ───────────────────────────────► │     MainWindow      │
│  InspectWorker      │   response_logged(id,status,…)   │  (signal forwarder) │
│                     │ ───────────────────────────────► │                     │
└─────────┬───────────┘                                   └──────────┬──────────┘
          │ builds RequestLog from RequestSnapshot                   │
          │                                                          ▼
          │                                                ┌─────────────────────┐
          ▼                                                │      LogsTab        │
┌─────────────────────┐                                    │  - log_request()    │
│  InferenceRunner    │   snapshot_quick_action / …        │  - update_response()│
│  - snapshot_*()     │ ◄────────────────────────────────  │  - log()/log_cost() │
│  - run_*()          │                                    │  - QSA + QVBoxLayout│
└─────────────────────┘                                    └─────────────────────┘
```

Data flow:

1. UI builds a worker via the existing `for_quick_action` / `for_follow_up` factory or constructs an `InspectWorker`. The factory now also calls a new `InferenceRunner.snapshot_*` method to materialize what the next stream call will send, and stores the resulting `RequestSnapshot` on the worker.
2. Worker `run()` emits `request_logged(RequestLog)` immediately, before invoking the stream generator. `LogsTab.log_request()` creates a `LogRow` with status `sent`.
3. As the stream runs, chunks still flow through existing signals (`chunk`, eventually `usage_recorded`, `finished_ok` / `failed` / `cancelled`). The log row body is not updated chunk-by-chunk.
4. In a single `finally` block, the worker emits `response_logged(correlation_id, status, full_text, error_or_none)`. `LogsTab.update_response()` finds the row by id and rewrites its Response section + status badge.

## 4. Data model (`core/usage.py`)

```python
from typing import Literal
from uuid import uuid4

LogStatus = Literal["sent", "ok", "error", "cancelled", "timeout"]

@dataclass(frozen=True)
class LoggedMessage:
    role: Literal["system", "user", "assistant"]
    text: str
    image_summary: str | None   # e.g. "PNG, 245 KB, 1920×1080"; None when no image

@dataclass
class RequestLog:
    correlation_id: str         # uuid4().hex[:8]
    timestamp: datetime         # UTC, when request_logged is emitted
    provider: str               # "openai" | "anthropic" | "gemini"
    model: str
    system: str                 # final composed system prompt
    messages: list[LoggedMessage]
    params: dict[str, object]   # provider-agnostic display dict (json_mode, has_images, …)
    response: str = ""
    status: LogStatus = "sent"
    error: str | None = None
    finished_at: datetime | None = None
```

Design choices:

- `correlation_id` is 8-hex (~4 billion) — short enough to print in a header, large enough to be unique within a 200-row buffer.
- Image bytes are never stored on the log. `image_summary` is computed when the snapshot is built (PIL already imported in `main_window.py` — reuse the loader).
- `params` is a loose dict so providers can populate provider-specific entries (json_mode, has_images, future thinking-effort) without a schema migration each time. UI renders each entry as `key: repr(value)`.
- `response` is mutable so `update_response` can rewrite in place.

## 5. Runner snapshot API (`core/runner.py`)

Refactor `run_quick_action`, `run_follow_up`, `inspect` to first produce a snapshot, then pass it to the provider. UI calls only the `snapshot_*` half when constructing a `RequestLog`.

```python
@dataclass(frozen=True)
class RequestSnapshot:
    provider: str
    model: str                   # resolved model id, not raw config string
    system: str                  # final composed system (includes RunState block when applicable)
    messages: tuple[Message, ...]
    params: dict[str, object]

class InferenceRunner:
    def snapshot_quick_action(self, request: QuickActionRequest) -> RequestSnapshot: ...
    def snapshot_follow_up(
        self, request: FollowUpRequest, history: tuple[Message, ...]
    ) -> RequestSnapshot: ...
    def snapshot_inspect(self, images: list[bytes]) -> RequestSnapshot: ...
```

`RequestSnapshot.messages` is the canonical form even for `run_quick_action` (which historically used `user_text + images`): the snapshot wraps the single quick-action turn into one `Message(role="user", text=user_text, image_png=image_png)`. `provider.stream()` already supports a `messages` parameter (introduced for follow-up), so all three run paths converge on:

```python
def run_quick_action(self, request, *, cancel_event):
    snap = self.snapshot_quick_action(request)
    provider, _ = self._get_provider_and_model()
    # capability check stays here, using snap.model + snap.params
    yield from provider.stream(
        model=snap.model,
        system=snap.system,
        messages=list(snap.messages),
        cancel_event=cancel_event,
        json_mode=snap.params.get("json_mode", False),
    )
```

`run_follow_up` and `inspect` follow the identical shape. Snapshot construction is the single place where the system block is composed and messages are assembled, so UI logging and execution can never disagree.

## 6. Worker integration (`ui/workers/`)

Add to both `InferenceWorker` and `InspectWorker`:

```python
class InferenceWorker(QThread):
    request_logged = Signal(object)                          # RequestLog
    response_logged = Signal(str, str, str, object)
    # (correlation_id, status: LogStatus, response_text, error_or_None)
```

Factory changes (`for_quick_action`, `for_follow_up`): accept the runner, call `runner.snapshot_quick_action(request)` (or follow_up variant) inside the factory, and store on the worker:

- `self._snapshot: RequestSnapshot` — the assembled snapshot.
- `self._correlation_id: str` — freshly generated via `uuid4().hex[:8]`.

For `InspectWorker`, the same wiring: caller passes runner + frames; worker's `__init__` calls `runner.snapshot_inspect(frames)` and stores `_snapshot` + `_correlation_id`.

`_build_request_log()` is a helper on the worker that combines `self._snapshot`, `self._correlation_id`, and `datetime.now(tz=timezone.utc)` into a `RequestLog`. Image-summary text for each `LoggedMessage` is computed here by `Image.open(io.BytesIO(png))` and formatting `f"PNG, {len(png)//1024} KB, {im.width}×{im.height}"`. PIL decodes the PNG header only — cheap; runs in the worker thread, not the UI thread.

`run()` skeleton (applies to both workers):

```python
def run(self) -> None:
    self.run_started.emit(self._model_id, self._input_preview)
    self.request_logged.emit(self._build_request_log())

    text_buffer: list[str] = []
    captured_usage: TokenUsage | None = None
    status: LogStatus = "ok"
    error_msg: str | None = None
    exc_to_emit: Exception | None = None

    try:
        for c in self._run_fn(self._cancel):
            if self._cancel.is_set():
                status = "cancelled"
                break
            if c.text_delta:
                text_buffer.append(c.text_delta)
                self.chunk.emit(c.text_delta)
            if c.usage is not None:
                captured_usage = c.usage
        if self._cancel.is_set():
            status = "cancelled"
    except RequestTimeoutError as exc:
        status, error_msg = "timeout", str(exc)
        exc_to_emit = exc
    except Exception as exc:
        status, error_msg = "error", f"{type(exc).__name__}: {exc}"
        exc_to_emit = exc
    finally:
        full_text = "".join(text_buffer)
        # Order matters: log first so UI updates regardless of downstream signal handling.
        self.response_logged.emit(self._correlation_id, status, full_text, error_msg)
        if status == "cancelled":
            self.cancelled.emit()
        elif status == "ok":
            self.usage_recorded.emit(self._build_call_record(captured_usage, full_text))
            self.finished_ok.emit()
        else:
            self.failed.emit(exc_to_emit)
```

`MainWindow` connects:

```python
worker.request_logged.connect(self._logs_tab.log_request)
worker.response_logged.connect(self._logs_tab.update_response)
```

`InspectWorker` connections mirror the above.

## 7. `LogRow` widget (`ui/widgets/log_row.py`)

New widget. Structure:

```
LogRow (QFrame, objectName="LogRow", dynamic property status=<LogStatus>)
├─ header (QWidget) — clickable, toggles body
│  ├─ chevron QLabel (▶ / ▼)
│  ├─ summary QLabel ("[12:03:45] [sent] openai/gpt-4o · a3f2c1de")
│  ├─ stretch
│  └─ "Copy" QToolButton
└─ body (QWidget, visible=False)
   ├─ "System prompt"      → QPlainTextEdit (read-only, monospace)
   ├─ "Messages (N)"       → vertical stack of (role tag + QPlainTextEdit) pairs
   │                         each user message with image appends image_summary on its own line
   ├─ "Params"             → QPlainTextEdit, one "key: value" per line
   └─ "Response"           → QPlainTextEdit, initial text "[streaming…]"
```

API:

```python
class LogRow(QFrame):
    def __init__(self, record: RequestLog, parent: QWidget | None = None) -> None: ...
    @property
    def correlation_id(self) -> str: ...
    def set_response(self, text: str, status: LogStatus, error: str | None) -> None: ...
    def toggle(self) -> None: ...
    def to_plain_text(self) -> str: ...   # full header + body content, independent of fold state
```

Behavior:

- Click anywhere in `header` toggles body visibility via direct `setVisible`; no animation. `mousePressEvent` on header forwards to `toggle()`.
- Status drives a QSS dynamic property; QSS files set the header label color per status.
- Each `QPlainTextEdit` uses `setMaximumBlockCount(2000)`; on overflow the widget keeps the most recent 2000 lines and the row appends `"… [truncated]"` to the visible text once when truncation first applies.
- `Copy` button copies `to_plain_text()` (full body, regardless of current fold state) via `QGuiApplication.clipboard()`.
- `set_response(text, status, error)`:
  - On `ok`: response edit shows `text`.
  - On `cancelled`: shows `text` if non-empty, else `(no output)`.
  - On `timeout` / `error`: shows `text` if any, then a blank line, then `f"[error] {error}"`.
  - Status badge in the header updates accordingly.

Also add a sibling `TextRow(QFrame)` for the existing plain `log()` lines and `log_cost()` lines — header only, no body, no fold toggle. Same `to_plain_text()` contract.

## 8. `LogsTab` refactor (`ui/tabs/logs_tab.py`)

Replace the `QTextEdit` and its HTML buffer with a `QScrollArea` containing a `QVBoxLayout`. New entries are inserted at the top (`layout.insertWidget(0, row)`); the layout's last item remains a permanent `addStretch(1)` so collapsed content does not stretch vertically.

State:

```python
MAX_ROWS = 200

class LogsTab(QWidget):
    def __init__(self, locale, parent=None) -> None: ...
    # existing
    def log(self, message: str) -> None: ...
    def log_cost(self, record: CallRecord) -> None: ...
    # new
    def log_request(self, record: RequestLog) -> None: ...
    def update_response(
        self, correlation_id: str, response: str,
        status: LogStatus, error: str | None = None,
    ) -> None: ...
```

`log_request`:

1. Build a `LogRow(record)`, insert at top, store in `self._rows: dict[str, LogRow]`.
2. Call `self._enforce_cap()` which trims the layout from the bottom while `widget_count() > MAX_ROWS`, deleting and popping evicted rows from `self._rows` if they were LogRows.

`update_response`:

1. Look up `self._rows.get(correlation_id)`. If missing, `_log.debug` and return silently.
2. Call `row.set_response(response, status, error)`.

`Copy all` button concatenates `row.to_plain_text()` for every visible widget, top-to-bottom, joined by `"\n\n---\n\n"`, and pushes to the clipboard. `Clear` removes every row and empties `self._rows`.

## 9. Timeout configuration

### 9.1 Schema (`config/schema.py`)

```python
class AppConfig(BaseSettings):
    ...
    request_timeout_seconds: int = 180
```

Existing user config files lacking the field fall back to the default.

### 9.2 Settings dialog (`ui/windows/settings_dialog.py`)

`General` tab adds a row:

```
Request timeout (seconds)   [ QSpinBox: 30–600, step 30, default 180 ]
```

`_apply_and_accept` writes `self._config.request_timeout_seconds = self._timeout.value()`.

### 9.3 Provider plumbing

Extend the provider factory signature:

```python
@dataclass(frozen=True)
class ProviderOptions:
    request_timeout_seconds: int = 180

ProviderFactory = Callable[[str, ProviderConfig, ProviderOptions], LLMProvider]
```

`InferenceRunner._get_provider_and_model` builds `ProviderOptions` from `self._config.request_timeout_seconds` and passes it to the factory.

`OpenAIProvider.__init__` stores `options`. `stream()` builds:

```python
httpx.Timeout(self._options.request_timeout_seconds, connect=15.0)
```

`AnthropicProvider.__init__` and `GeminiProvider.__init__` accept `options` but ignore it — placeholder for future spec; this keeps the registry signature stable.

Update `llm/registry.py` and all call sites (main entrypoint, tests) to pass options.

### 9.4 Distinguishing timeout from other network errors

Add a `RequestTimeoutError(NetworkError)` subclass to `llm/errors.py`. `OpenAIProvider.stream` catches `httpx.TimeoutException` (read or connect) and raises:

```python
raise RequestTimeoutError(
    f"Request exceeded {options.request_timeout_seconds}s timeout "
    f"(elapsed {elapsed:.1f}s)"
) from exc
```

The worker matches on this subclass to mark the row as `timeout` rather than generic `error`.

## 10. Terminal row states

| Worker outcome | Row status | Header tag | Response body |
|---|---|---|---|
| Stream completes naturally | `ok` | `[ok]` | full response text |
| `cancel_event.is_set()` inside loop | `cancelled` | `[cancelled]` | partial text or `(no output)` |
| `RequestTimeoutError` | `timeout` (red) | `[timeout]` | partial text + `\n[error] <msg>` |
| Any other exception (`AuthError`, `RateLimitError`, `NetworkError`, `MissingAPIKey`, `MissingCapabilityError`, `ValueError`, …) | `error` (red) | `[error]` | partial text (often empty) + `\n[error] <ClassName>: <msg>` |

`MissingAPIKey` is raised inside `_get_provider_and_model` before any stream chunk. `request_logged` has already fired during worker startup, so the row exists; the `finally` block fires `response_logged` with `status="error"` and the row paints red.

## 11. i18n

Add to `locales/en.yaml` and `locales/zh.yaml`:

```
logs:
  section:
    system: "System prompt"
    messages: "Messages"
    params: "Params"
    response: "Response"
  streaming_placeholder: "[streaming…]"
  copy_row: "Copy"
  status:
    sent: "sent"
    ok: "ok"
    error: "error"
    cancelled: "cancelled"
    timeout: "timeout"
settings:
  request_timeout_label: "Request timeout (seconds)"
```

Chinese strings translated correspondingly. The status labels are intentionally short and ASCII so they read in monospace headers regardless of locale; only the section titles and settings label localize.

## 12. QSS

`resources/qss/dark_fantasy.qss` (and other themes) add:

```
QFrame#LogRow { background: transparent; }
QFrame#LogRow QLabel#LogRowSummary { font-family: ui-monospace, Menlo, monospace; font-size: 11.5px; }
QFrame#LogRow[status="sent"]      QLabel#LogRowSummary { color: #888; }
QFrame#LogRow[status="ok"]        QLabel#LogRowSummary { color: <theme fg>; }
QFrame#LogRow[status="error"]     QLabel#LogRowSummary { color: #d65a5a; }
QFrame#LogRow[status="timeout"]   QLabel#LogRowSummary { color: #d65a5a; }
QFrame#LogRow[status="cancelled"] QLabel#LogRowSummary { color: #666; }
QFrame#LogRow QPlainTextEdit { font-family: ui-monospace, Menlo, monospace; font-size: 11px; }
```

`USAGE_COLORS` in `ui/theme.py` gains the four new keys for code paths that need the color outside of QSS (none currently expected, but reserved).

## 13. Testing

### Pure Python (no Qt)

- `tests/core/test_runner_snapshot.py`
  - `snapshot_quick_action` includes the composed RunState block when a `RunStateStore` carries state, and excludes it when empty.
  - `snapshot_follow_up` returns `len(history) + 1` messages with the appended user message last.
  - `snapshot_inspect` populates `params["json_mode"] = True` and resolves the model id.
- `tests/core/test_request_log.py`
  - `correlation_id` length 8, hex characters only.
  - `LoggedMessage.image_summary` is None iff `image_png` was None.
- `tests/llm/test_openai_timeout.py`
  - `OpenAIProvider` built with `ProviderOptions(request_timeout_seconds=5)` actually configures `httpx.Timeout(5.0, connect=15.0)` (introspect on the provider after construction or via dependency-injected client).
  - A simulated `httpx.ReadTimeout` is wrapped into `RequestTimeoutError`, not `NetworkError`.

### Qt (pytest-qt)

- `tests/ui/test_log_row.py`
  - Constructs default `RequestLog`; body starts hidden.
  - Click on header toggles body visibility.
  - `set_response("hello", "ok", None)` updates header status to `ok` and Response edit to `hello`.
  - `to_plain_text()` returns full body content even when body hidden.
- `tests/ui/test_logs_tab.py`
  - `log_request(r)` adds one LogRow and registers in `_rows[r.correlation_id]`.
  - 201 sequential `log_request` calls evict the oldest row from layout and from `_rows`.
  - `update_response("missing-id", "x", "ok", None)` is a no-op (no exception, no row created).
- `tests/ui/test_inference_worker_logging.py`
  - Fake runner yielding three chunks then raising `RequestTimeoutError`: assert `request_logged` fires before any chunk; `response_logged` fires once with `status="timeout"` and `response_text == "chunk1chunk2chunk3"` (partial); `failed` is emitted.
  - Cancellation mid-stream: `response_logged` fires with `status="cancelled"` and the accumulated partial text.

### Manual

- Trigger Quick Action: confirm a `[sent]` row appears immediately and expanding it shows the live payload, even if the network is artificially slowed. After the stream completes the row turns `[ok]` and Response fills in.
- Lower `request_timeout_seconds` to 30 in Settings, kick off a slow inspect: the row turns `[timeout]` red and the Response body contains the elapsed-time error message.

## 14. Risks and mitigations

- **Snapshot drift.** Snapshot construction must match what the runner actually sends. Mitigation: factor the common logic into `snapshot_*` and have `run_*` call it, so there is exactly one path.
- **Image summary cost.** `Image.open(io.BytesIO(png)).size` decodes the PNG header but not pixels — cheap. Still, run it inside the worker thread, not on the UI thread.
- **`QPlainTextEdit` count.** Each LogRow holds 4+ `QPlainTextEdit` instances; at 200 rows that is 800 widgets. Acceptable on desktop but worth keeping `MAX_ROWS` capped.
- **Settings hot-reload.** Changing `request_timeout_seconds` only affects providers built *after* the change. Since `_get_provider_and_model` builds a new provider per call, this is automatic — but document it in `settings_dialog`'s tooltip so users don't expect the running call to retarget.

## 15. Acceptance

- All tests in §13 pass.
- A manual session reproduces the §13 manual checks.
- `request_timeout_seconds` is persisted across restarts via the existing `ConfigStore`.
- `Logs` tab continues to honor `Copy all` and `Clear` as today.
- Anthropic / Gemini providers still raise `NotImplementedError`, but their constructors accept `ProviderOptions` without TypeError.
