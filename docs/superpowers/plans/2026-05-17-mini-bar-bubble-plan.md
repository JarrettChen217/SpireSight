# InfoBubble + Multi-turn Conversation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a styled floating InfoBubble anchored below the mini-bar for streaming responses + follow-up chat, with a ConversationStore that enables multi-turn context across mode switches.

**Architecture:** Pure-Python data model (Message, ConversationStore, two request types) → split runner methods → extended provider interface → new InfoBubble widget → MainWindow wiring. PinButton extracted as a reusable control. ConversationStore is a singleton assembled in app.py and injected.

**Tech Stack:** PySide6 (Qt), Python dataclasses, httpx (OpenAI SSE), markdown-it-py

**Spec:** `docs/superpowers/specs/2026-05-17-mini-bar-bubble-design.md`

---

### Task 1: `core/messages.py` — Message dataclass

**Files:**
- Create: `src/spiresight/core/messages.py`
- Test: `tests/core/test_messages.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_messages.py
from spiresight.core.messages import Message


def test_message_creation():
    m = Message(role="user", text="hello")
    assert m.role == "user"
    assert m.text == "hello"
    assert m.image_png is None


def test_message_with_image():
    img = b"\x89PNG\r\n\x1a\n"
    m = Message(role="user", text="look", image_png=img)
    assert m.image_png == img
    assert m.role == "user"


def test_message_assistant():
    m = Message(role="assistant", text="ok")
    assert m.role == "assistant"
    assert m.image_png is None


def test_message_immutable():
    m = Message(role="user", text="hi")
    try:
        m.text = "nope"  # type: ignore[misc]
        assert False, "should have raised"
    except Exception:
        pass


def test_message_equality():
    a = Message(role="user", text="hi")
    b = Message(role="user", text="hi")
    assert a == b
    assert hash(a) == hash(b)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_messages.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spiresight.core.messages'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/spiresight/core/messages.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    text: str
    image_png: bytes | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_messages.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/core/test_messages.py src/spiresight/core/messages.py
git commit -m "feat: add Message dataclass for conversation turns"
```

---

### Task 2: `core/conversation.py` — ConversationStore QObject

**Files:**
- Create: `src/spiresight/core/conversation.py`
- Test: `tests/core/test_conversation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_conversation.py
from spiresight.core.conversation import ConversationStore
from spiresight.core.messages import Message


def test_store_starts_empty():
    store = ConversationStore()
    assert store.turns() == ()
    assert store.last_screenshot() is None


def test_append_and_turns():
    store = ConversationStore()
    m1 = Message(role="user", text="hello")
    m2 = Message(role="assistant", text="hi there")
    store.append(m1)
    store.append(m2)
    turns = store.turns()
    assert len(turns) == 2
    assert turns[0] is m1
    assert turns[1] is m2


def test_turns_is_immutable_snapshot():
    store = ConversationStore()
    store.append(Message(role="user", text="a"))
    snapshot = store.turns()
    store.append(Message(role="assistant", text="b"))
    assert len(snapshot) == 1
    assert len(store.turns()) == 2


def test_clear():
    store = ConversationStore()
    store.append(Message(role="user", text="x"))
    store.clear()
    assert store.turns() == ()


def test_last_screenshot_no_images():
    store = ConversationStore()
    store.append(Message(role="user", text="hi"))
    store.append(Message(role="assistant", text="hello"))
    assert store.last_screenshot() is None


def test_last_screenshot_returns_most_recent():
    store = ConversationStore()
    img1 = b"\x89PNG1"
    img2 = b"\x89PNG2"
    store.append(Message(role="user", text="first", image_png=img1))
    store.append(Message(role="assistant", text="ok"))
    store.append(Message(role="user", text="second", image_png=img2))
    assert store.last_screenshot() == img2


def test_last_screenshot_skips_assistant_images():
    store = ConversationStore()
    store.append(Message(role="user", text="q", image_png=b"\x89PNGu"))
    store.append(Message(role="assistant", text="a"))
    assert store.last_screenshot() == b"\x89PNGu"


def test_changed_signal():
    from PySide6.QtCore import Signal
    store = ConversationStore()
    emitted = []
    store.changed.connect(lambda: emitted.append(1))
    store.append(Message(role="user", text="hi"))
    store.clear()
    assert len(emitted) == 2
```

Note: the `changed_signal` test requires a QApplication. Add conftest fixture if not already present.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_conversation.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/spiresight/core/conversation.py
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from spiresight.core.messages import Message


class ConversationStore(QObject):
    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._turns: list[Message] = []

    def turns(self) -> tuple[Message, ...]:
        return tuple(self._turns)

    def append(self, message: Message) -> None:
        self._turns.append(message)
        self.changed.emit()

    def clear(self) -> None:
        self._turns.clear()
        self.changed.emit()

    def last_screenshot(self) -> bytes | None:
        for m in reversed(self._turns):
            if m.role == "user" and m.image_png is not None:
                return m.image_png
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_conversation.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/core/test_conversation.py src/spiresight/core/conversation.py
git commit -m "feat: add ConversationStore for multi-turn tracking"
```

---

### Task 3: `core/request.py` — replace InferenceRequest with two request types

**Files:**
- Modify: `src/spiresight/core/request.py`
- Modify: every import of `InferenceRequest` (runner.py, main_window.py, inference_worker.py)
- Test: `tests/core/test_request.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_request.py
from spiresight.core.request import QuickActionRequest, FollowUpRequest


def test_quick_action_request():
    req = QuickActionRequest(
        prompt_id="combat_advice",
        custom_text="",
        include_screenshot=True,
    )
    assert req.prompt_id == "combat_advice"
    assert req.custom_text == ""
    assert req.include_screenshot is True


