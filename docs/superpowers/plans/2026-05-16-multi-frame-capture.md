# Multi-Frame Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single-shot Inspect with a multi-frame capture session so the user can scroll the deck view, capture N frames, and have the LLM emit one merged `RunState` from all frames in one call.

**Architecture:** Add an in-memory `InspectSession` buffer for PNG frames; generalize the `LLMProvider.stream()` interface from a single `image_png` to a list `images`; reshape the inspect UI to `[Capture] [Done] [Clear]` with a thumbnail strip. No persistence, no stitching, no incremental merging.

**Tech Stack:** Python 3.12, PySide6 (Qt), pytest, Pydantic, OpenAI Chat Completions vision API.

**Spec:** `docs/superpowers/specs/2026-05-16-multi-frame-capture-design.md`

**Environment notes:**
- Always use `.venv/bin/python` / `.venv/bin/pytest` — never the system Python.
- Run from repo root: `/Users/haochen/Documents/Gogs_Repositories/SpireSight`.
- Tests that touch Qt widgets need `QCoreApplication` instantiated; existing tests show the pattern.

---

## Task 1: `InspectSession` in-memory frame buffer

**Files:**
- Create: `src/spiresight/core/inspect_session.py`
- Test: `tests/test_inspect_session.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_inspect_session.py
import pytest
from PySide6.QtCore import QCoreApplication

from spiresight.core.inspect_session import InspectSession


@pytest.fixture(autouse=True)
def _qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def test_starts_empty():
    s = InspectSession()
    assert s.count == 0
    assert s.frames == []


def test_add_frame_appends_and_emits_changed():
    s = InspectSession()
    calls: list[int] = []
    s.changed.connect(lambda: calls.append(s.count))

    s.add_frame(b"PNG1")
    s.add_frame(b"PNG2")

    assert s.count == 2
    assert s.frames == [b"PNG1", b"PNG2"]
    assert calls == [1, 2]


def test_frames_returns_defensive_copy():
    s = InspectSession()
    s.add_frame(b"PNG1")
    snapshot = s.frames
    snapshot.append(b"MUTATED")
    assert s.count == 1
    assert s.frames == [b"PNG1"]


def test_remove_frame_drops_index_and_emits():
    s = InspectSession()
    s.add_frame(b"A"); s.add_frame(b"B"); s.add_frame(b"C")
    emitted: list[int] = []
    s.changed.connect(lambda: emitted.append(s.count))

    s.remove_frame(1)
    assert s.frames == [b"A", b"C"]
    assert emitted == [2]


def test_remove_frame_out_of_range_raises():
    s = InspectSession()
    s.add_frame(b"A")
    with pytest.raises(IndexError):
        s.remove_frame(5)


def test_clear_empties_and_emits():
    s = InspectSession()
    s.add_frame(b"A"); s.add_frame(b"B")
    emitted: list[int] = []
    s.changed.connect(lambda: emitted.append(s.count))

    s.clear()
    assert s.count == 0
    assert s.frames == []
    assert emitted == [0]


def test_max_frames_cap_raises_runtime_error():
    s = InspectSession()
    for i in range(InspectSession.MAX_FRAMES):
        s.add_frame(f"P{i}".encode())
    assert s.count == InspectSession.MAX_FRAMES
    with pytest.raises(RuntimeError):
        s.add_frame(b"OVERFLOW")
    assert s.count == InspectSession.MAX_FRAMES  # rejection did not append
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_inspect_session.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spiresight.core.inspect_session'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/spiresight/core/inspect_session.py
"""In-memory buffer of captured PNG frames for one Inspect batch.

Lives for the duration of a `MainWindow`. Not persisted. The panel
subscribes to `changed` to re-render the thumbnail strip.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class InspectSession(QObject):
    MAX_FRAMES = 6

    changed = Signal()  # emitted after any add_frame / remove_frame / clear

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._frames: list[bytes] = []

    @property
    def count(self) -> int:
        return len(self._frames)

    @property
    def frames(self) -> list[bytes]:
        return list(self._frames)

    def add_frame(self, png: bytes) -> None:
        if len(self._frames) >= self.MAX_FRAMES:
            raise RuntimeError(
                f"Inspect session is full ({self.MAX_FRAMES} frames). "
                "Press Done or remove a frame first."
            )
        self._frames.append(png)
        self.changed.emit()

    def remove_frame(self, index: int) -> None:
        if index < 0 or index >= len(self._frames):
            raise IndexError(f"frame index {index} out of range (0..{len(self._frames) - 1})")
        del self._frames[index]
        self.changed.emit()

    def clear(self) -> None:
        if not self._frames:
            self.changed.emit()
            return
        self._frames.clear()
        self.changed.emit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_inspect_session.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/core/inspect_session.py tests/test_inspect_session.py
git commit -m "feat(core): add InspectSession frame buffer with Qt signal"
```

