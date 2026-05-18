# Logs Request-Context + Configurable Timeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture each inference request's system prompt / messages / params / response into expandable per-call rows in the Logs tab, and expose a global `request_timeout_seconds` in Settings (default 180s, range 30–600s) wired through to the OpenAI provider.

**Architecture:** New `RequestLog` and `LoggedMessage` dataclasses carry payload snapshots. `InferenceRunner` gains pure `snapshot_*` methods so workers can materialize the exact payload up-front; existing `run_*` methods are refactored to call those same snapshots. Workers emit two new signals (`request_logged`, `response_logged`) consumed by `LogsTab`, which is rewritten from a `QTextEdit` HTML buffer into a `QScrollArea` + `QVBoxLayout` of `LogRow` / `TextRow` widgets. Timeout reaches providers via a new `ProviderOptions` parameter on the provider factory; `OpenAIProvider` translates `httpx.TimeoutException` into a new `RequestTimeoutError` subclass that workers recognize.

**Tech Stack:** Python 3.x, PySide6 (Qt for Python), httpx, pydantic v2, pytest + pytest-qt, PIL (Pillow), pyyaml.

**Reference spec:** `docs/superpowers/specs/2026-05-18-logs-request-context-and-timeout-design.md`

---

## File Structure

**Create:**
- `src/spiresight/ui/widgets/log_row.py` — `LogRow` (collapsible request row) and `TextRow` (single-line row).
- `tests/test_request_log.py` — pure-Python dataclass tests.
- `tests/test_runner_snapshot.py` — snapshot method tests.
- `tests/test_openai_timeout.py` — OpenAI timeout / `RequestTimeoutError` tests.
- `tests/test_log_row.py` — `LogRow` widget tests (Qt).
- `tests/test_logs_tab_request.py` — `LogsTab.log_request` / `update_response` tests (Qt).
- `tests/test_inference_worker_logging.py` — worker `request_logged` / `response_logged` signal tests (Qt).

**Modify:**
- `src/spiresight/core/usage.py` — add `RequestLog`, `LoggedMessage`, `LogStatus`.
- `src/spiresight/core/runner.py` — add `RequestSnapshot`, `snapshot_quick_action`, `snapshot_follow_up`, `snapshot_inspect`; refactor `run_*` to call them.
- `src/spiresight/llm/provider.py` — add `ProviderOptions` dataclass; widen `LLMProvider` protocol.
- `src/spiresight/llm/errors.py` — add `RequestTimeoutError(NetworkError)`.
- `src/spiresight/llm/registry.py` — pass `ProviderOptions` through the factory.
- `src/spiresight/llm/providers/openai_provider.py` — read timeout from options, wrap `httpx.TimeoutException` as `RequestTimeoutError`.
- `src/spiresight/llm/providers/anthropic_provider.py` — accept `ProviderOptions` in `__init__` (still raises NotImplementedError on stream).
- `src/spiresight/llm/providers/gemini_provider.py` — same.
- `src/spiresight/config/schema.py` — add `AppConfig.request_timeout_seconds`.
- `src/spiresight/ui/windows/settings_dialog.py` — add timeout `QSpinBox` to General tab.
- `src/spiresight/ui/workers/inference_worker.py` — store snapshot + correlation_id; new signals; rewrite `run()` with `finally`.
- `src/spiresight/ui/workers/inspect_worker.py` — same.
- `src/spiresight/ui/tabs/logs_tab.py` — rewrite around `QScrollArea` + `QVBoxLayout`.
- `src/spiresight/ui/windows/main_window.py` — connect new worker signals.
- `src/spiresight/prompts/locales/en.yaml`, `src/spiresight/prompts/locales/zh.yaml` — i18n keys.
- `src/spiresight/resources/qss/*.qss` — `LogRow` selectors.
- `src/spiresight/ui/theme.py` — add status color keys (reserved).

---

## Conventions

- Run a single test: `pytest tests/test_X.py::test_Y -v`
- Run the full suite: `pytest -q`
- All new code lives under `src/spiresight/`; tests under `tests/`.
- Commit after each task once tests pass. Conventional-commit prefixes: `feat:`, `refactor:`, `test:`, `fix:`, `chore:`.
- For Qt tests, `pytest-qt` exposes a `qtbot` fixture. To check signal emissions use `with qtbot.waitSignal(obj.signal_name, timeout=2000) as blocker:` and inspect `blocker.args`.

---

### Task 1: `RequestLog` + `LoggedMessage` dataclasses

**Files:**
- Modify: `src/spiresight/core/usage.py` (append at end, after existing classes)
- Test: `tests/test_request_log.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_request_log.py`:

```python
from datetime import datetime, timezone

from spiresight.core.usage import RequestLog, LoggedMessage


def test_logged_message_image_summary_optional():
    m1 = LoggedMessage(role="user", text="hi", image_summary=None)
    m2 = LoggedMessage(role="user", text="look", image_summary="PNG, 245 KB, 1920×1080")
    assert m1.image_summary is None
    assert m2.image_summary == "PNG, 245 KB, 1920×1080"


def test_request_log_defaults_and_mutability():
    now = datetime.now(tz=timezone.utc)
    record = RequestLog(
        correlation_id="a3f2c1de",
        timestamp=now,
        provider="openai",
        model="gpt-4o",
        system="you are helpful",
        messages=[LoggedMessage(role="user", text="hi", image_summary=None)],
        params={"json_mode": False, "has_images": False},
    )
    assert record.response == ""
    assert record.status == "sent"
    assert record.error is None
    assert record.finished_at is None
    # response is mutable so update_response can rewrite in place
    record.response = "world"
    record.status = "ok"
    assert record.response == "world"
    assert record.status == "ok"


def test_correlation_id_is_eight_hex():
    from uuid import uuid4
    cid = uuid4().hex[:8]
    assert len(cid) == 8
    assert all(c in "0123456789abcdef" for c in cid)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_request_log.py -v`
Expected: FAIL with `ImportError: cannot import name 'RequestLog'`.

- [ ] **Step 3: Implement `RequestLog` + `LoggedMessage`**

Edit `src/spiresight/core/usage.py`. Add imports at top (alongside existing):

```python
from typing import Literal
```

Append at the end of the file:

```python
LogStatus = Literal["sent", "ok", "error", "cancelled", "timeout"]


@dataclass(frozen=True)
class LoggedMessage:
    role: Literal["system", "user", "assistant"]
    text: str
    image_summary: str | None  # e.g. "PNG, 245 KB, 1920×1080"; None when no image


@dataclass
class RequestLog:
    correlation_id: str          # uuid4().hex[:8]
    timestamp: datetime          # UTC, when request_logged is emitted
    provider: str                # "openai" | "anthropic" | "gemini"
    model: str
    system: str                  # final composed system prompt
    messages: list[LoggedMessage]
    params: dict[str, object]    # provider-agnostic display dict
    response: str = ""
    status: LogStatus = "sent"
    error: str | None = None
    finished_at: datetime | None = None
```