def test_quick_action_request_immutable():
    req = QuickActionRequest(prompt_id="x", custom_text="", include_screenshot=False)
    try:
        req.prompt_id = "y"  # type: ignore[misc]
        assert False
    except Exception:
        pass


def test_follow_up_request():
    req = FollowUpRequest(user_text="what about defense?")
    assert req.user_text == "what about defense?"
    assert req.include_screenshot is False
    assert req.recapture is False


def test_follow_up_request_recapture():
    req = FollowUpRequest(user_text="look again", recapture=True)
    assert req.recapture is True
    assert req.include_screenshot is False


def test_follow_up_request_with_screenshot():
    req = FollowUpRequest(user_text="check this", include_screenshot=True, recapture=True)
    assert req.include_screenshot is True
    assert req.recapture is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_request.py -v`
Expected: FAIL — `ImportError` on `QuickActionRequest`

- [ ] **Step 3: Write implementation**

```python
# src/spiresight/core/request.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuickActionRequest:
    prompt_id: str
    custom_text: str
    include_screenshot: bool


@dataclass(frozen=True)
class FollowUpRequest:
    user_text: str
    include_screenshot: bool = False
    recapture: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_request.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/core/test_request.py src/spiresight/core/request.py
git commit -m "feat: replace InferenceRequest with QuickActionRequest + FollowUpRequest"
```

---

### Task 4: `prompts/guard.txt` — Guard system prompt

**Files:**
- Create: `prompts/guard.txt`

- [ ] **Step 1: Write the guard prompt file**

```text
You are continuing a previous conversation. The user is asking a follow-up question without re-attaching the structured run state (cards, relics, potions). Rely on prior assistant messages for game-state context. If the user asks something that requires information you cannot infer from the conversation history, say so explicitly rather than guessing.
```

Use Write tool on `prompts/guard.txt`.

- [ ] **Step 2: Commit**

```bash
git add prompts/guard.txt
git commit -m "feat: add guard system prompt for follow-up requests"
```

---

### Task 5: `llm/provider.py` — extend stream() with `messages` param

**Files:**
- Modify: `src/spiresight/llm/provider.py`

- [ ] **Step 1: Add `messages` parameter to LLMProvider protocol**

Read `src/spiresight/llm/provider.py`, then edit the `stream()` signature to add the optional `messages` param:

In `src/spiresight/llm/provider.py`, change the `stream()` method signature:

```python
# Before (line 26-35):
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

# After:
def stream(
    self,
    *,
    model: str,
    system: str,
    user_text: str = "",
    images: list[bytes] = (),
    messages: list | None = None,   # list[Message], deferred import
    cancel_event: threading.Event = None,  # type: ignore[assignment]
    json_mode: bool = False,
) -> Iterator[StreamChunk]: ...
```

Add `from __future__ import annotations` if not already present (it is). The `list | None` type hint avoids a circular import from `core.messages`.

- [ ] **Step 2: Verify no existing callers break**

Run: `python -c "from spiresight.llm.provider import LLMProvider; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/llm/provider.py
git commit -m "feat: add optional messages param to LLMProvider.stream()"
```

---

### Task 6: OpenAI provider — implement messages path

**Files:**
- Modify: `src/spiresight/llm/providers/openai_provider.py`

- [ ] **Step 1: Update `stream()` to handle messages vs single-turn**

Read the file. Add a conditional in `stream()` around the payload construction (lines 94-101).

Replace:

```python
def stream(
    self,
    *,
    model: str,
    system: str,
    user_text: str,
    images: list[bytes],
    cancel_event: threading.Event,
    json_mode: bool = False,
) -> Iterator[StreamChunk]:
    if not self._config.api_key:
        raise MissingAPIKey(self.name)

    base_url = (self._config.base_url or _DEFAULT_BASE).rstrip("/")
    url = f"{base_url}/chat/completions"
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

With:

```python
def stream(
    self,
    *,
    model: str,
    system: str,
    user_text: str = "",
    images: list[bytes] = (),
    cancel_event: threading.Event = None,  # type: ignore[assignment]
    json_mode: bool = False,
    messages: list | None = None,
) -> Iterator[StreamChunk]:
    if not self._config.api_key:
        raise MissingAPIKey(self.name)
    if cancel_event is None:
        cancel_event = threading.Event()

    base_url = (self._config.base_url or _DEFAULT_BASE).rstrip("/")
    url = f"{base_url}/chat/completions"

    if messages is not None:
        api_messages = self._build_messages(system, messages)
    else:
        api_messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": self._build_user_content(user_text, images)},
        ]

    payload = {
        "model": model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": api_messages,
    }
```

- [ ] **Step 2: Add `_build_messages()` static method**

Add this method to `OpenAIProvider`:

```python
@staticmethod
def _build_messages(system: str, messages: list) -> list[dict]:
    """Build OpenAI-format messages array from conversation history."""
    result: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        if m.image_png is not None and m.role == "user":
            b64 = base64.b64encode(m.image_png).decode()
            result.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": m.text},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            })
        else:
            result.append({"role": m.role, "content": m.text})
    return result
```

- [ ] **Step 3: Smoke-test the import and basic stream path**

Run: `python -c "from spiresight.llm.providers.openai_provider import OpenAIProvider; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/spiresight/llm/providers/openai_provider.py
git commit -m "feat: support multi-turn messages in OpenAI provider stream()"
```

---

### Task 7: Gemini provider — update signature to match protocol

**Files:**
- Modify: `src/spiresight/llm/providers/gemini_provider.py`

- [ ] **Step 1: Update signature to accept messages param**

Replace the `stream()` signature in `GeminiProvider` (lines 20-29) to match the updated protocol:

```python
def stream(
    self,
    *,
    model: str,
    system: str,
    user_text: str = "",
    images: list[bytes] = (),
    cancel_event: threading.Event = None,  # type: ignore[assignment]
    json_mode: bool = False,
    messages: list | None = None,
) -> Iterator[StreamChunk]:
    raise NotImplementedError("Gemini provider is not implemented in MVP")
```