---

## Task 2: Rename `image_png` → `images` across provider interface

This is a mechanical rename touching the protocol, 3 providers, and 4 test files. It is one atomic commit because every call site must move together; the tree will not type-check or pass tests mid-migration.

**Files:**
- Modify: `src/spiresight/llm/provider.py`
- Modify: `src/spiresight/llm/providers/openai_provider.py`
- Modify: `src/spiresight/llm/providers/anthropic_provider.py`
- Modify: `src/spiresight/llm/providers/gemini_provider.py`
- Modify: `src/spiresight/core/runner.py` (both `inspect` and `run` call sites)
- Modify: `tests/test_openai_provider.py`
- Modify: `tests/test_provider_stubs.py`
- Modify: `tests/test_provider_contract.py`
- Modify: `tests/test_inference_runner.py` (the fake `_FakeProvider.stream` signature and assertion keys)

- [ ] **Step 1: Update the protocol**

In `src/spiresight/llm/provider.py`, change the `stream` signature:

```python
# Before
    def stream(
        self,
        *,
        model: str,
        system: str,
        user_text: str,
        image_png: bytes | None,
        cancel_event: threading.Event,
        json_mode: bool = False,
    ) -> Iterator[StreamChunk]: ...

# After
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

- [ ] **Step 2: Update OpenAI provider — signature + multi-image content builder**

In `src/spiresight/llm/providers/openai_provider.py`:

Change `stream(...)` parameter `image_png: bytes | None` → `images: list[bytes]`.

Change the call inside `payload["messages"]`:

```python
# Before
{"role": "user", "content": self._build_user_content(user_text, image_png)},
# After
{"role": "user", "content": self._build_user_content(user_text, images)},
```

Replace `_build_user_content`:

```python
@staticmethod
def _build_user_content(text: str, images: list[bytes]) -> list[dict] | str:
    if not images:
        return text
    parts: list[dict] = [{"type": "text", "text": text}]
    for png in images:
        b64 = base64.b64encode(png).decode()
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })
    return parts
```

- [ ] **Step 3: Update Anthropic and Gemini stubs — signature only**

In both `anthropic_provider.py` and `gemini_provider.py`, change the `stream` signature exactly the same way (`image_png: bytes | None` → `images: list[bytes]`). The body still raises `NotImplementedError`.

- [ ] **Step 4: Update runner call sites**

In `src/spiresight/core/runner.py`:

In `inspect(...)`, change the `provider.stream(...)` keyword:

```python
# Before
for chunk in provider.stream(
    model=model.id,
    system=sp.content,
    user_text=INSPECTOR_USER_TEXT,
    image_png=image_png,
    cancel_event=cancel_event,
    json_mode=True,
):
# After
for chunk in provider.stream(
    model=model.id,
    system=sp.content,
    user_text=INSPECTOR_USER_TEXT,
    images=[image_png],
    cancel_event=cancel_event,
    json_mode=True,
):
```

In `run(...)`, replace `image_png=image_png` with a list adapter:

```python
# Before
yield from provider.stream(
    model=model.id,
    system=self._compose_system(sp.content),
    user_text=user_text,
    image_png=image_png,
    cancel_event=cancel_event,
)
# After
yield from provider.stream(
    model=model.id,
    system=self._compose_system(sp.content),
    user_text=user_text,
    images=[image_png] if image_png is not None else [],
    cancel_event=cancel_event,
)
```

(Task 3 will change `inspect()` further. For this task, the inspect path still grabs one screenshot internally — we are *only* renaming the provider kwarg.)

- [ ] **Step 5: Update test files — rename `image_png=` to `images=` and adjust values**

In `tests/test_openai_provider.py`, every `image_png=None` becomes `images=[]` and every `image_png=png` becomes `images=[png]`.

In `tests/test_provider_stubs.py`, change the kwarg in the `p.stream(...)` call:

```python
# Before
list(p.stream(model="x", system="s", user_text="u",
              image_png=None, cancel_event=threading.Event()))
# After
list(p.stream(model="x", system="s", user_text="u",
              images=[], cancel_event=threading.Event()))