`datetime` and `dataclass` are already imported in this module.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_request_log.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/core/usage.py tests/test_request_log.py
git commit -m "feat(usage): add RequestLog + LoggedMessage dataclasses"
```

---

### Task 2: `ProviderOptions` + `RequestTimeoutError`

**Files:**
- Modify: `src/spiresight/llm/provider.py`
- Modify: `src/spiresight/llm/errors.py`
- Test: `tests/test_provider_contract.py` (existing — add cases)

- [ ] **Step 1: Inspect current errors and protocol**

Run: `cat src/spiresight/llm/errors.py src/spiresight/llm/provider.py`
Note the existing `NetworkError` class — `RequestTimeoutError` will subclass it.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_provider_contract.py`:

```python
from spiresight.llm.errors import NetworkError, RequestTimeoutError
from spiresight.llm.provider import ProviderOptions


def test_provider_options_defaults():
    opts = ProviderOptions()
    assert opts.request_timeout_seconds == 180


def test_provider_options_frozen():
    import dataclasses
    opts = ProviderOptions(request_timeout_seconds=60)
    assert opts.request_timeout_seconds == 60
    # frozen dataclass -> assignment raises
    try:
        opts.request_timeout_seconds = 30  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("ProviderOptions should be frozen")


def test_request_timeout_error_is_network_error():
    exc = RequestTimeoutError("Request exceeded 60s timeout (elapsed 61.2s)")
    assert isinstance(exc, NetworkError)
    assert "60s" in str(exc)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_provider_contract.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 4: Add `RequestTimeoutError`**

Edit `src/spiresight/llm/errors.py`. Locate `class NetworkError` and add below it:

```python
class RequestTimeoutError(NetworkError):
    """Provider read/connect timeout — raised when httpx.TimeoutException fires."""
```

- [ ] **Step 5: Add `ProviderOptions`**

Edit `src/spiresight/llm/provider.py`. Add to the dataclass section near the top (after `from dataclasses import dataclass`):

```python
@dataclass(frozen=True)
class ProviderOptions:
    request_timeout_seconds: int = 180
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_provider_contract.py -v`
Expected: all existing tests still pass + 3 new passes.

- [ ] **Step 7: Commit**

```bash
git add src/spiresight/llm/errors.py src/spiresight/llm/provider.py tests/test_provider_contract.py
git commit -m "feat(llm): add ProviderOptions + RequestTimeoutError"
```

---

### Task 3: `AppConfig.request_timeout_seconds`

**Files:**
- Modify: `src/spiresight/config/schema.py`
- Test: `tests/test_config_store.py` (existing — add cases)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config_store.py`:

```python
def test_app_config_request_timeout_default():
    from spiresight.config.schema import AppConfig
    cfg = AppConfig()
    assert cfg.request_timeout_seconds == 180


def test_app_config_request_timeout_override():
    from spiresight.config.schema import AppConfig
    cfg = AppConfig(request_timeout_seconds=60)
    assert cfg.request_timeout_seconds == 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_store.py::test_app_config_request_timeout_default -v`
Expected: FAIL with `AttributeError: 'AppConfig' object has no attribute 'request_timeout_seconds'`.

- [ ] **Step 3: Add field to `AppConfig`**

Edit `src/spiresight/config/schema.py`. Inside `class AppConfig`, after `include_screenshot_default`:

```python
    request_timeout_seconds: int = 180
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config_store.py -v`
Expected: all pass including the 2 new tests.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/config/schema.py tests/test_config_store.py
git commit -m "feat(config): expose request_timeout_seconds (default 180s)"
```

---

### Task 4: Provider factory widening to accept `ProviderOptions`

**Files:**
- Modify: `src/spiresight/llm/registry.py`
- Modify: `src/spiresight/llm/providers/openai_provider.py` (constructor only)
- Modify: `src/spiresight/llm/providers/anthropic_provider.py`
- Modify: `src/spiresight/llm/providers/gemini_provider.py`
- Modify: `src/spiresight/core/runner.py` (only the `ProviderFactory` typedef + the call site)
- Test: `tests/test_registry.py` (existing — add case), `tests/test_provider_stubs.py` (existing — ensure stubs still accept the new arg)

- [ ] **Step 1: Read the current registry**

Run: `cat src/spiresight/llm/registry.py`
Identify the `make_provider(name, config)` factory and its callers.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_registry.py`:

```python
def test_registry_builds_openai_with_options():
    from spiresight.config.schema import ProviderConfig
    from spiresight.llm.provider import ProviderOptions
    from spiresight.llm import registry

    cfg = ProviderConfig(api_key="sk-test")
    opts = ProviderOptions(request_timeout_seconds=42)
    provider = registry.make_provider("openai", cfg, opts)
    assert provider.name == "openai"
    # Stored on the provider for later use:
    assert getattr(provider, "_options", None) is opts
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_registry.py::test_registry_builds_openai_with_options -v`
Expected: FAIL — `make_provider` does not accept three positional args yet.

- [ ] **Step 4: Update each provider constructor**

In `src/spiresight/llm/providers/openai_provider.py`, change:

```python
class OpenAIProvider:
    name = "openai"

    def __init__(self, config: ProviderConfig, options: ProviderOptions | None = None) -> None:
        self._config = config
        self._options = options or ProviderOptions()
```

Add the import: `from spiresight.llm.provider import ProviderOptions, StreamChunk`.

In `src/spiresight/llm/providers/anthropic_provider.py`:

```python
from spiresight.llm.provider import ProviderOptions, StreamChunk

class AnthropicProvider:
    name = "anthropic"

    def __init__(self, config: ProviderConfig, options: ProviderOptions | None = None) -> None:
        self._config = config
        self._options = options or ProviderOptions()
```

In `src/spiresight/llm/providers/gemini_provider.py`: mirror the Anthropic edit.

- [ ] **Step 5: Update `make_provider` in `registry.py`**

Locate the factory and change its signature:

```python
def make_provider(
    name: str,
    config: ProviderConfig,
    options: ProviderOptions | None = None,
) -> LLMProvider:
    options = options or ProviderOptions()
    if name == "openai":
        return OpenAIProvider(config, options)
    if name == "anthropic":
        return AnthropicProvider(config, options)
    if name == "gemini":
        return GeminiProvider(config, options)
    raise KeyError(f"Unknown provider: {name}")
```

Add the import at the top: `from spiresight.llm.provider import ProviderOptions, LLMProvider`.

- [ ] **Step 6: Update `core/runner.py` factory typedef + call site**

In `src/spiresight/core/runner.py`, change:

```python
ProviderFactory = Callable[[str, ProviderConfig, ProviderOptions], LLMProvider]
```

Add the import: `from spiresight.llm.provider import LLMProvider, ProviderOptions, StreamChunk`.

In `_get_provider_and_model`, before calling `self._factory`:

```python
options = ProviderOptions(
    request_timeout_seconds=self._config.request_timeout_seconds,
)
provider = self._factory(self._config.active_provider, provider_cfg, options)
```