- [ ] **Step 2: Verify import**

Run: `python -c "from spiresight.llm.providers.gemini_provider import GeminiProvider; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/llm/providers/gemini_provider.py
git commit -m "fix: update GeminiProvider.stream() signature for messages param"
```

---

### Task 8: `core/runner.py` — split into `run_quick_action()` + `run_follow_up()`

**Files:**
- Modify: `src/spiresight/core/runner.py`

- [ ] **Step 1: Update imports and add guard prompt loading**

At the top of `runner.py`, replace `InferenceRequest` import:

```python
from spiresight.core.request import QuickActionRequest, FollowUpRequest
from spiresight.core.messages import Message
```

Add a module-level constant for the guard prompt path (loaded lazily):

```python
from pathlib import Path

def _load_guard_prompt() -> str:
    """Locate prompts/guard.txt relative to this file or prompts/ dir."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "prompts" / "guard.txt"
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()
    return (
        "You are continuing a previous conversation. "
        "Rely on prior assistant messages for context. "
        "If you lack needed information, say so explicitly."
    )
```

- [ ] **Step 2: Rename `run()` → `run_quick_action()` and add `_cap_check()` helper**

Replace the existing `run()` method with:

```python
def _get_provider_and_model(self):
    provider_cfg = self._config.providers.get(
        self._config.active_provider, ProviderConfig()
    )
    if not provider_cfg.api_key:
        raise MissingAPIKey(self._config.active_provider)
    provider = self._factory(self._config.active_provider, provider_cfg)
    model = self._resolve_model(provider, self._config.active_model)
    return provider, model


def run_quick_action(
    self,
    request: QuickActionRequest,
    *,
    cancel_event: threading.Event,
) -> Iterator[StreamChunk]:
    qa = self._loader.get_quick_action(request.prompt_id)
    sp = self._loader.get_system_prompt(qa.system_prompt_id)
    user_text = qa.user_template.format(custom_text=request.custom_text or "")

    provider, model = self._get_provider_and_model()
    missing = set(qa.required_capabilities) - set(model.capabilities)
    if missing:
        raise MissingCapabilityError(model=model.id, missing=missing)

    image_png: bytes | None = None
    if qa.requires_screenshot and request.include_screenshot:
        image_png = self._capture.grab_primary()

    yield from provider.stream(
        model=model.id,
        system=self._compose_system(sp.content),
        user_text=user_text,
        images=[image_png] if image_png is not None else [],
        cancel_event=cancel_event,
    )
```

- [ ] **Step 3: Add `run_follow_up()`**

```python
def run_follow_up(
    self,
    request: FollowUpRequest,
    history: tuple[Message, ...],
    *,
    cancel_event: threading.Event,
) -> Iterator[StreamChunk]:
    guard = _load_guard_prompt()

    image_png: bytes | None = None
    if request.recapture:
        image_png = self._capture.grab_primary()
    elif request.include_screenshot:
        # Reuse last screenshot from history
        for m in reversed(history):
            if m.role == "user" and m.image_png is not None:
                image_png = m.image_png
                break

    user_msg = Message(role="user", text=request.user_text, image_png=image_png)
    messages = list(history) + [user_msg]

    provider, model = self._get_provider_and_model()

    yield from provider.stream(
        model=model.id,
        system=guard,
        messages=messages,
        cancel_event=cancel_event,
    )
```

- [ ] **Step 4: Run existing tests to check for regressions**

Run: `pytest tests/ -v --ignore=tests/core/test_messages.py --ignore=tests/core/test_conversation.py --ignore=tests/core/test_request.py -k "not inspect"`
Expected: All existing tests pass (any tests referencing old `InferenceRequest` will fail and we fix in next tasks).

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/core/runner.py
git commit -m "feat: split runner into run_quick_action + run_follow_up"
```

---

### Task 9: `ui/workers/inference_worker.py` — support both request types

**Files:**
- Modify: `src/spiresight/ui/workers/inference_worker.py`

- [ ] **Step 1: Rewrite InferenceWorker with factory methods**

Read the file, then replace it entirely:

```python
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
```

- [ ] **Step 2: Verify import**

Run: `python -c "from spiresight.ui.workers.inference_worker import InferenceWorker; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/ui/workers/inference_worker.py
git commit -m "feat: add for_quick_action / for_follow_up factories to InferenceWorker"
```

---

### Task 10: `ui/widgets/pin_button.py` — reusable PinButton

**Files:**
- Create: `src/spiresight/ui/widgets/pin_button.py`

- [ ] **Step 1: Write PinButton widget**

```python
# src/spiresight/ui/widgets/pin_button.py
from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QToolButton

from spiresight.ui.theme import icon_path