```

In `tests/test_provider_contract.py`:

```python
# Before — _Fake.stream signature
def stream(self, *, model, system, user_text, image_png, cancel_event) -> Iterator[StreamChunk]:
# After
def stream(self, *, model, system, user_text, images, cancel_event) -> Iterator[StreamChunk]:
```

And the call site:

```python
# Before
chunks = list(fake.stream(
    model="fake-1", system="sys", user_text="hi",
    image_png=None, cancel_event=threading.Event(),
))
# After
chunks = list(fake.stream(
    model="fake-1", system="sys", user_text="hi",
    images=[], cancel_event=threading.Event(),
))
```

In `tests/test_inference_runner.py`:

```python
# Before — _FakeProvider.stream signature + recorded keys
def stream(self, *, model, system, user_text, image_png, cancel_event, json_mode=False):
    self.last_call = dict(model=model, system=system, user_text=user_text,
                          image_png=image_png, json_mode=json_mode)
    yield from self._chunks
# After
def stream(self, *, model, system, user_text, images, cancel_event, json_mode=False):
    self.last_call = dict(model=model, system=system, user_text=user_text,
                          images=images, json_mode=json_mode)
    yield from self._chunks
```

Then update every assertion against `last_call`:

- `assert provider.last_call["image_png"] == b"PNG_BYTES"` → `assert provider.last_call["images"] == [b"PNG_BYTES"]`
- `assert provider.last_call["image_png"] is None` → `assert provider.last_call["images"] == []`

(There are three such assertions in the file at this point: in `test_run_streams_text_with_image_when_required`, `test_run_omits_image_when_screenshot_unchecked`, and `test_inspect_buffers_chunks_parses_json_returns_run_state`. Find all of them with `grep -n image_png tests/test_inference_runner.py` before editing.)

- [ ] **Step 6: Run the full test suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: All tests pass. If any test still uses `image_png=...`, the failure message will name the file/line — fix and re-run.

- [ ] **Step 7: Commit**

```bash
git add src/spiresight/llm/provider.py \
        src/spiresight/llm/providers/openai_provider.py \
        src/spiresight/llm/providers/anthropic_provider.py \
        src/spiresight/llm/providers/gemini_provider.py \
        src/spiresight/core/runner.py \
        tests/test_openai_provider.py \
        tests/test_provider_stubs.py \
        tests/test_provider_contract.py \
        tests/test_inference_runner.py
git commit -m "refactor(llm): generalize provider.stream from image_png to images list"
```

---

## Task 3: `InferenceRunner.inspect()` accepts caller-supplied frames

**Files:**
- Modify: `src/spiresight/core/runner.py`
- Modify: `tests/test_inference_runner.py`

The current `inspect()` calls `screen_capture.grab_primary()` itself. After this task, capture is done by the caller (the worker, which receives buffered frames from the panel). `inspect()` only orchestrates the LLM call.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_inference_runner.py`:

```python
def test_inspect_with_multiple_frames_passes_all_to_provider():
    sp = SystemPrompt(id="inspector", description="", content="emit JSON only")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o",
                          frozenset({Cap.VISION, Cap.JSON_MODE}), 128_000)],
        chunks=[
            StreamChunk('{"cards":[],"relics":[],"potions":[],'),
            StreamChunk('"archetype_candidates":[],"overall_eval":"",'),
            StreamChunk('"inspected_at":"2026-05-16T00:00:00+00:00"}', "stop"),
        ],
    )

    class _StaticLoader:
        def get_system_prompt(self, _): return sp

    cfg = AppConfig(active_provider="openai", active_model="gpt-4o")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    runner = InferenceRunner(
        config=cfg, prompt_loader=_StaticLoader(),
        provider_factory=lambda n, p: provider, screen_capture=_FakeCapture(),
    )

    state = runner.inspect(
        images=[b"PNG_A", b"PNG_B", b"PNG_C"],
        cancel_event=threading.Event(),
    )
    assert state.cards == []
    assert provider.last_call["images"] == [b"PNG_A", b"PNG_B", b"PNG_C"]


def test_inspect_with_no_frames_raises_value_error():
    sp = SystemPrompt(id="inspector", description="", content="json")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o",
                          frozenset({Cap.VISION, Cap.JSON_MODE}), 128_000)],
        chunks=[],
    )

    class _StaticLoader:
        def get_system_prompt(self, _): return sp

    cfg = AppConfig(active_provider="openai", active_model="gpt-4o")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    runner = InferenceRunner(
        config=cfg, prompt_loader=_StaticLoader(),
        provider_factory=lambda n, p: provider, screen_capture=_FakeCapture(),
    )

    with pytest.raises(ValueError, match="at least one frame"):
        runner.inspect(images=[], cancel_event=threading.Event())
    assert provider.last_call is None  # provider was never called
```