(Same for the `inspect()` body, which currently calls `self._factory` directly — pass `options` there too.)

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_registry.py tests/test_provider_stubs.py tests/test_inference_runner.py -v`
Expected: all pass. If a test fails because it called `make_provider(name, cfg)` with two args, our new keyword default keeps it green.

- [ ] **Step 8: Commit**

```bash
git add src/spiresight/llm src/spiresight/core/runner.py tests/test_registry.py
git commit -m "refactor(llm): thread ProviderOptions through provider factory"
```

---

### Task 5: OpenAI provider — honor timeout, wrap `httpx.TimeoutException`

**Files:**
- Modify: `src/spiresight/llm/providers/openai_provider.py`
- Test: `tests/test_openai_timeout.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_openai_timeout.py`:

```python
import httpx
import pytest

from spiresight.config.schema import ProviderConfig
from spiresight.llm.errors import RequestTimeoutError
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.openai_provider import OpenAIProvider


def test_openai_provider_stores_options():
    p = OpenAIProvider(ProviderConfig(api_key="sk-x"), ProviderOptions(request_timeout_seconds=42))
    assert p._options.request_timeout_seconds == 42


def test_openai_provider_wraps_httpx_timeout(monkeypatch):
    """Simulate httpx.ReadTimeout during stream() and assert RequestTimeoutError is raised."""

    class _FakeStream:
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def __init__(self, *a, **kw):
            raise httpx.ReadTimeout("read timed out")

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def stream(self, *a, **kw): return _FakeStream()

    monkeypatch.setattr(httpx, "Client", _FakeClient)

    p = OpenAIProvider(
        ProviderConfig(api_key="sk-x"),
        ProviderOptions(request_timeout_seconds=5),
    )
    with pytest.raises(RequestTimeoutError) as exc_info:
        # consume generator to trigger the request
        list(p.stream(model="gpt-4o", system="s", user_text="hi"))
    assert "5s timeout" in str(exc_info.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_openai_timeout.py -v`
Expected: FAIL — currently `httpx.ReadTimeout` is caught and re-raised as `NetworkError`, not `RequestTimeoutError`.

- [ ] **Step 3: Update `OpenAIProvider.stream`**

In `src/spiresight/llm/providers/openai_provider.py`:

a. Replace the `httpx.Timeout(60.0, connect=10.0)` call with:

```python
timeout = httpx.Timeout(self._options.request_timeout_seconds, connect=15.0)
```

b. Replace the `except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException) as exc:` block with two separate handlers:

```python
        except httpx.TimeoutException as exc:
            raise RequestTimeoutError(
                f"Request exceeded {self._options.request_timeout_seconds}s timeout "
                f"({type(exc).__name__})"
            ) from exc
        except (httpx.ConnectError, httpx.ReadError) as exc:
            raise NetworkError(str(exc)) from exc
```

c. Add the import: `from spiresight.llm.errors import AuthError, MissingAPIKey, NetworkError, RateLimitError, RequestTimeoutError`.

Update the `httpx.Client(timeout=...)` line to use the new local `timeout`:

```python
with httpx.Client(timeout=timeout) as client:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_openai_timeout.py tests/test_openai_provider.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/llm/providers/openai_provider.py tests/test_openai_timeout.py
git commit -m "feat(openai): honor ProviderOptions.request_timeout_seconds + wrap httpx timeouts"
```

---

### Task 6: `RequestSnapshot` + `InferenceRunner.snapshot_*`

**Files:**
- Modify: `src/spiresight/core/runner.py`
- Test: `tests/test_runner_snapshot.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_runner_snapshot.py`:

```python
from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.core.messages import Message
from spiresight.core.request import FollowUpRequest, QuickActionRequest
from spiresight.core.runner import InferenceRunner, RequestSnapshot
from spiresight.llm.models import ModelInfo
from spiresight.llm.capabilities import Capability


@pytest.fixture
def runner():
    cfg = AppConfig(active_provider="openai", active_model="gpt-4o", request_timeout_seconds=60)
    cfg.providers = {"openai": ProviderConfig(api_key="sk-x")}

    loader = MagicMock()
    loader.get_quick_action.return_value = MagicMock(
        system_prompt_id="sts_helper",
        user_template="Help with {custom_text}",
        requires_screenshot=False,
        required_capabilities=frozenset(),
    )
    loader.get_system_prompt.return_value = MagicMock(content="SYS BASE")

    fake_provider = MagicMock()
    fake_provider.name = "openai"
    fake_provider.list_models.return_value = [
        ModelInfo("gpt-4o", "GPT-4o", frozenset({Capability.VISION, Capability.JSON_MODE}), context_window=128_000)
    ]
    factory = MagicMock(return_value=fake_provider)

    capture = MagicMock()
    capture.grab_primary.return_value = b"\x89PNG\r\n\x1a\n"  # fake

    return InferenceRunner(
        config=cfg,
        prompt_loader=loader,
        provider_factory=factory,
        screen_capture=capture,
        run_state_store=None,
    )


def test_snapshot_quick_action_basic(runner):
    req = QuickActionRequest(prompt_id="explain", custom_text="this", include_screenshot=False)
    snap = runner.snapshot_quick_action(req)
    assert isinstance(snap, RequestSnapshot)
    assert snap.provider == "openai"
    assert snap.model == "gpt-4o"
    assert snap.system == "SYS BASE"
    assert len(snap.messages) == 1
    assert snap.messages[0].role == "user"
    assert "Help with this" == snap.messages[0].text


def test_snapshot_follow_up_appends_user_message(runner):
    hist = (
        Message(role="user", text="first", image_png=None),
        Message(role="assistant", text="reply", image_png=None),
    )
    req = FollowUpRequest(user_text="why?", include_screenshot=False, recapture=False)
    snap = runner.snapshot_follow_up(req, hist)
    assert len(snap.messages) == 3
    assert snap.messages[-1].role == "user"
    assert snap.messages[-1].text == "why?"


def test_snapshot_inspect_json_mode_true(runner):
    snap = runner.snapshot_inspect([b"\x89PNG\r\n\x1a\n"])
    assert snap.params["json_mode"] is True
    assert len(snap.messages) == 1
    assert snap.messages[0].image_png is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_runner_snapshot.py -v`
Expected: FAIL — `cannot import name 'RequestSnapshot'`.

- [ ] **Step 3: Implement `RequestSnapshot` and the three `snapshot_*` methods**

In `src/spiresight/core/runner.py`:

a. Add the dataclass near the top, after the `_INSPECT_CAPS` constant:

```python
@dataclass(frozen=True)
class RequestSnapshot:
    provider: str
    model: str
    system: str
    messages: tuple[Message, ...]
    params: dict[str, object]