class PinButton(QToolButton):
    toggled = Signal(bool)

    def __init__(self, pinned: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(pinned)
        self.setIconSize(QSize(18, 18))
        self.setObjectName("pin-button")
        self._update_icon()
        self.clicked.connect(lambda: self.toggled.emit(self.isChecked()))
        self.clicked.connect(self._update_icon)

    def _update_icon(self) -> None:
        name = "pin_filled" if self.isChecked() else "pin_outline"
        self.setIcon(QIcon(icon_path(name)))
```

- [ ] **Step 2: Verify import**

Run: `python -c "from spiresight.ui.widgets.pin_button import PinButton; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/ui/widgets/pin_button.py
git commit -m "feat: extract reusable PinButton from mini-bar / main-window pin logic"
```

---

### Task 11: `ui/widgets/mini_bar.py` — add moved signal, use PinButton

**Files:**
- Modify: `src/spiresight/ui/widgets/mini_bar.py`

- [ ] **Step 1: Replace inline pin button with PinButton, add moved signal**

Read the file. Apply the following edits:

a) Add imports at top:
```python
from spiresight.ui.widgets.pin_button import PinButton
```

b) Add `moved` and `pin_toggled` signals to class body (line 18-19):
```python
class MiniBar(QWidget):
    action_clicked = Signal(str)
    expand_requested = Signal()
    moved = Signal(QPoint)          # NEW
    pin_toggled = Signal(bool)      # NEW
```

c) Replace the `_pin_btn` block (lines 42-50) with:
```python
self._pin_btn = PinButton(pinned=pinned)
self._pin_btn.setToolTip("Always on top")
self._pin_btn.toggled.connect(self._on_pin_toggled)
row.addWidget(self._pin_btn)
```

d) In `mouseMoveEvent` (line 82-83), emit moved after moving:
```python
def mouseMoveEvent(self, e: QMouseEvent) -> None:
    if self._drag_offset is not None:
        self.move(e.globalPosition().toPoint() - self._drag_offset)
        self.moved.emit(self.pos())   # NEW
```

e) Remove old `_toggle_pin`, `_update_pin_icon` methods. Replace `is_pinned` property with PinButton state. Add:

```python
@property
def is_pinned(self) -> bool:
    return self._pin_btn.isChecked()

def set_pinned(self, pinned: bool) -> None:
    self._pin_btn.setChecked(pinned)

def _on_pin_toggled(self, pinned: bool) -> None:
    self._pinned = pinned
    geo = self.geometry()
    flags = self.windowFlags()
    if pinned:
        flags |= Qt.WindowType.WindowStaysOnTopHint
    else:
        flags &= ~Qt.WindowType.WindowStaysOnTopHint
    self.setWindowFlags(flags)
    self.setGeometry(geo)
    self.show()
    self.pin_toggled.emit(pinned)
```

f) Update MainWindow reference: `_toggle_mini_bar` calls `self._mini_bar.set_pinned(self._config.always_on_top)` instead of `self._mini_bar._toggle_pin()`.

- [ ] **Step 2: Commit**

```bash
git add src/spiresight/ui/widgets/mini_bar.py src/spiresight/ui/windows/main_window.py
git commit -m "feat: add moved signal to MiniBar, replace inline pin with PinButton"
```

---

### Task 12: `ui/widgets/info_bubble.py` — InfoBubble widget

**Files:**
- Create: `src/spiresight/ui/widgets/info_bubble.py`

- [ ] **Step 1: Write InfoBubble widget**

```python
# src/spiresight/ui/widgets/info_bubble.py
"""Floating bubble anchored below the mini-bar.

Shows streaming markdown responses with a chat input for follow-up
questions. Frameless tool window, styled via dark_fantasy.qss.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QBrush, QColor, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)

from spiresight.core.usage import TokenUsage
from spiresight.ui.widgets.output_view import OutputView

BUBBLE_WIDTH = 360
BUBBLE_MAX_HEIGHT = 200
TAIL_SIZE = 10


class _TailWidget(QWidget):
    """Small triangle pointer drawn at the top of the bubble."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(TAIL_SIZE, TAIL_SIZE)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.moveTo(0, TAIL_SIZE)
        path.lineTo(TAIL_SIZE // 2, 0)
        path.lineTo(TAIL_SIZE, TAIL_SIZE)
        path.closeSubpath()
        p.setBrush(QBrush(QColor("#0d1018")))
        p.setPen(QPen(QColor("#1d2233"), 1))
        p.drawPath(path)


class InfoBubble(QWidget):
    closed = Signal()
    cancel_requested = Signal()
    follow_up_requested = Signal(str, bool)   # (text, recapture)

    def __init__(self, parent=None) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setObjectName("info-bubble")
        self._cursor_timer = QTimer(self)
        self._cursor_visible = True

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── title bar ──
        title = QWidget()
        title.setObjectName("bubble-title-bar")
        title_row = QHBoxLayout(title)
        title_row.setContentsMargins(12, 8, 8, 8)

        self._chip = QLabel()
        self._chip.setObjectName("bubble-chip")
        self._model_label = QLabel()
        self._model_label.setObjectName("bubble-model")

        close_btn = QPushButton("×")
        close_btn.setObjectName("bubble-close")
        close_btn.setFixedSize(24, 24)
        close_btn.clicked.connect(self.closed.emit)
        close_btn.clicked.connect(self.hide)

        title_row.addWidget(self._chip)
        title_row.addWidget(self._model_label)
        title_row.addStretch(1)
        title_row.addWidget(close_btn)
        root.addWidget(title)

        # ── scrollable body ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setMaximumHeight(BUBBLE_MAX_HEIGHT)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(14, 12, 14, 12)
        self._body_layout.setSpacing(8)

        self._output = OutputView()
        self._body_layout.addWidget(self._output, stretch=1)

        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll, stretch=1)

        # ── controls row ──
        controls = QWidget()
        controls.setObjectName("bubble-controls")
        ctrl_row = QHBoxLayout(controls)
        ctrl_row.setContentsMargins(12, 6, 12, 6)

        self._cost_label = QLabel("")
        self._cost_label.setTextFormat(Qt.TextFormat.RichText)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("bubble-cancel")
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)
        self._cancel_btn.hide()

        ctrl_row.addWidget(self._cost_label)
        ctrl_row.addStretch(1)
        ctrl_row.addWidget(self._cancel_btn)
        root.addWidget(controls)

        # ── input row ──
        input_row = QWidget()
        input_row.setObjectName("bubble-input-row")
        ir = QHBoxLayout(input_row)
        ir.setContentsMargins(10, 8, 10, 8)
        ir.setSpacing(6)

        self._cam_btn = QToolButton()
        self._cam_btn.setText("\U0001f4f7")
        self._cam_btn.setObjectName("bubble-camera")
        self._cam_btn.setCheckable(True)
        self._cam_btn.setToolTip("Capture new screenshot for this follow-up")
        self._cam_btn.setFixedSize(28, 28)

        self._input = QLineEdit()
        self._input.setObjectName("bubble-input")
        self._input.setPlaceholderText("追问…")
        self._input.returnPressed.connect(self._on_send)

        send_btn = QPushButton("↵")
        send_btn.setObjectName("bubble-send")
        send_btn.setFixedSize(32, 28)
        send_btn.clicked.connect(self._on_send)

        ir.addWidget(self._cam_btn)
        ir.addWidget(self._input, stretch=1)
        ir.addWidget(send_btn)
        root.addWidget(input_row)

        self.resize(BUBBLE_WIDTH, 100)
        self._cursor_timer.timeout.connect(self._toggle_cursor)
        self._streaming = False

    # ── public API ──

    def reset(self) -> None:
        self._output.reset()
        self._cost_label.clear()
        self._cancel_btn.hide()
        self._cursor_timer.stop()
        self._streaming = False
        # Remove user message widgets from body (but keep OutputView)
        for i in reversed(range(self._body_layout.count())):
            w = self._body_layout.itemAt(i).widget()
            if w is not self._output:
                w.deleteLater()

    def append_user_message(self, text: str) -> None:
        label = QLabel(text)
        label.setObjectName("bubble-user-msg")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        # Insert before OutputView
        idx = self._body_layout.indexOf(self._output)
        self._body_layout.insertWidget(idx, label)

    def append_delta(self, text: str) -> None:
        self._output.append_delta(text)

    def finalize(self) -> None:
        self._output.finalize()
        self.set_streaming(False)

    def set_streaming(self, active: bool) -> None:
        self._streaming = active
        if active:
            self._cancel_btn.show()
            self._cursor_timer.start(500)
        else:
            self._cancel_btn.hide()
            self._cursor_timer.stop()
            self._remove_cursor()

    def set_cost(self, cost_usd: float | None, usage: TokenUsage | None) -> None:
        parts: list[str] = []
        if cost_usd is not None:
            parts.append(
                f'<span style="color:#4ade80;">●</span>'
                f' <span style="color:#6e7a89;">${cost_usd:.4f}</span>'
            )
        if usage is not None:
            parts.append(
                f'<span style="color:#6e7a89;">{usage.input_tokens} in'
                f' / {usage.output_tokens} out</span>'
            )
        if parts:
            self._cost_label.setText(" · ".join(parts))

    def set_title(self, action_label: str, model_id: str) -> None:
        self._chip.setText(action_label)
        self._model_label.setText(model_id)

    def move_anchored(self, anchor_pos: QPoint) -> None:
        """Position bubble so tail aligns to anchor_pos (mini-bar center-bottom)."""
        x = anchor_pos.x() - BUBBLE_WIDTH // 2 + TAIL_SIZE + 2
        y = anchor_pos.y() + TAIL_SIZE
        self.move(x, y)

    # ── internals ──

    def _on_send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        recapture = self._cam_btn.isChecked()
        self._input.clear()
        self._cam_btn.setChecked(False)
        self.append_user_message(text)
        self.follow_up_requested.emit(text, recapture)

    def _toggle_cursor(self) -> None:
        if not self._streaming:
            return
        self._cursor_visible = not self._cursor_visible
        # Append invisible marker that OutputView re-renders to toggle
        # We append a zero-width space so the render pipeline flushes
        if self._cursor_visible:
            self._output.append_delta("​")
        else:
            self._output.append_delta("")

    def _remove_cursor(self) -> None:
        self._cursor_visible = False