Also update the **three pre-existing inspect tests** in this file (`test_inspect_buffers_chunks_parses_json_returns_run_state`, `test_inspect_raises_value_error_on_malformed_json`, `test_inspect_raises_missing_capability_when_model_lacks_json_mode`) to call `runner.inspect(images=[b"PNG_BYTES"], cancel_event=...)` and remove the assertion `assert provider.last_call["images"] == [b"PNG_BYTES"]` from the malformed/capability tests (those don't reach the provider for the capability one, and don't care about images for the malformed one).

For the first existing test (`test_inspect_buffers_chunks...`), keep the assertion but update the value: `assert provider.last_call["images"] == [b"PNG_BYTES"]`.

- [ ] **Step 2: Run inspect-related tests to verify they fail**

Run: `.venv/bin/pytest tests/test_inference_runner.py -v -k inspect`
Expected: New tests fail with `TypeError: inspect() got an unexpected keyword argument 'images'` (current signature still uses no `images` parameter). The three existing inspect tests fail with the same error after you update their call sites.

- [ ] **Step 3: Update `inspect()` signature and body**

In `src/spiresight/core/runner.py`, replace the `inspect` method:

```python
def inspect(self, *, images: list[bytes], cancel_event: threading.Event) -> RunState:
    """Send N pre-captured PNG frames to the inspector prompt, parse RunState."""
    if not images:
        raise ValueError("inspect requires at least one frame")

    sp = self._loader.get_system_prompt(INSPECTOR_PROMPT_ID)

    provider_cfg = self._config.providers.get(
        self._config.active_provider, ProviderConfig()
    )
    if not provider_cfg.api_key:
        raise MissingAPIKey(self._config.active_provider)
    provider = self._factory(self._config.active_provider, provider_cfg)

    model = self._resolve_model(provider, self._config.active_model)
    missing = _INSPECT_CAPS - set(model.capabilities)
    if missing:
        raise MissingCapabilityError(model=model.id, missing=missing)

    buffer: list[str] = []
    for chunk in provider.stream(
        model=model.id,
        system=sp.content,
        user_text=INSPECTOR_USER_TEXT,
        images=images,
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
        raise ValueError(
            f"Inspector returned unparseable JSON: {raw[:200]}"
        ) from exc
```

Notice: the line `image_png = self._capture.grab_primary()` is **removed** — capture now happens upstream.

- [ ] **Step 4: Run the full test suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/core/runner.py tests/test_inference_runner.py
git commit -m "feat(core): InferenceRunner.inspect accepts caller-supplied frames"
```

---

## Task 4: `InspectWorker` carries the frame list

**Files:**
- Modify: `src/spiresight/ui/workers/inspect_worker.py`

The worker no longer wraps `runner.inspect()` blindly — it owns the `frames` payload that the panel buffered.

- [ ] **Step 1: Update the worker**

Replace the file body with:

```python
from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from spiresight.core.run_state import RunState
from spiresight.core.runner import InferenceRunner