```

Import: `from dataclasses import dataclass` (already imported indirectly? confirm and add if missing).

b. Add three new methods on `InferenceRunner`:

```python
    def snapshot_quick_action(self, request: QuickActionRequest) -> RequestSnapshot:
        qa = self._loader.get_quick_action(request.prompt_id)
        sp = self._loader.get_system_prompt(qa.system_prompt_id)
        user_text = qa.user_template.format(custom_text=request.custom_text or "")
        image_png: bytes | None = None
        if qa.requires_screenshot and request.include_screenshot:
            image_png = self._capture.grab_primary()
        provider, model = self._get_provider_and_model()
        return RequestSnapshot(
            provider=provider.name,
            model=model.id,
            system=self._compose_system(sp.content),
            messages=(Message(role="user", text=user_text, image_png=image_png),),
            params={"json_mode": False, "has_images": image_png is not None},
        )

    def snapshot_follow_up(
        self,
        request: FollowUpRequest,
        history: tuple[Message, ...],
    ) -> RequestSnapshot:
        guard = _load_guard_prompt()
        image_png: bytes | None = None
        if request.recapture:
            image_png = self._capture.grab_primary()
        elif request.include_screenshot:
            for m in reversed(history):
                if m.role == "user" and m.image_png is not None:
                    image_png = m.image_png
                    break
        user_msg = Message(role="user", text=request.user_text, image_png=image_png)
        provider, model = self._get_provider_and_model()
        return RequestSnapshot(
            provider=provider.name,
            model=model.id,
            system=guard,
            messages=tuple(history) + (user_msg,),
            params={"json_mode": False, "has_images": image_png is not None},
        )

    def snapshot_inspect(self, images: list[bytes]) -> RequestSnapshot:
        if not images:
            raise ValueError("inspect requires at least one frame")
        sp = self._loader.get_system_prompt(INSPECTOR_PROMPT_ID)
        provider, model = self._get_provider_and_model()
        msgs = tuple(
            Message(role="user", text=INSPECTOR_USER_TEXT, image_png=img) for img in images
        )
        return RequestSnapshot(
            provider=provider.name,
            model=model.id,
            system=sp.content,
            messages=msgs,
            params={"json_mode": True, "has_images": True, "image_count": len(images)},
        )
```

c. Refactor `run_quick_action`, `run_follow_up`, `inspect` to call the snapshot first. New `run_quick_action`:

```python
    def run_quick_action(
        self, request: QuickActionRequest, *, cancel_event: threading.Event,
    ) -> Iterator[StreamChunk]:
        snap = self.snapshot_quick_action(request)
        provider, model = self._get_provider_and_model()
        qa = self._loader.get_quick_action(request.prompt_id)
        missing = set(qa.required_capabilities) - set(model.capabilities)
        if missing:
            raise MissingCapabilityError(model=model.id, missing=missing)
        msg = snap.messages[0]
        yield from provider.stream(
            model=snap.model,
            system=snap.system,
            user_text=msg.text,
            images=[msg.image_png] if msg.image_png is not None else [],
            cancel_event=cancel_event,
            json_mode=snap.params.get("json_mode", False),
        )
```

New `run_follow_up`:

```python
    def run_follow_up(
        self, request: FollowUpRequest, history: tuple[Message, ...],
        *, cancel_event: threading.Event,
    ) -> Iterator[StreamChunk]:
        snap = self.snapshot_follow_up(request, history)
        provider, _ = self._get_provider_and_model()
        yield from provider.stream(
            model=snap.model,
            system=snap.system,
            messages=list(snap.messages),
            cancel_event=cancel_event,
        )
```

New `inspect` body (preserve parsing):

```python
    def inspect(self, *, images: list[bytes], cancel_event: threading.Event) -> RunState:
        snap = self.snapshot_inspect(images)
        provider, model = self._get_provider_and_model()
        missing = _INSPECT_CAPS - set(model.capabilities)
        if missing:
            raise MissingCapabilityError(model=model.id, missing=set(missing))
        buffer: list[str] = []
        for chunk in provider.stream(
            model=snap.model,
            system=snap.system,
            user_text=INSPECTOR_USER_TEXT,
            images=[m.image_png for m in snap.messages if m.image_png is not None],
            cancel_event=cancel_event,
            json_mode=True,
        ):
            if chunk.text_delta:
                buffer.append(chunk.text_delta)
            if chunk.finish_reason is not None:
                break
        raw = "".join(buffer).strip()
        try:
            return RunState.model_validate_json(raw)
        except Exception as exc:
            raise ValueError(f"Inspector returned unparseable JSON: {raw[:200]}") from exc
```

- [ ] **Step 4: Run the snapshot tests**

Run: `pytest tests/test_runner_snapshot.py -v`
Expected: 3 passed.

- [ ] **Step 5: Re-run the existing runner tests**

Run: `pytest tests/test_inference_runner.py -v`
Expected: still all passing (the run_* refactor preserves observable behavior).

- [ ] **Step 6: Commit**

```bash
git add src/spiresight/core/runner.py tests/test_runner_snapshot.py
git commit -m "refactor(runner): add RequestSnapshot + snapshot_* methods, run_* use them"
```

---

### Task 7: `InferenceWorker` — snapshot capture, signals, finally block

**Files:**
- Modify: `src/spiresight/ui/workers/inference_worker.py`
- Test: `tests/test_inference_worker_logging.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_inference_worker_logging.py`:

```python
from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from spiresight.core.messages import Message
from spiresight.core.runner import RequestSnapshot
from spiresight.core.usage import RequestLog
from spiresight.llm.errors import RequestTimeoutError
from spiresight.llm.provider import StreamChunk
from spiresight.ui.workers.inference_worker import InferenceWorker


def _make_worker(run_fn, *, snap=None):
    runner = MagicMock()
    snap = snap or RequestSnapshot(
        provider="openai", model="gpt-4o",
        system="SYS", messages=(Message(role="user", text="hi", image_png=None),),
        params={"json_mode": False, "has_images": False},
    )
    w = InferenceWorker(
        runner=runner, run_fn=run_fn,
        model_id="gpt-4o", input_preview="hi",
        snapshot=snap, correlation_id="aaaaaaaa",
    )
    return w


def test_request_logged_fires_before_stream_consumed(qtbot):
    def run_fn(cancel: threading.Event) -> Iterator[StreamChunk]:
        yield StreamChunk(text_delta="abc")

    w = _make_worker(run_fn)
    with qtbot.waitSignal(w.request_logged, timeout=2000) as blocker:
        w.run()
    rec = blocker.args[0]
    assert isinstance(rec, RequestLog)
    assert rec.correlation_id == "aaaaaaaa"
    assert rec.status == "sent"
    assert rec.system == "SYS"


def test_response_logged_on_success(qtbot):
    def run_fn(cancel):
        yield StreamChunk(text_delta="hello ")
        yield StreamChunk(text_delta="world", finish_reason="stop")
    w = _make_worker(run_fn)
    with qtbot.waitSignal(w.response_logged, timeout=2000) as blocker:
        w.run()
    cid, status, text, err = blocker.args
    assert cid == "aaaaaaaa"
    assert status == "ok"
    assert text == "hello world"
    assert err is None


def test_response_logged_on_timeout(qtbot):
    def run_fn(cancel):
        yield StreamChunk(text_delta="partial")
        raise RequestTimeoutError("Request exceeded 5s timeout")
    w = _make_worker(run_fn)
    with qtbot.waitSignal(w.response_logged, timeout=2000) as blocker:
        w.run()
    cid, status, text, err = blocker.args
    assert status == "timeout"
    assert text == "partial"
    assert "5s timeout" in err