```

Note: The cursor toggle approach above is a placeholder. In practice, implement cursor blink by adding/removing a `<span class="stream-cursor">|</span>` to the markdown buffer in finalize/append_delta of OutputView, or use a separate QLabel overlay. The simplest correct approach: after `finalize()`, do nothing (cursor naturally stops because append_delta stops). While streaming, the OutputView's last character auto-scrolls — we can rely on that without a separate cursor animation. For this MVP, skip the blinking cursor and just let the streaming text naturally indicate "in progress." Add the cursor animation as a follow-up.

**Simplified approach (no cursor timer):**
Remove `_cursor_timer`, `_toggle_cursor`, `_remove_cursor`, `_cursor_visible`. In `set_streaming`, only show/hide cancel button. The streaming text itself is enough visual feedback.

- [ ] **Step 2: Commit**

```bash
git add src/spiresight/ui/widgets/info_bubble.py
git commit -m "feat: add InfoBubble widget for mini-bar response display"
```

---

### Task 13: ChatTab multi-turn rendering (must run before Task 14)

**Files:**
- Modify: `src/spiresight/ui/tabs/chat_tab.py`
- Modify: `src/spiresight/ui/widgets/output_view.py`

- [ ] **Step 1: Add `append_user_message` to ChatTab and OutputView**

In `chat_tab.py`, add:

```python
def append_user_message(self, text: str) -> None:
    self.output.append_user_message(text)
```

In `output_view.py`, add to `OutputView`:

```python
def append_user_message(self, text: str) -> None:
    self._flush()
    current = self.toHtml()
    user_html = (
        f'<div style="background-color:#10141e; border-left:2px solid #d4a54a; '
        f'border-radius:0 4px 4px 0; padding:6px 10px; margin-bottom:8px; '
        f'color:#6e7a89;">{text}</div>'
    )
    self.setHtml(current + user_html)
    sb = self.verticalScrollBar()
    sb.setValue(sb.maximum())