class InspectWorker(QThread):
    ready = Signal(object)   # RunState
    failed = Signal(object)  # Exception

    def __init__(
        self,
        runner: InferenceRunner,
        frames: list[bytes],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._runner = runner
        self._frames = list(frames)  # defensive copy; session may mutate later
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            state: RunState = self._runner.inspect(
                images=self._frames, cancel_event=self._cancel
            )
            self.ready.emit(state)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(exc)
```

- [ ] **Step 2: Run the test suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: All tests pass. There is no dedicated worker test (worker is integration glue; it gets exercised via the main_window smoke test in Task 8).

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/ui/workers/inspect_worker.py
git commit -m "feat(ui): InspectWorker accepts pre-captured frames"
```

---

## Task 5: Update `sts_inspector` prompt for multi-image input

**Files:**
- Modify: `prompts/system_prompts.yaml`

- [ ] **Step 1: Edit the prompt**

In `prompts/system_prompts.yaml`, find the `sts_inspector` block (its `content:` starts with *"You are a Slay the Spire II run-state extractor..."*). Insert this paragraph **between the JSON schema block and the `Rules:` block**, indented to match surrounding lines:

```yaml
    You will receive one or more screenshots of the deck view, possibly
    with overlap from the player scrolling. Treat them as views of the
    same deck — a card visible in multiple frames is the same card and
    must be counted exactly once. Aggregate the full deck from all
    frames before emitting the JSON.

```

(Mind the indentation: each line is prefixed with 4 spaces to stay inside the YAML pipe-string for `content:`.)

- [ ] **Step 2: Verify the YAML still loads**

Run: `.venv/bin/python -c "from spiresight.prompts.loader import PromptLoader; PromptLoader().get_system_prompt('sts_inspector')"`
Expected: no exception, no output.

- [ ] **Step 3: Commit**

```bash
git add prompts/system_prompts.yaml
git commit -m "prompts(inspector): instruct LLM to merge multi-frame deck views"
```

---

## Task 6: `RunStatePanel` overhaul — thumbnails, new buttons, new signals

**Files:**
- Modify: `src/spiresight/ui/widgets/run_state_panel.py`

This task replaces `inspect_requested` / `set_inspect_enabled` with `capture_requested` / `done_requested` / `set_capture_enabled` / `set_busy`, and adds the thumbnail strip wired to `InspectSession.changed`.

There is no automated test for the widget (it's UI glue tested manually in Task 8). We rely on the existing tests still passing — but no test in `tests/` imports `RunStatePanel`, so the type rename is internally consistent only when Task 7 also lands.

- [ ] **Step 1: Replace the file**

Overwrite `src/spiresight/ui/widgets/run_state_panel.py`:

```python
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from spiresight.core.inspect_session import InspectSession
from spiresight.core.run_state import RunState
from spiresight.ui.state.run_state_store import RunStateStore

_USEFULNESS_COLORS = {
    "key":         "#d4a54a",
    "good":        "#6bb5e8",
    "situational": "#d5cebf",
    "skip":        "#6e7a89",
}

_RARITY_GLYPHS = {
    "starter":  "○",
    "common":   "●",
    "uncommon": "◆",
    "rare":     "◆",
}


class _Thumbnail(QFrame):
    """A small framed thumbnail with an × removal button overlay."""
    remove_clicked = Signal(int)

    def __init__(self, png: bytes, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index = index
        self.setFixedSize(64, 36)
        self.setFrameShape(QFrame.Shape.Box)
        self.setStyleSheet("background-color: #2a2a2a; border: 1px solid #444;")

        pix = QPixmap()
        pix.loadFromData(png, "PNG")
        scaled = pix.scaled(
            QSize(64, 36),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        img_label = QLabel(self)
        img_label.setPixmap(scaled)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_label.setGeometry(0, 0, 64, 36)

        x_btn = QPushButton("×", self)
        x_btn.setFixedSize(14, 14)
        x_btn.setStyleSheet(
            "QPushButton {background: rgba(0,0,0,0.7); color: white; "
            "border: none; font-weight: bold; font-size: 10px;} "
            "QPushButton:hover {background: #c84a4a;}"
        )
        x_btn.move(64 - 14, 0)
        x_btn.clicked.connect(lambda: self.remove_clicked.emit(self._index))

        self.setToolTip(f"Frame {index + 1}")


class RunStatePanel(QWidget):
    capture_requested = Signal()
    done_requested    = Signal()
    clear_requested   = Signal()

    def __init__(
        self,
        store: RunStateStore,
        session: InspectSession,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._session = session
        self._capability_ok = True
        self._capability_tooltip = ""
        self._busy = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        header = QLabel("Run State")
        header.setProperty("role", "section-header")
        outer.addWidget(header)

        # ── thumbnail strip (horizontally scrollable) ────────────
        self._strip_scroll = QScrollArea()
        self._strip_scroll.setWidgetResizable(True)
        self._strip_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._strip_scroll.setFixedHeight(0)  # hidden when empty
        self._strip_host = QWidget()
        self._strip_layout = QHBoxLayout(self._strip_host)
        self._strip_layout.setContentsMargins(0, 0, 0, 0)
        self._strip_layout.setSpacing(4)
        self._strip_layout.addStretch(1)
        self._strip_scroll.setWidget(self._strip_host)
        outer.addWidget(self._strip_scroll)

        # ── button row ──────────────────────────────────────────
        button_row = QHBoxLayout()
        self._capture_btn = QPushButton("Capture")
        self._capture_btn.setObjectName("primary")
        self._capture_btn.clicked.connect(self.capture_requested.emit)
        self._done_btn = QPushButton("Done")
        self._done_btn.clicked.connect(self.done_requested.emit)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self.clear_requested.emit)
        button_row.addWidget(self._capture_btn)
        button_row.addWidget(self._done_btn)
        button_row.addWidget(self._clear_btn)
        outer.addLayout(button_row)

        # ── state content (existing rendering, scrollable) ──────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._content_host = QWidget()
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(4)
        self._scroll.setWidget(self._content_host)
        outer.addWidget(self._scroll, stretch=1)

        store.changed.connect(self._render)
        session.changed.connect(self._refresh_thumbnails)
        self._render(store.get())
        self._refresh_thumbnails()
        self._update_button_states()

    # ── public control API ──────────────────────────────────────

    def set_capture_enabled(self, enabled: bool, tooltip: str = "") -> None:
        self._capability_ok = enabled
        self._capability_tooltip = tooltip
        self._update_button_states()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_button_states()

    # ── thumbnail strip ─────────────────────────────────────────

    def _refresh_thumbnails(self) -> None:
        # clear existing
        while self._strip_layout.count():
            item = self._strip_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        frames = self._session.frames
        if not frames:
            self._strip_scroll.setFixedHeight(0)
            self._strip_layout.addStretch(1)
            self._update_button_states()
            return

        self._strip_scroll.setFixedHeight(44)
        for i, png in enumerate(frames):
            thumb = _Thumbnail(png, i, parent=self._strip_host)
            thumb.remove_clicked.connect(self._session.remove_frame)
            self._strip_layout.addWidget(thumb)
        self._strip_layout.addStretch(1)
        self._update_button_states()

    # ── button state machine ────────────────────────────────────

    def _update_button_states(self) -> None:
        count = self._session.count
        at_cap = count >= InspectSession.MAX_FRAMES

        if self._busy:
            self._capture_btn.setEnabled(False)
            self._capture_btn.setToolTip("")
            self._done_btn.setEnabled(False)
            self._done_btn.setText("Analyzing…")
            self._done_btn.setToolTip("")
            return

        self._done_btn.setText("Done")

        if not self._capability_ok:
            self._capture_btn.setEnabled(False)
            self._capture_btn.setToolTip(self._capability_tooltip)
            self._done_btn.setEnabled(False)
            self._done_btn.setToolTip(self._capability_tooltip)
            return

        if at_cap:
            self._capture_btn.setEnabled(False)
            self._capture_btn.setToolTip(
                f"Maximum {InspectSession.MAX_FRAMES} frames per session."
            )
        else:
            self._capture_btn.setEnabled(True)
            self._capture_btn.setToolTip("")

        if count == 0:
            self._done_btn.setEnabled(False)
            self._done_btn.setToolTip("Capture at least one frame first.")
        else:
            self._done_btn.setEnabled(True)
            self._done_btn.setToolTip("")

    # ── state rendering (unchanged behavior) ────────────────────

    def _clear_content(self) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render(self, state: RunState | None) -> None:
        self._clear_content()
        if state is None:
            empty = QLabel(
                "Press Capture to grab one or more deck-view frames, then Done."
            )
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #6e7a89;")
            self._content_layout.addWidget(empty)
            self._content_layout.addStretch(1)
            return

        if state.archetype_candidates:
            self._content_layout.addWidget(self._subheader("Archetype"))
            for a in state.archetype_candidates:
                self._content_layout.addWidget(
                    self._line(f"● {a.name} ({a.confidence})",
                               color=_USEFULNESS_COLORS["key"]
                               if a.confidence == "high" else None)
                )

        if state.cards:
            total = sum(c.count for c in state.cards)
            self._content_layout.addWidget(self._subheader(f"Cards ({total})"))
            ordered = sorted(
                state.cards,
                key=lambda c: ("key", "good", "situational", "skip").index(c.usefulness),
            )
            for c in ordered:
                glyph = _RARITY_GLYPHS.get(c.rarity, "●")
                label = c.name if c.count == 1 else f"{c.name} x{c.count}"
                text = f"{glyph} {label}"
                if c.note:
                    text += f"  — {c.note}"
                self._content_layout.addWidget(
                    self._line(text, color=_USEFULNESS_COLORS.get(c.usefulness))
                )

        if state.relics:
            self._content_layout.addWidget(self._subheader("Relics"))
            relic_text = " · ".join(r.name for r in state.relics)
            relic_label = QLabel(relic_text)
            relic_label.setWordWrap(True)
            self._content_layout.addWidget(relic_label)

        if state.potions:
            self._content_layout.addWidget(self._subheader("Potions"))
            self._content_layout.addWidget(QLabel(" · ".join(state.potions)))

        if state.overall_eval.strip():
            self._content_layout.addWidget(self._subheader("Eval"))
            eval_label = QLabel(state.overall_eval.strip())
            eval_label.setWordWrap(True)
            eval_label.setStyleSheet("color: #d5cebf;")
            self._content_layout.addWidget(eval_label)

        self._content_layout.addStretch(1)

    @staticmethod
    def _subheader(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #6e7a89; font-size: 10px; "
                          "text-transform: uppercase; margin-top: 4px;")
        return lbl

    @staticmethod
    def _line(text: str, color: str | None = None) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        if color:
            lbl.setStyleSheet(f"color: {color};")
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        return lbl
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `.venv/bin/python -c "from spiresight.ui.widgets.run_state_panel import RunStatePanel; print(RunStatePanel)"`
Expected: prints `<class 'spiresight.ui.widgets.run_state_panel.RunStatePanel'>` with no traceback.

(Do **not** run the full test suite yet — `main_window.py` still references the old signals/methods and the app won't start. Task 7 fixes that.)

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/ui/widgets/run_state_panel.py
git commit -m "feat(ui): RunStatePanel with thumbnail strip + Capture/Done/Clear buttons"
```

---

## Task 7: Wire `InspectSession` + new panel into `MainWindow`

**Files:**
- Modify: `src/spiresight/ui/windows/main_window.py`

- [ ] **Step 1: Add the import**

Add to the imports block (alongside `RunStateStore`):

```python
from spiresight.core.inspect_session import InspectSession
```

- [ ] **Step 2: Instantiate the session in `__init__`**

After the `self._run_state_store = RunStateStore(self)` line, add:

```python
self._inspect_session = InspectSession(self)
```

- [ ] **Step 3: Update the panel construction and signal wiring**

Replace this block (around line 81–84):

```python
self._run_state_panel = RunStatePanel(self._run_state_store, parent=self)
self._run_state_panel.inspect_requested.connect(self._on_inspect_requested)
self._run_state_panel.clear_requested.connect(self._run_state_store.clear)
sb_layout.addWidget(self._run_state_panel, stretch=1)
```

with:

```python
self._run_state_panel = RunStatePanel(
    self._run_state_store, self._inspect_session, parent=self
)
self._run_state_panel.capture_requested.connect(self._on_capture_requested)
self._run_state_panel.done_requested.connect(self._on_done_requested)
self._run_state_panel.clear_requested.connect(self._on_clear_requested)
sb_layout.addWidget(self._run_state_panel, stretch=1)
```

- [ ] **Step 4: Replace the inspect-flow handlers**

Replace the existing methods `_on_inspect_requested`, `_on_inspect_ready`, `_on_inspect_failed`, and `_refresh_inspect_availability` with these implementations. Keep the surrounding `# ─── inspect flow ───` comment marker.

```python
# ─── inspect flow ────────────────────────────────────────────

def _on_capture_requested(self) -> None:
    try:
        png = self._capture.grab_primary()
    except Exception as exc:  # noqa: BLE001
        self.statusBar().showMessage(f"Capture failed: {exc}", 5000)
        return
    try:
        self._inspect_session.add_frame(png)
    except RuntimeError as exc:
        self.statusBar().showMessage(str(exc), 5000)
        return
    self.statusBar().showMessage(
        f"Captured frame {self._inspect_session.count}.", 2000
    )

def _on_done_requested(self) -> None:
    if self._inspect_worker is not None and self._inspect_worker.isRunning():
        return
    frames = self._inspect_session.frames
    if not frames:
        return
    runner = InferenceRunner(
        config=self._config,
        prompt_loader=self._loader,
        provider_factory=registry.get,
        screen_capture=self._capture,
        run_state_store=self._run_state_store,
    )
    self._run_state_panel.set_busy(True)
    self.statusBar().showMessage(
        f"Inspecting {len(frames)} frame(s)…"
    )

    self._inspect_worker = InspectWorker(runner, frames, self)
    self._inspect_worker.ready.connect(self._on_inspect_ready)
    self._inspect_worker.failed.connect(self._on_inspect_failed)
    self._inspect_worker.start()

def _on_clear_requested(self) -> None:
    self._inspect_session.clear()
    self._run_state_store.clear()
    self.statusBar().showMessage("Run state cleared.", 2000)

def _on_inspect_ready(self, state: RunState) -> None:
    self._run_state_store.set(state)
    self._inspect_session.clear()
    self._run_state_panel.set_busy(False)
    self.statusBar().showMessage("Run state captured.", 3000)

def _on_inspect_failed(self, exc: Exception) -> None:
    self._run_state_panel.set_busy(False)
    # session frames are preserved so the user can retry
    if isinstance(exc, MissingCapabilityError):
        missing = ", ".join(sorted(c.value for c in exc.missing))
        self.statusBar().showMessage(
            f"Inspect needs {missing} — switch model.", 8000
        )
    elif isinstance(exc, ValueError):
        self.statusBar().showMessage(
            "Inspect failed: malformed response, try again.", 8000
        )
    else:
        self.statusBar().showMessage(f"Inspect failed: {exc}", 8000)

def _refresh_inspect_availability(self) -> None:
    try:
        provider_cfg = self._config.providers.get(self._config.active_provider)
        if provider_cfg is None:
            self._run_state_panel.set_capture_enabled(
                False, "Configure a provider first."
            )
            return
        provider = registry.get(self._config.active_provider, provider_cfg)
        model = next(
            (m for m in provider.list_models()
             if m.id == self._config.active_model), None
        )
        if model is None:
            self._run_state_panel.set_capture_enabled(False, "Select a model.")
            return
        needed = {Capability.VISION, Capability.JSON_MODE}
        missing = needed - set(model.capabilities)
        if missing:
            names = ", ".join(sorted(c.value for c in missing))
            self._run_state_panel.set_capture_enabled(
                False, f"Active model lacks {names}."
            )
        else:
            self._run_state_panel.set_capture_enabled(True)
    except Exception:  # noqa: BLE001
        self._run_state_panel.set_capture_enabled(True)
```

- [ ] **Step 5: Search for any leftover references to the removed API**

Run: `grep -n "inspect_requested\|set_inspect_enabled\|_on_inspect_requested\b" src/spiresight/ui/windows/main_window.py`
Expected: no matches.

If anything turns up (other callers, settings dialog, mini-bar wiring), update those references the same way: `inspect_requested` → `done_requested` only if you genuinely want a "fire inspect now" semantics; otherwise re-route through `capture_requested` / `done_requested` as appropriate.

- [ ] **Step 6: Run the full test suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: All tests pass. (No test imports `main_window`, but the import graph must still resolve when the app starts.)

- [ ] **Step 7: Verify the app boots**

Run: `.venv/bin/python -m spiresight &` then `sleep 3 && kill %1` (or use a brief launch you can dismiss manually).
Expected: window opens with the new `[Capture] [Done] [Clear]` row and an empty thumbnail strip area. No traceback on startup.

- [ ] **Step 8: Commit**

```bash
git add src/spiresight/ui/windows/main_window.py
git commit -m "feat(ui): wire InspectSession and Capture/Done flow into MainWindow"
```

---

## Task 8: End-to-end smoke (manual)

**Files:** none modified (verification only).

This task confirms the user-facing flow works against a real provider. It is intentionally manual — pixel-level UI tests have low ROI here.

- [ ] **Step 1: Run the app against a real OpenAI key**

Ensure `~/.config/spiresight/config.toml` (or wherever the app reads from) has a valid OpenAI key configured and a vision+JSON-mode capable model (e.g., `gpt-4o`) is selected.

Run: `.venv/bin/python -m spiresight`

- [ ] **Step 2: Validate the capture session**

1. Open Slay the Spire II, navigate to the deck-view screen with a deck large enough to require scrolling.
2. In SpireSight, click **Capture** — confirm one thumbnail appears.
3. Scroll the in-game deck view, click **Capture** again — confirm a second thumbnail.
4. Add a third — confirm three thumbnails.
5. Click the `×` on the middle thumbnail — confirm it disappears and the remaining two reorder to indices 0 and 1.
6. Click **Done** — Done button shows "Analyzing…" and is disabled; Capture is disabled.
7. After a few seconds, the run state populates in the lower half of the panel; thumbnails disappear; buttons return to default state.

- [ ] **Step 3: Validate failure modes**

1. With a non-JSON-mode model selected (e.g., switch to a stub that lacks `JSON_MODE`), confirm both Capture and Done are disabled with the tooltip "Active model lacks json_mode."
2. Press Done with zero frames — Done should already be disabled with tooltip "Capture at least one frame first."
3. Capture 6 frames — Capture button disables with tooltip "Maximum 6 frames per session."

- [ ] **Step 4: Validate Clear**

1. With a captured RunState visible and some thumbnails buffered, click **Clear**.
2. Both the thumbnails and the rendered RunState section disappear; the empty-state hint reappears.

- [ ] **Step 5: Verify state injection still works**

1. After a successful inspect, fire any quick-action (e.g., "Card pick advice") with a screenshot — confirm the response refers to your deck composition (cards/relics/archetype) rather than generic advice. This confirms `to_prompt_block()` injection is intact (no regression from Task 4 of the original plan).

- [ ] **Step 6: No commit unless something was tweaked**

If smoke testing revealed a bug, fix it inline as a follow-up commit using the conventional commit prefix that matches the area (e.g., `fix(ui): ...`).

---

## Notes for the implementer

- **TDD discipline:** every code task except the prompt edit (Task 5) and the UI overhaul (Tasks 6–7) lands its test first. Tasks 6 and 7 are GUI glue with no pure-Python testable surface; the smoke pass in Task 8 is the verification.
- **No backwards-compat shims:** delete `inspect_requested` and `set_inspect_enabled` cleanly. No deprecation wrappers, no `# removed` comments.
- **Defensive copies:** both `InspectSession.frames` and `InspectWorker._frames` copy — the panel must not be able to mutate the worker's payload mid-flight.
- **`.venv` is mandatory:** all `python` / `pytest` invocations go through `.venv/bin/...`.