def test_response_logged_on_cancel(qtbot):
    def run_fn(cancel):
        yield StreamChunk(text_delta="abc")
        cancel.set()
        yield StreamChunk(text_delta="never")
    w = _make_worker(run_fn)
    with qtbot.waitSignal(w.response_logged, timeout=2000) as blocker:
        w.run()
    cid, status, text, err = blocker.args
    assert status == "cancelled"
    assert text == "abc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_inference_worker_logging.py -v`
Expected: FAIL on imports / signal-not-exist / constructor signature mismatch.

- [ ] **Step 3: Rewrite `InferenceWorker`**

Edit `src/spiresight/ui/workers/inference_worker.py`. Replace the entire file:

```python
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
    run_started = Signal(str, str)         # model_id, input_preview
    usage_recorded = Signal(object)        # CallRecord
    cancelled = Signal()
    request_logged = Signal(object)        # RequestLog (status="sent")
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
        model_id: str,
        input_preview: str,
        parent=None,
    ) -> "InferenceWorker":
        snap = runner.snapshot_quick_action(request)
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
        self.run_started.emit(self._model_id, self._input_preview)
        self.request_logged.emit(self._build_request_log())

        captured_usage: TokenUsage | None = None
        text_buffer: list[str] = []
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
        except Exception as exc:  # noqa: BLE001
            status, error_msg = "error", f"{type(exc).__name__}: {exc}"
            exc_to_emit = exc
        finally:
            full_text = "".join(text_buffer)
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
```

- [ ] **Step 4: Run worker logging tests**

Run: `pytest tests/test_inference_worker_logging.py -v`
Expected: 4 passed.

- [ ] **Step 5: Re-run existing worker tests**

Run: `pytest tests/test_inference_worker_usage_flow.py -v`
Expected: still passing. If any test constructs `InferenceWorker` directly with the old signature, update those tests to use the factory classmethods (the test only needs the externally-observable signals).

- [ ] **Step 6: Commit**

```bash
git add src/spiresight/ui/workers/inference_worker.py tests/test_inference_worker_logging.py
git commit -m "feat(workers): InferenceWorker emits request_logged + response_logged"
```

---

### Task 8: `InspectWorker` — same logging signals

**Files:**
- Modify: `src/spiresight/ui/workers/inspect_worker.py`
- Modify: `tests/test_inference_worker_logging.py` (add InspectWorker variant) — or new `tests/test_inspect_worker_logging.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_inspect_worker_logging.py`:

```python
from unittest.mock import MagicMock

from spiresight.core.runner import RequestSnapshot
from spiresight.core.messages import Message
from spiresight.core.usage import RequestLog
from spiresight.ui.workers.inspect_worker import InspectWorker


def test_inspect_worker_emits_request_logged(qtbot, monkeypatch):
    runner = MagicMock()
    runner.snapshot_inspect.return_value = RequestSnapshot(
        provider="openai", model="gpt-4o",
        system="INSPECT-SYS",
        messages=(Message(role="user", text="Extract.", image_png=b"\x89PNG"),),
        params={"json_mode": True, "has_images": True, "image_count": 1},
    )
    runner.inspect.return_value = MagicMock()

    w = InspectWorker(runner=runner, frames=[b"\x89PNG"])
    with qtbot.waitSignal(w.request_logged, timeout=2000) as blocker:
        w.run()
    rec: RequestLog = blocker.args[0]
    assert rec.system == "INSPECT-SYS"
    assert rec.params["json_mode"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_inspect_worker_logging.py -v`
Expected: FAIL — `request_logged` does not exist on `InspectWorker`.

- [ ] **Step 3: Rewrite `InspectWorker`**

Edit `src/spiresight/ui/workers/inspect_worker.py`. Replace with:

```python
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from uuid import uuid4

from PySide6.QtCore import QThread, Signal

from spiresight.core.run_state import RunState
from spiresight.core.runner import InferenceRunner
from spiresight.core.usage import LogStatus, RequestLog
from spiresight.ui.workers.inference_worker import _snapshot_to_logged_messages
from spiresight.llm.errors import RequestTimeoutError

_log = logging.getLogger(__name__)


class InspectWorker(QThread):
    ready = Signal(object)              # RunState
    failed = Signal(object)             # Exception
    request_logged = Signal(object)     # RequestLog
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
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_inspect_worker_logging.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/workers/inspect_worker.py tests/test_inspect_worker_logging.py
git commit -m "feat(workers): InspectWorker emits request_logged + response_logged"
```

---

### Task 9: `LogRow` + `TextRow` widgets

**Files:**
- Create: `src/spiresight/ui/widgets/log_row.py`
- Test: `tests/test_log_row.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_log_row.py`:

```python
from datetime import datetime, timezone

import pytest

from spiresight.core.usage import LoggedMessage, RequestLog
from spiresight.ui.widgets.log_row import LogRow, TextRow


@pytest.fixture
def sample_record():
    return RequestLog(
        correlation_id="a3f2c1de",
        timestamp=datetime.now(tz=timezone.utc),
        provider="openai",
        model="gpt-4o",
        system="You are SpireSight.",
        messages=[
            LoggedMessage(role="user", text="What card?", image_summary="PNG, 245 KB, 1920×1080"),
        ],
        params={"json_mode": False, "has_images": True},
    )


def test_log_row_initial_collapsed(qtbot, sample_record):
    row = LogRow(sample_record)
    qtbot.addWidget(row)
    assert row.correlation_id == "a3f2c1de"
    assert row._body.isVisible() is False


def test_log_row_toggle_shows_body(qtbot, sample_record):
    row = LogRow(sample_record)
    qtbot.addWidget(row)
    row.show()
    row.toggle()
    assert row._body.isVisible() is True
    row.toggle()
    assert row._body.isVisible() is False


def test_log_row_set_response_ok(qtbot, sample_record):
    row = LogRow(sample_record)
    qtbot.addWidget(row)
    row.set_response("the answer", "ok", None)
    assert "ok" in row._summary.text()
    assert "the answer" in row._response.toPlainText()


def test_log_row_set_response_error_appends_error(qtbot, sample_record):
    row = LogRow(sample_record)
    qtbot.addWidget(row)
    row.set_response("partial", "error", "NetworkError: down")
    txt = row._response.toPlainText()
    assert "partial" in txt
    assert "[error] NetworkError: down" in txt


def test_log_row_to_plain_text_contains_all_sections(qtbot, sample_record):
    row = LogRow(sample_record)
    qtbot.addWidget(row)
    row.set_response("the answer", "ok", None)
    txt = row.to_plain_text()
    assert "System prompt" in txt
    assert "You are SpireSight." in txt
    assert "Messages" in txt
    assert "What card?" in txt
    assert "PNG, 245 KB, 1920×1080" in txt
    assert "Params" in txt
    assert "json_mode: False" in txt
    assert "Response" in txt
    assert "the answer" in txt


def test_text_row_no_body(qtbot):
    tr = TextRow("[12:03:40] saved settings")
    qtbot.addWidget(tr)
    assert tr.to_plain_text() == "[12:03:40] saved settings"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_log_row.py -v`
Expected: FAIL — `cannot import name 'LogRow'`.

- [ ] **Step 3: Implement the widgets**

Create `src/spiresight/ui/widgets/log_row.py`:

```python
"""Collapsible log row widgets for the Logs tab.

LogRow renders a single inference request with header (always visible) and
body (system / messages / params / response) hidden by default. TextRow is
the non-collapsible sibling used for plain log lines and cost rows.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from spiresight.core.usage import LogStatus, RequestLog


_MONOSPACE_QSS = "font-family: ui-monospace, Menlo, monospace; font-size: 11px;"
_TRUNCATE_LIMIT = 2000


def _make_section(title: str) -> tuple[QLabel, QPlainTextEdit]:
    label = QLabel(title)
    label.setStyleSheet("font-weight: 600; padding-top: 4px;")
    edit = QPlainTextEdit()
    edit.setReadOnly(True)
    edit.setStyleSheet(_MONOSPACE_QSS)
    edit.setMaximumBlockCount(_TRUNCATE_LIMIT)
    return label, edit


def _format_header(record: RequestLog) -> str:
    ts = record.timestamp.astimezone().strftime("%H:%M:%S")
    return f"[{ts}] [{record.status}] {record.provider}/{record.model} · {record.correlation_id}"


class LogRow(QFrame):
    def __init__(self, record: RequestLog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LogRow")
        self.setProperty("status", record.status)
        self._record = record

        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(2)

        self._header = QWidget()
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(2, 2, 2, 2)
        self._chevron = QLabel("▶")
        self._summary = QLabel(_format_header(record))
        self._summary.setObjectName("LogRowSummary")
        self._summary.setStyleSheet(_MONOSPACE_QSS)
        header_layout.addWidget(self._chevron)
        header_layout.addWidget(self._summary, stretch=1)
        self._copy_btn = QToolButton()
        self._copy_btn.setText("Copy")
        self._copy_btn.clicked.connect(self._on_copy)
        header_layout.addWidget(self._copy_btn)
        outer.addWidget(self._header)

        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(20, 2, 2, 6)
        body_layout.setSpacing(2)

        self._sys_label, self._sys_edit = _make_section("System prompt")
        self._sys_edit.setPlainText(record.system)
        body_layout.addWidget(self._sys_label)
        body_layout.addWidget(self._sys_edit)

        self._msgs_label = QLabel(f"Messages ({len(record.messages)})")
        self._msgs_label.setStyleSheet("font-weight: 600; padding-top: 4px;")
        body_layout.addWidget(self._msgs_label)
        msg_text_parts: list[str] = []
        for m in record.messages:
            msg_text_parts.append(f"[{m.role}] {m.text}")
            if m.image_summary:
                msg_text_parts.append(f"  [image: {m.image_summary}]")
        self._msgs_edit = QPlainTextEdit("\n".join(msg_text_parts))
        self._msgs_edit.setReadOnly(True)
        self._msgs_edit.setStyleSheet(_MONOSPACE_QSS)
        self._msgs_edit.setMaximumBlockCount(_TRUNCATE_LIMIT)
        body_layout.addWidget(self._msgs_edit)

        self._params_label, self._params_edit = _make_section("Params")
        self._params_edit.setPlainText(
            "\n".join(f"{k}: {v!r}" for k, v in record.params.items())
        )
        body_layout.addWidget(self._params_label)
        body_layout.addWidget(self._params_edit)

        self._resp_label, self._response = _make_section("Response")
        self._response.setPlainText("[streaming…]")
        body_layout.addWidget(self._resp_label)
        body_layout.addWidget(self._response)

        outer.addWidget(self._body)
        self._body.setVisible(False)

        self._header.mousePressEvent = self._on_header_click  # type: ignore[method-assign]

    @property
    def correlation_id(self) -> str:
        return self._record.correlation_id

    def toggle(self) -> None:
        self._body.setVisible(not self._body.isVisible())
        self._chevron.setText("▼" if self._body.isVisible() else "▶")

    def _on_header_click(self, event: QMouseEvent) -> None:
        self.toggle()

    def set_response(self, text: str, status: LogStatus, error: str | None) -> None:
        self._record.status = status
        self._record.response = text
        self._record.error = error
        self.setProperty("status", status)
        # force QSS re-evaluation after dynamic property change
        self.style().unpolish(self)
        self.style().polish(self)
        self._summary.setText(_format_header(self._record))

        if status == "ok":
            body = text
        elif status == "cancelled":
            body = text if text else "(no output)"
        else:  # error, timeout
            parts = [text] if text else []
            if error:
                parts.append(f"[error] {error}")
            body = "\n".join(parts) if parts else "(no output)"
        self._response.setPlainText(body)

    def to_plain_text(self) -> str:
        lines: list[str] = [self._summary.text(), ""]
        lines.append("System prompt")
        lines.append(self._sys_edit.toPlainText())
        lines.append("")
        lines.append(self._msgs_label.text())
        lines.append(self._msgs_edit.toPlainText())
        lines.append("")
        lines.append("Params")
        lines.append(self._params_edit.toPlainText())
        lines.append("")
        lines.append("Response")
        lines.append(self._response.toPlainText())
        return "\n".join(lines)

    def _on_copy(self) -> None:
        QGuiApplication.clipboard().setText(self.to_plain_text())


class TextRow(QFrame):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TextRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self._label = QLabel(text)
        self._label.setStyleSheet(_MONOSPACE_QSS)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._label, stretch=1)

    def to_plain_text(self) -> str:
        return self._label.text()
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_log_row.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/widgets/log_row.py tests/test_log_row.py
git commit -m "feat(ui): add LogRow + TextRow widgets for Logs tab"
```

---

### Task 10: `LogsTab` rewrite

**Files:**
- Modify: `src/spiresight/ui/tabs/logs_tab.py`
- Test: `tests/test_logs_tab.py` (existing — may need updates), `tests/test_logs_tab_request.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_logs_tab_request.py`:

```python
from datetime import datetime, timezone

from spiresight.core.usage import LoggedMessage, RequestLog
from spiresight.ui.tabs.logs_tab import LogsTab
from spiresight.prompts.ui_locale import UILocale


def _record(cid: str = "aaaaaaaa") -> RequestLog:
    return RequestLog(
        correlation_id=cid,
        timestamp=datetime.now(tz=timezone.utc),
        provider="openai",
        model="gpt-4o",
        system="SYS",
        messages=[LoggedMessage(role="user", text="hi", image_summary=None)],
        params={"json_mode": False, "has_images": False},
    )


def _make_tab(qtbot, tmp_path) -> LogsTab:
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.yaml").write_text(
        "logs:\n  copy_all: Copy all\n  clear: Clear\n",
        encoding="utf-8",
    )
    locale = UILocale(locales_dir, "en")
    tab = LogsTab(locale)
    qtbot.addWidget(tab)
    return tab


def test_log_request_inserts_row(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    tab.log_request(_record("aaaaaaaa"))
    assert "aaaaaaaa" in tab._rows
    assert tab._row_count() == 1


def test_log_request_then_update_response(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    tab.log_request(_record("aaaaaaaa"))
    tab.update_response("aaaaaaaa", "the answer", "ok", None)
    row = tab._rows["aaaaaaaa"]
    assert "ok" in row._summary.text()
    assert "the answer" in row._response.toPlainText()


def test_update_response_for_missing_id_is_noop(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    # should not raise:
    tab.update_response("zzzzzzzz", "x", "ok", None)


def test_ring_buffer_evicts_oldest(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    for i in range(205):
        tab.log_request(_record(f"id{i:05d}"))
    assert tab._row_count() == 200
    # The oldest 5 should be gone:
    assert "id00000" not in tab._rows
    assert "id00204" in tab._rows
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_logs_tab_request.py -v`
Expected: FAIL — `LogsTab` has no `log_request` / `_rows` / `_row_count`.