```

- [ ] **Step 2: Commit**

```bash
git add src/spiresight/ui/tabs/chat_tab.py src/spiresight/ui/widgets/output_view.py
git commit -m "feat: add user-message styling to ChatTab and OutputView"
```

---

### Task 14: MainWindow wiring — full integration

**Files:**
- Modify: `src/spiresight/ui/windows/main_window.py`

This is the largest task. Apply changes in order.

- [ ] **Step 1: Add imports**

Add after line 20-54 imports:

```python
from spiresight.core.conversation import ConversationStore
from spiresight.core.messages import Message
from spiresight.core.request import QuickActionRequest, FollowUpRequest
from spiresight.ui.widgets.info_bubble import InfoBubble
from spiresight.ui.widgets.pin_button import PinButton
```

- [ ] **Step 2: Update constructor — add ConversationStore, replace pin btn, init bubble**

In `__init__`, after `self._mini_bar: MiniBar | None = None` (line 74):

```python
self._bubble: InfoBubble | None = None
self._conversation: ConversationStore = conversation_store  # injected
```

Change the pin button block (lines 119-127) to use PinButton:

```python
self._pin_btn = PinButton(pinned=config.always_on_top)
self._pin_btn.setToolTip("Always on top")
self._pin_btn.setFixedSize(28, 28)
self._pin_btn.toggled.connect(self._on_pin_toggled)
```

Replace `_toggle_pin` and `_update_pin_icon` methods:

```python
def _on_pin_toggled(self, pinned: bool) -> None:
    self._config.always_on_top = pinned
    self._store.save(self._config)
    self._apply_always_on_top()