- [ ] **Step 3: Rewrite `LogsTab`**

Replace `src/spiresight/ui/tabs/logs_tab.py` with:

```python
"""Lightweight in-memory log viewer.

Owns a vertical stack of LogRow / TextRow widgets (max 200), inserted at
the top. log() emits a TextRow for plain text events, log_cost() emits a
TextRow for cost lines, log_request() emits a LogRow for an in-flight
inference call which is later finalized via update_response().
"""
from __future__ import annotations

import logging
from datetime import datetime
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from spiresight.core.usage import CallRecord, LogStatus, RequestLog
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.widgets.log_row import LogRow, TextRow

_log = logging.getLogger(__name__)
MAX_ROWS = 200


class LogsTab(QWidget):
    def __init__(self, locale: UILocale, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._locale = locale
        self._rows: dict[str, LogRow] = {}

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

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._container = QWidget()
        self._stack = QVBoxLayout(self._container)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setSpacing(2)
        self._stack.addStretch(1)  # trailing stretch keeps rows top-aligned
        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, stretch=1)

        locale.changed.connect(self._retranslate)

    # ---- plain rows (unchanged API) ----

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._insert(TextRow(escape(f"[{ts}] {message}")))

    def log_cost(self, record: CallRecord) -> None:
        ts = record.timestamp.strftime("%H:%M:%S")
        in_tok = str(record.usage.input_tokens) if record.usage_known else "?"
        out_tok = str(record.usage.output_tokens) if record.usage_known else "?"
        cost = f"~${record.cost_usd:.4f}" if record.cost_usd is not None else "~$—"
        text = (
            f"[{ts}] [cost] {record.model} "
            f"↑ {in_tok} ↓ {out_tok} {cost} | "
            f'Q: "{record.input_preview}" | '
            f'A: "{record.output_preview}"'
        )
        self._insert(TextRow(text))

    # ---- request rows (new) ----

    def log_request(self, record: RequestLog) -> None:
        row = LogRow(record)
        self._rows[record.correlation_id] = row
        self._insert(row)

    def update_response(
        self,
        correlation_id: str,
        response: str,
        status: LogStatus,
        error: str | None = None,
    ) -> None:
        row = self._rows.get(correlation_id)
        if row is None:
            _log.debug("update_response for evicted/unknown id %s", correlation_id)
            return
        row.set_response(response, status, error)

    # ---- internals ----

    def _row_count(self) -> int:
        # subtract 1 for the trailing stretch item
        return max(0, self._stack.count() - 1)

    def _insert(self, widget: QFrame) -> None:
        self._stack.insertWidget(0, widget)
        self._enforce_cap()

    def _enforce_cap(self) -> None:
        while self._row_count() > MAX_ROWS:
            # last layout item is the stretch; second-to-last is the oldest row
            item = self._stack.takeAt(self._stack.count() - 2)
            if item is None:
                return
            w = item.widget()
            if isinstance(w, LogRow):
                self._rows.pop(w.correlation_id, None)
            if w is not None:
                w.deleteLater()

    def _on_copy(self) -> None:
        parts: list[str] = []
        for i in range(self._stack.count() - 1):  # skip stretch
            w = self._stack.itemAt(i).widget()
            if hasattr(w, "to_plain_text"):
                parts.append(w.to_plain_text())
        QGuiApplication.clipboard().setText("\n\n---\n\n".join(parts))

    def _on_clear(self) -> None:
        while self._row_count() > 0:
            item = self._stack.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows.clear()

    def _retranslate(self) -> None:
        loc = self._locale
        self._copy_btn.setText(loc.get("logs.copy_all"))
        self._clear_btn.setText(loc.get("logs.clear"))
```

- [ ] **Step 4: Run the new tests**

Run: `pytest tests/test_logs_tab_request.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the existing logs_tab tests**

Run: `pytest tests/test_logs_tab.py -v`
Expected: passes; if any test asserts on `QTextEdit` internals, update it to use `_rows` / `_row_count` instead.

- [ ] **Step 6: Commit**

```bash
git add src/spiresight/ui/tabs/logs_tab.py tests/test_logs_tab_request.py tests/test_logs_tab.py
git commit -m "refactor(ui): rewrite LogsTab around QScrollArea + LogRow list"
```

---

### Task 11: Wire worker signals in `MainWindow`

**Files:**
- Modify: `src/spiresight/ui/windows/main_window.py`

- [ ] **Step 1: Find the worker construction sites**

Run: `grep -n "InferenceWorker\|InspectWorker" src/spiresight/ui/windows/main_window.py`
Note each site where a worker is constructed and signals are connected.

- [ ] **Step 2: Connect the new signals**

After every existing connection block where the worker is set up (look for `worker.run_started.connect(...)` or `worker.usage_recorded.connect(...)`), add:

```python
worker.request_logged.connect(self._logs_tab.log_request)
worker.response_logged.connect(self._logs_tab.update_response)
```

For `InspectWorker`:

```python
self._inspect_worker.request_logged.connect(self._logs_tab.log_request)
self._inspect_worker.response_logged.connect(self._logs_tab.update_response)
```

- [ ] **Step 3: Smoke test by launching the app**

Run (manually, not in CI): `python -m spiresight`
Trigger a Quick Action; confirm a `[sent]` row appears in Logs and updates to `[ok]` after the stream completes.

- [ ] **Step 4: Commit**

```bash
git add src/spiresight/ui/windows/main_window.py
git commit -m "feat(ui): connect worker logging signals to LogsTab"
```

---

### Task 12: Settings dialog — timeout `QSpinBox`

**Files:**
- Modify: `src/spiresight/ui/windows/settings_dialog.py`

- [ ] **Step 1: Add the spinbox to the General tab**

Edit `_build_general_tab` in `src/spiresight/ui/windows/settings_dialog.py`. Add to the imports at top: `QSpinBox`:

```python
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QLineEdit, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)
```

Inside `_build_general_tab`, before `return page`:

```python
        self._timeout = QSpinBox()
        self._timeout.setRange(30, 600)
        self._timeout.setSingleStep(30)
        self._timeout.setValue(self._config.request_timeout_seconds)
        form.addRow("Request timeout (seconds)", self._timeout)
```

- [ ] **Step 2: Persist in `_apply_and_accept`**

Append before `self.accept()`:

```python
        self._config.request_timeout_seconds = self._timeout.value()