```

- [ ] **Step 3: Update `_toggle_mini_bar` — wire bubble signals**

Replace the existing `_toggle_mini_bar` (lines 260-270):

```python
def _toggle_mini_bar(self) -> None:
    if self._mini_bar is None:
        self._mini_bar = MiniBar(self._loader, hotkey_hint=self._config.hotkey,
                                  pinned=self._config.always_on_top)
        self._mini_bar.action_clicked.connect(self._on_action)
        self._mini_bar.expand_requested.connect(self._exit_mini_bar)
        self._mini_bar.pin_toggled.connect(self._on_pin_toggled)
        self._mini_bar.moved.connect(self._on_mini_bar_moved)
        self._bubble = InfoBubble()
        self._bubble.closed.connect(self._on_bubble_closed)
        self._bubble.cancel_requested.connect(self._on_cancel)
        self._bubble.follow_up_requested.connect(self._dispatch_follow_up)
    elif self._mini_bar.is_pinned != self._config.always_on_top:
        self._mini_bar.set_pinned(self._config.always_on_top)
    self.hide()
    self._mini_bar.show()

    if self._bubble is not None:
        turns = self._conversation.turns()
        if turns:
            self._bubble.show()
            mb_geo = self._mini_bar.geometry()
            anchor = QPoint(mb_geo.x() + mb_geo.width() // 2, mb_geo.y() + mb_geo.height())
            self._bubble.move_anchored(anchor)

    self._config.mini_bar_mode = True
    self._store.save(self._config)
```

- [ ] **Step 4: Update `_exit_mini_bar` — close bubble, retain conversation**

Replace existing `_exit_mini_bar` (lines 273-283):

```python
def _exit_mini_bar(self) -> None:
    if self._mini_bar is not None:
        self._config.always_on_top = self._mini_bar.is_pinned
        self._store.save(self._config)
        self._apply_always_on_top()
        self._pin_btn.setChecked(self._config.always_on_top)
        self._mini_bar.hide()
    if self._bubble is not None:
        self._bubble.hide()
    self.show()
    self._config.mini_bar_mode = False
    self._store.save(self._config)
    # Render conversation in ChatTab
    self._render_conversation()
```

Add `_on_mini_bar_moved`:

```python
def _on_mini_bar_moved(self, pos: QPoint) -> None:
    if self._bubble is not None and self._bubble.isVisible():
        mb_geo = self._mini_bar.geometry()
        anchor = QPoint(mb_geo.x() + mb_geo.width() // 2, mb_geo.y() + mb_geo.height())
        self._bubble.move_anchored(anchor)
```

Add `_on_bubble_closed`:

```python
def _on_bubble_closed(self) -> None:
    # conversation retained per spec §7.4
    pass
```

- [ ] **Step 5: Rewrite `_on_action` — use QuickActionRequest, conversation.clear, bubble streaming**

Replace the `_on_action` method (lines 312-385):

```python
def _on_action(
    self,
    action_id: str,
    *,
    custom_text_override: str | None = None,
    include_screenshot_override: bool | None = None,
) -> None:
    if self._worker is not None and self._worker.isRunning():
        return
    self._config.last_used_prompt_id = action_id
    self._store.save(self._config)

    custom_text = (
        custom_text_override if custom_text_override is not None
        else self._compose.text()
    )
    include_screenshot = (
        include_screenshot_override if include_screenshot_override is not None
        else self._compose.include_screenshot()
    )

    self._conversation.clear()

    request = QuickActionRequest(
        prompt_id=action_id,
        custom_text=custom_text,
        include_screenshot=include_screenshot,
    )

    screenshot_png: bytes | None = None
    if include_screenshot:
        try:
            screenshot_png = self._capture.grab_primary()
        except Exception as exc:  # noqa: BLE001
            self._log(f"capture failed: {exc}")
            screenshot_png = None

    if screenshot_png is not None:
        w, h = _png_dims(screenshot_png)
        self._screenshot_store.set(ScreenshotBundle(
            frames=(screenshot_png,),
            timestamp=datetime.now(tz=timezone.utc),
            width=w, height=h,
        ))

    self._last_screenshot_png = screenshot_png
    self._stream_buffer = []

    runner = InferenceRunner(
        config=self._config,
        prompt_loader=self._loader,
        provider_factory=registry.get,
        screen_capture=_PrecapturedScreen(screenshot_png) if screenshot_png else self._capture,
        run_state_store=self._run_state_store,
    )

    is_mini = self._config.mini_bar_mode

    if is_mini and self._bubble is not None:
        try:
            qa = self._loader.get_quick_action(action_id)
            action_label = qa.label
        except Exception:
            action_label = action_id
        self._bubble.reset()
        self._bubble.set_title(action_label, self._config.active_model)
        self._bubble.set_streaming(True)
        self._bubble.show()
        if self._mini_bar is not None:
            mb_geo = self._mini_bar.geometry()
            anchor = QPoint(mb_geo.x() + mb_geo.width() // 2, mb_geo.y() + mb_geo.height())
            self._bubble.move_anchored(anchor)
    else:
        self._tabs.setCurrentIndex(_TAB_CHAT)
        self._chat_tab.reset()

    self._compose.set_streaming(True)
    self.statusBar().showMessage("Streaming…")

    input_preview = self._compose_input_preview_qa(action_id, custom_text)
    self._worker = InferenceWorker.for_quick_action(
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

- [ ] **Step 6: Update `_on_chunk` — route to bubble or chat_tab**

```python
def _on_chunk(self, text: str) -> None:
    self._stream_buffer.append(text)
    if self._config.mini_bar_mode and self._bubble is not None:
        self._bubble.append_delta(text)
    else:
        self._chat_tab.append_delta(text)
```

- [ ] **Step 7: Update `_on_finished` — append to conversation**

```python
def _on_finished(self) -> None:
    self._chat_tab.finalize()
    self._compose.set_streaming(False)
    self.statusBar().showMessage("Done.", 3000)

    if self._bubble is not None:
        self._bubble.finalize()

    full_markdown = "".join(self._stream_buffer)

    # Append to conversation
    user_text = ""
    if self._last_request_qa is not None:
        user_text = self._last_request_qa.custom_text or self._last_request_qa.prompt_id
    self._conversation.append(Message(
        role="user",
        text=user_text,
        image_png=self._last_screenshot_png,
    ))
    self._conversation.append(Message(role="assistant", text=full_markdown))

    # History entry
    if self._last_request_qa is not None:
        entry = HistoryEntry(
            timestamp=datetime.now(tz=timezone.utc),
            prompt_id=self._last_request_qa.prompt_id,
            custom_text=self._last_request_qa.custom_text,
            model_id=self._config.active_model,
            include_screenshot=self._last_request_qa.include_screenshot,
            screenshot_png=self._last_screenshot_png,
            markdown=full_markdown,
        )
        self._history_store.append(entry)

    self._last_request_qa = None
    self._last_screenshot_png = None
    self._stream_buffer = []
```

Note: Change `self._last_request` (was `InferenceRequest`) to `self._last_request_qa: QuickActionRequest | None = None`.

- [ ] **Step 8: Add `_compose_input_preview_qa` helper**

```python
def _compose_input_preview_qa(self, prompt_id: str, custom_text: str) -> str:
    if custom_text:
        return custom_text
    try:
        qa = self._loader.get_quick_action(prompt_id)
        return qa.label
    except Exception:
        return prompt_id
```

- [ ] **Step 9: Add `_dispatch_follow_up` and follow-up flow**

```python
def _dispatch_follow_up(self, text: str, recapture: bool) -> None:
    if self._worker is not None and self._worker.isRunning():
        self._worker.cancel()
        self._worker.wait()

    include_screenshot = recapture or self._conversation.last_screenshot() is not None

    request = FollowUpRequest(
        user_text=text,
        include_screenshot=include_screenshot,
        recapture=recapture,
    )
    history = self._conversation.turns()

    screenshot_png: bytes | None = None
    if recapture:
        try:
            screenshot_png = self._capture.grab_primary()
            self._last_screenshot_png = screenshot_png
        except Exception as exc:  # noqa: BLE001
            self._log(f"follow-up capture failed: {exc}")

    runner = InferenceRunner(
        config=self._config,
        prompt_loader=self._loader,
        provider_factory=registry.get,
        screen_capture=self._capture,
        run_state_store=None,  # No RunState for follow-up per spec
    )

    self._stream_buffer = []

    is_mini = self._config.mini_bar_mode

    if is_mini and self._bubble is not None:
        self._bubble.set_streaming(True)
    else:
        self._tabs.setCurrentIndex(_TAB_CHAT)
        self._chat_tab.reset()

    self._compose.set_streaming(True)
    self.statusBar().showMessage("Streaming…")

    from spiresight.core.usage import _truncate_preview
    input_preview = _truncate_preview(text, 60)
    self._worker = InferenceWorker.for_follow_up(
        runner, request, history,
        model_id=self._config.active_model,
        input_preview=input_preview,
        parent=self,
    )
    self._worker.chunk.connect(self._on_chunk)
    self._worker.finished_ok.connect(self._on_follow_up_finished)
    self._worker.failed.connect(self._on_failed)
    self._worker.run_started.connect(self._tracker.call_started)
    self._worker.usage_recorded.connect(self._on_usage_recorded)
    self._worker.cancelled.connect(self._tracker.call_cancelled)
    self._worker.start()

def _on_follow_up_finished(self) -> None:
    self._chat_tab.finalize()
    self._compose.set_streaming(False)
    self.statusBar().showMessage("Done.", 3000)

    if self._bubble is not None:
        self._bubble.finalize()

    full_markdown = "".join(self._stream_buffer)

    self._conversation.append(Message(
        role="user",
        text=self._last_follow_up_text,
        image_png=self._last_screenshot_png,
    ))
    self._conversation.append(Message(role="assistant", text=full_markdown))

    self._last_screenshot_png = None
    self._stream_buffer = []
    self._last_follow_up_text = ""
```

Add `_last_follow_up_text: str = ""` to `__init__`. In `_dispatch_follow_up`, set `self._last_follow_up_text = text`.

- [ ] **Step 10: Add `_render_conversation` for ChatTab multi-turn**

```python
def _render_conversation(self) -> None:
    turns = self._conversation.turns()
    if not turns:
        return
    self._tabs.setCurrentIndex(_TAB_CHAT)
    self._chat_tab.reset()
    for msg in turns:
        if msg.role == "user":
            self._chat_tab.append_user_message(msg.text)
        else:
            self._chat_tab.append_delta(msg.text)
    self._chat_tab.finalize()
```

- [ ] **Step 11: Update `_on_compose_send` — make it follow-up aware**

If ComposePanel input and there's an active conversation, send as follow-up:

```python
def _on_compose_send(self, text: str, include_screenshot: bool) -> None:
    if self._conversation.turns():
        # Follow-up mode
        self._dispatch_follow_up(text, recapture=include_screenshot)
    else:
        # Fresh quick-action
        actions = self._loader.quick_actions()
        if not actions:
            return
        action_id = self._config.last_used_prompt_id or actions[0].id
        self._on_action(
            action_id,
            custom_text_override=text,
            include_screenshot_override=include_screenshot,
        )
```

- [ ] **Step 12: Update `_on_resend` — use QuickActionRequest**

Replace `InferenceRequest(...)` line 434 with `QuickActionRequest(...)`, and use `InferenceWorker.for_quick_action(...)`.

- [ ] **Step 13: Update `_on_usage_recorded` — add bubble cost**

After forwarding to tracker (line 423), add:

```python
if self._bubble is not None:
    self._bubble.set_cost(priced_cost, priced_record.usage)
```

- [ ] **Step 14: Update `_last_request` references**

Change all `self._last_request` to `self._last_request_qa` and update type annotation to `QuickActionRequest | None`.

- [ ] **Step 15: Commit**

```bash
git add src/spiresight/ui/windows/main_window.py
git commit -m "feat: wire InfoBubble, ConversationStore, and dual request paths in MainWindow"
```

---

### Task 15: `dark_fantasy.qss` — bubble + pin styles

**Files:**
- Modify: `src/spiresight/resources/qss/dark_fantasy.qss`

- [ ] **Step 1: Append QSS rules**

Read the qss file, append at the end:

```css
/* ── InfoBubble ─────────────────────────────────────────────── */
QWidget#info-bubble {
    background-color: #0d1018;
    border: 1px solid #1d2233;
    border-radius: 8px;
}
QWidget#bubble-title-bar {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                      stop:0 rgba(212,165,74,10), stop:1 transparent);
    border-bottom: 1px solid #1d2233;
}
QLabel#bubble-chip { color: #d4a54a; font-weight: 600; font-size: 10px; }
QLabel#bubble-model { color: #6e7a89; font-family: monospace; font-size: 10px; }
QPushButton#bubble-close { color: #6e7a89; border: none; font-size: 14px; }
QPushButton#bubble-close:hover { color: #d4743a; }
QLabel#bubble-user-msg {
    background-color: #10141e;
    border-left: 2px solid #d4a54a;
    border-radius: 0 4px 4px 0;
    padding: 6px 10px;
    color: #6e7a89;
}
QToolButton#bubble-camera {
    color: #6e7a89;
    border: 1px solid transparent;
    border-radius: 4px;
}
QToolButton#bubble-camera:checked {
    background-color: rgba(212,165,74,18);
    border-color: #d4a54a;
    color: #d4a54a;
}
QPushButton#bubble-send {
    background-color: #d4a54a;
    color: #1a1408;
    font-weight: 600;
    border-radius: 5px;
    padding: 6px 12px;
}
QLineEdit#bubble-input {
    background-color: #10141e;
    border: 1px solid #1d2233;
    border-radius: 5px;
    padding: 6px 9px;
    color: #d5cebf;
}
QLineEdit#bubble-input:focus { border-color: #3a6080; }
QPushButton#bubble-cancel {
    border: 1px solid #1d2233;
    color: #d4743a;
    background: transparent;
    padding: 2px 10px;
    border-radius: 4px;
}
QPushButton#bubble-cancel:hover { border-color: #d4743a; }

/* ── PinButton ──────────────────────────────────────────────── */
QToolButton#pin-button {
    color: #6e7a89;
    border: none;
    padding: 4px;
}
QToolButton#pin-button:checked {
    color: #d4a54a;
}
```

- [ ] **Step 2: Commit**

```bash
git add src/spiresight/resources/qss/dark_fantasy.qss
git commit -m "feat: add InfoBubble + PinButton QSS rules"
```

---

### Task 16: `app.py` — assemble ConversationStore singleton

**Files:**
- Modify: `src/spiresight/app.py`

- [ ] **Step 1: Create and inject ConversationStore**

In `run()`, after creating the config and loader but before creating MainWindow (line 55-60):

```python
from spiresight.core.conversation import ConversationStore

conversation_store = ConversationStore()

window = MainWindow(config, store, loader, pricing=pricing, conversation_store=conversation_store)
```

Update `MainWindow.__init__` signature to accept `conversation_store: ConversationStore` parameter.

- [ ] **Step 2: Verify app imports**

Run: `python -c "from spiresight.app import run; print('OK')"`
Expected: `OK` — `run()` is not actually called, just verifying all imports resolve.

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/app.py src/spiresight/ui/windows/main_window.py
git commit -m "feat: inject ConversationStore singleton from app.py"
```

---

### Task 17: End-to-end smoke test

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass (including new tests from Tasks 1-3).

- [ ] **Step 2: Import smoke test**

Run: `python -c "from spiresight.ui.windows.main_window import MainWindow; from spiresight.ui.widgets.info_bubble import InfoBubble; from spiresight.ui.widgets.pin_button import PinButton; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 3: Commit any final fixes**

```bash
git add -u
git commit -m "chore: fix import issues from integration"
```