```

- [ ] **Step 3: Quick smoke check**

Open the dialog, change value, re-open — value should be preserved (relies on the existing `ConfigStore` save path triggered by the dialog's accept handler in `MainWindow`).

- [ ] **Step 4: Commit**

```bash
git add src/spiresight/ui/windows/settings_dialog.py
git commit -m "feat(settings): expose request_timeout_seconds spinbox"
```

---

### Task 13: i18n strings

**Files:**
- Modify: `src/spiresight/prompts/locales/en.yaml`
- Modify: `src/spiresight/prompts/locales/zh.yaml`

- [ ] **Step 1: Find existing locale layout**

Run: `cat src/spiresight/prompts/locales/en.yaml`
Note the `logs:` section and the indent style.

- [ ] **Step 2: Add keys to `en.yaml`**

Under `logs:` add (and create `settings:` if missing):

```yaml
logs:
  copy_all: "Copy all"
  clear: "Clear"
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

(Preserve all existing keys; only add the new ones.)

- [ ] **Step 3: Mirror to `zh.yaml`**

```yaml
logs:
  copy_all: "复制全部"
  clear: "清空"
  section:
    system: "System prompt"
    messages: "Messages"
    params: "Params"
    response: "Response"
  streaming_placeholder: "[流式中…]"
  copy_row: "复制"
  status:
    sent: "sent"
    ok: "ok"
    error: "error"
    cancelled: "cancelled"
    timeout: "timeout"
settings:
  request_timeout_label: "请求超时（秒）"
```

Section titles and status labels stay ASCII English so monospace headers stay aligned across locales.

- [ ] **Step 4: Use the keys in widgets**

In `src/spiresight/ui/widgets/log_row.py`, replace the hardcoded "System prompt", "Messages", "Params", "Response", "[streaming…]", "Copy" strings with `locale.get(...)` lookups. Since `LogRow.__init__` doesn't currently take a locale, pass one through from `LogsTab._insert`:

In `LogRow.__init__`, accept `locale: UILocale | None = None`. If `None`, use the hardcoded fallbacks (preserves test convenience). Otherwise call `locale.get(...)` for each label.

In `LogsTab.log_request`, pass `locale=self._locale` to `LogRow`.

Update `LogRow` import in `logs_tab.py` accordingly.

- [ ] **Step 5: Use settings key**

In `settings_dialog.py`, replace `"Request timeout (seconds)"` with `self._locale.get("settings.request_timeout_label")` — but settings_dialog currently does not take a `UILocale`. Inspect its constructor; if it doesn't, leave the string as English for now and file a follow-up. (Out of scope for this spec — keep English literal here. Note this in a code comment.)

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_log_row.py tests/test_logs_tab_request.py -v`
Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/spiresight/prompts/locales/ src/spiresight/ui/widgets/log_row.py src/spiresight/ui/tabs/logs_tab.py
git commit -m "feat(i18n): localize Logs section titles + streaming placeholder"
```

---

### Task 14: QSS theming

**Files:**
- Modify: every theme file under `src/spiresight/resources/qss/*.qss`
- Modify: `src/spiresight/ui/theme.py`

- [ ] **Step 1: List theme files**

Run: `ls src/spiresight/resources/qss/`

- [ ] **Step 2: For each `.qss` file, append**

```css
QFrame#LogRow { background: transparent; }
QFrame#LogRow QLabel#LogRowSummary {
    font-family: ui-monospace, Menlo, monospace;
    font-size: 11.5px;
}
QFrame#LogRow[status="sent"]      QLabel#LogRowSummary { color: #888888; }
QFrame#LogRow[status="ok"]        QLabel#LogRowSummary { color: palette(text); }
QFrame#LogRow[status="error"]     QLabel#LogRowSummary { color: #d65a5a; }
QFrame#LogRow[status="timeout"]   QLabel#LogRowSummary { color: #d65a5a; }
QFrame#LogRow[status="cancelled"] QLabel#LogRowSummary { color: #666666; }
QFrame#LogRow QPlainTextEdit {
    font-family: ui-monospace, Menlo, monospace;
    font-size: 11px;
}
```

If a theme uses palette-incompatible colors, substitute the theme's foreground hex for `palette(text)`.

- [ ] **Step 3: Extend `USAGE_COLORS` in `theme.py`**

Open `src/spiresight/ui/theme.py`. Add four keys to `USAGE_COLORS` (or whichever dict already holds usage-color constants):

```python
USAGE_COLORS.update({
    "log_sent": "#888888",
    "log_ok": "",          # use theme fg
    "log_error": "#d65a5a",
    "log_cancelled": "#666666",
})
```

If `USAGE_COLORS` is a top-level literal dict, just add the keys inline instead of `.update`.

- [ ] **Step 4: Visual smoke check**

Run the app manually, switch between themes, trigger a Quick Action and an artificial error (set timeout=30, run a slow inspect). Confirm the row colors match expectations in each theme.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/resources/qss/ src/spiresight/ui/theme.py
git commit -m "style(qss): theme LogRow status badges across all themes"
```

---

### Task 15: Full-suite sweep + manual verification

- [ ] **Step 1: Run the entire suite**

Run: `pytest -q`
Expected: all passing. If `tests/test_inference_worker_usage_flow.py` or any other test calls the old `InferenceWorker(...)` direct constructor with the old signature, update it now to either use the factory classmethods or pass the new required kwargs (`snapshot`, `correlation_id`).

- [ ] **Step 2: Run mypy**

Run: `mypy src/spiresight`
Expected: clean. Fix any `Argument missing for parameter "options"` errors by passing `None` or constructing `ProviderOptions()` at the call site.

- [ ] **Step 3: Run ruff**

Run: `ruff check src/ tests/`
Expected: clean.

- [ ] **Step 4: Manual verification — golden path**

Launch app. Open a Quick Action. Confirm in the Logs tab:
1. A `[sent]` row appears immediately with the correct provider/model/correlation-id header.
2. Expanding the row shows non-empty `System prompt`, `Messages`, `Params`, and `Response: [streaming…]` sections.
3. After streaming completes, the row's status flips to `[ok]` and the Response section contains the model's full text.
4. The cost row (if pricing is configured) appears below the request row.

- [ ] **Step 5: Manual verification — timeout path**

Open Settings, lower `Request timeout (seconds)` to `30`. Trigger an Inspect on a screen the model is slow to parse (or use a deliberately slow prompt). Confirm:
1. The row turns red and reads `[timeout]`.
2. The expanded Response section contains both any partial output and a line `[error] Request exceeded 30s timeout (ReadTimeout)`.

- [ ] **Step 6: Manual verification — cancel path**

Trigger a Quick Action, then click cancel mid-stream. Confirm the row reads `[cancelled]` and the Response section contains the partial text streamed so far, not "(no output)" unless cancellation arrived before the first chunk.

- [ ] **Step 7: Commit any test fixups discovered**

```bash
git add -A
git commit -m "test: update existing tests for InferenceWorker snapshot/correlation_id args"
```

(Skip this commit if no tests needed updating.)

---

## Out-of-scope reminders (do not implement here)

- Per-feature timeout overrides.
- Anthropic / Gemini stream() implementations.
- Thinking-effort parameter exposure.
- Image base64 expansion / thumbnail rendering.
- Settings dialog locale awareness for the new timeout label (left as a follow-up).
- Log persistence across restarts.
- Log search / filter / grouping.

These belong to future specs (model profiles, providers + relays).
