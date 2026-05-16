# Run-State Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-run memory so the LLM sees the player's current deck/relics/archetype on every advice call, with a manual *Inspect Now* button that captures structured JSON from a screenshot and renders it in a sidebar panel.

**Architecture:** Pure-Python Pydantic models in `core/`, Qt-aware store in `ui/state/`, separate `inspect()` runner method using buffered JSON-mode provider calls, automatic prompt-block injection into every existing `quick_action`.

**Tech Stack:** PySide6, Pydantic v2, pytest, respx (for HTTP mocks), httpx, pyyaml.

**Spec:** `docs/superpowers/specs/2026-05-16-prompt-run-state-design.md`

---

## File Structure

**New files:**
- `src/spiresight/core/run_state.py` — Pydantic models (`Card`, `Relic`, `ArchetypeCandidate`, `RunState`) + `to_prompt_block()`. Pure Python, no Qt.
- `src/spiresight/ui/state/__init__.py` — empty package marker.
- `src/spiresight/ui/state/run_state_store.py` — `RunStateStore(QObject)` with `changed` signal.
- `src/spiresight/ui/widgets/run_state_panel.py` — sidebar widget rendering state + Inspect/Clear buttons.
- `src/spiresight/ui/workers/inspect_worker.py` — `QThread` wrapping `InferenceRunner.inspect()`, buffers full response, emits parsed `RunState`.
- `tests/test_run_state.py` — model + prompt-block tests.
- `tests/test_run_state_store.py` — store get/set/clear + signal tests.

**Modified files:**
- `src/spiresight/llm/provider.py` — add `json_mode: bool = False` to `LLMProvider.stream()` protocol.
- `src/spiresight/llm/providers/openai_provider.py` — accept `json_mode`, set `response_format={"type":"json_object"}`.
- `src/spiresight/llm/providers/anthropic_provider.py` — accept `json_mode` (still raises `NotImplementedError`).
- `src/spiresight/llm/providers/gemini_provider.py` — same.
- `src/spiresight/core/runner.py` — accept optional `run_state_store`, append prompt block to system, add `inspect()` method.
- `src/spiresight/ui/workers/inference_worker.py` — no behavior change (left alone; `InspectWorker` lives in a sibling file).
- `src/spiresight/ui/windows/main_window.py` — instantiate store, mount panel, widen window (880→980), widen sidebar (240→280), connect inspect/clear buttons.
- `prompts/system_prompts.yaml` — add `sts_inspector`, append usage hint to `sts_expert`.
- `tests/test_inference_runner.py` — add cases for state injection + `inspect()`.
- `tests/test_openai_provider.py` — add case for `json_mode` request body.
- `tests/test_provider_stubs.py` — update for new kwarg.

---

## Task 1: Pydantic data model (`core/run_state.py`)

**Files:**
- Create: `src/spiresight/core/run_state.py`
- Test: `tests/test_run_state.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_run_state.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from spiresight.core.run_state import (
    ArchetypeCandidate, Card, Relic, RunState,
)


def _sample_state() -> RunState:
    return RunState(
        cards=[
            Card(name="Strike", count=4, rarity="starter", usefulness="skip", note="filler"),
            Card(name="Heavy Blade+", count=1, rarity="uncommon", usefulness="key",
                 note="main scaler"),
            Card(name="Pommel Strike", count=2, rarity="common", usefulness="good"),
        ],
        relics=[
            Relic(name="Akabeko", synergy_tags=["strength"]),
            Relic(name="Vajra", synergy_tags=["strength"]),
        ],
        potions=["Energy Potion"],
        archetype_candidates=[
            ArchetypeCandidate(name="Strength", confidence="high",
                               rationale="Akabeko + Heavy Blade"),
            ArchetypeCandidate(name="Exhaust", confidence="low",
                               rationale="no pickups yet"),
        ],
        overall_eval="Strong strength curve. Next pick should scale.",
        inspected_at=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )


def test_run_state_json_roundtrip():
    state = _sample_state()
    blob = state.model_dump_json()
    again = RunState.model_validate_json(blob)
    assert again == state


def test_to_prompt_block_contains_archetype_cards_relics_eval():
    state = _sample_state()
    block = state.to_prompt_block()
    assert block.startswith("## Current Run Context")
    assert "Strength (high)" in block
    assert "Exhaust (low)" in block
    assert "Heavy Blade+" in block
    assert "Strike x4" in block
    assert "Akabeko" in block and "Vajra" in block
    assert "Strong strength curve" in block


def test_to_prompt_block_groups_cards_by_usefulness():
    state = _sample_state()
    block = state.to_prompt_block()
    # key cards listed before filler
    key_idx = block.index("Heavy Blade+")
    skip_idx = block.index("Strike x4")
    assert key_idx < skip_idx


def test_to_prompt_block_omits_empty_sections():
    minimal = RunState(
        cards=[Card(name="Strike", count=4, rarity="starter", usefulness="skip")],
        relics=[],
        potions=[],
        archetype_candidates=[],
        overall_eval="",
        inspected_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
    )
    block = minimal.to_prompt_block()
    assert "Relics" not in block
    assert "Eval" not in block
    assert "Archetype" not in block


def test_rejects_bad_usefulness():
    with pytest.raises(ValidationError):
        Card(name="X", rarity="common", usefulness="amazing")


def test_rejects_bad_rarity():
    with pytest.raises(ValidationError):
        Card(name="X", rarity="legendary", usefulness="good")


def test_rejects_bad_confidence():
    with pytest.raises(ValidationError):
        ArchetypeCandidate(name="X", confidence="certain", rationale="hi")
```

- [ ] **Step 1.2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_run_state.py -v`
Expected: ImportError (module doesn't exist).

- [ ] **Step 1.3: Create `src/spiresight/core/run_state.py`**

```python
"""Per-run memory: structured snapshot of the player's deck state.

Pure-Python module — no Qt imports — so the inference layer can depend
on it without dragging in PySide6. The Qt-aware store lives in
`ui/state/run_state_store.py`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Usefulness = Literal["skip", "situational", "good", "key"]
Rarity = Literal["starter", "common", "uncommon", "rare"]
Confidence = Literal["low", "medium", "high"]

_USEFULNESS_ORDER: tuple[Usefulness, ...] = ("key", "good", "situational", "skip")


class Card(BaseModel):
    name: str
    count: int = 1
    rarity: Rarity
    usefulness: Usefulness
    note: str = ""


class Relic(BaseModel):
    name: str
    synergy_tags: list[str] = Field(default_factory=list)


class ArchetypeCandidate(BaseModel):
    name: str
    confidence: Confidence
    rationale: str = ""


class RunState(BaseModel):
    cards: list[Card]
    relics: list[Relic]
    potions: list[str]
    archetype_candidates: list[ArchetypeCandidate]
    overall_eval: str
    inspected_at: datetime

    def to_prompt_block(self) -> str:
        """Compact natural-language summary for injection into system prompt."""
        lines: list[str] = ["## Current Run Context"]

        if self.archetype_candidates:
            arches = " / ".join(
                f"{a.name} ({a.confidence})" for a in self.archetype_candidates
            )
            lines.append(f"Archetype: {arches}")

        if self.cards:
            grouped: dict[str, list[str]] = {u: [] for u in _USEFULNESS_ORDER}
            for c in self.cards:
                label = c.name if c.count == 1 else f"{c.name} x{c.count}"
                grouped[c.usefulness].append(label)
            for tier in _USEFULNESS_ORDER:
                if not grouped[tier]:
                    continue
                heading = {
                    "key": "Key cards",
                    "good": "Solid",
                    "situational": "Situational",
                    "skip": "Filler",
                }[tier]
                lines.append(f"{heading}: {', '.join(grouped[tier])}")

        if self.relics:
            relic_strs = [
                f"{r.name} ({', '.join(r.synergy_tags)})" if r.synergy_tags else r.name
                for r in self.relics
            ]
            lines.append(f"Relics: {', '.join(relic_strs)}")

        if self.potions:
            lines.append(f"Potions: {', '.join(self.potions)}")

        if self.overall_eval.strip():
            lines.append(f"Eval: {self.overall_eval.strip()}")

        return "\n".join(lines)
```

- [ ] **Step 1.4: Run the tests — all should pass**

Run: `.venv/bin/pytest tests/test_run_state.py -v`
Expected: 7 passed.

- [ ] **Step 1.5: Commit**

```bash
git add src/spiresight/core/run_state.py tests/test_run_state.py
git commit -m "feat(core): add RunState model with prompt-block formatter"
```

---

## Task 2: Qt-aware RunStateStore (`ui/state/run_state_store.py`)

**Files:**
- Create: `src/spiresight/ui/state/__init__.py`
- Create: `src/spiresight/ui/state/run_state_store.py`
- Test: `tests/test_run_state_store.py`

- [ ] **Step 2.1: Write the failing tests**

Create `tests/test_run_state_store.py`:

```python
from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QCoreApplication

from spiresight.core.run_state import RunState, Card
from spiresight.ui.state.run_state_store import RunStateStore


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def _sample() -> RunState:
    return RunState(
        cards=[Card(name="Strike", count=4, rarity="starter", usefulness="skip")],
        relics=[], potions=[], archetype_candidates=[],
        overall_eval="", inspected_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
    )


def test_initial_state_is_none(qapp):
    store = RunStateStore()
    assert store.get() is None


def test_set_then_get(qapp):
    store = RunStateStore()
    state = _sample()
    store.set(state)
    assert store.get() == state


def test_clear_resets_to_none(qapp):
    store = RunStateStore()
    store.set(_sample())
    store.clear()
    assert store.get() is None


def test_changed_signal_emits_on_set(qapp):
    store = RunStateStore()
    emissions: list[RunState | None] = []
    store.changed.connect(lambda s: emissions.append(s))
    state = _sample()
    store.set(state)
    assert emissions == [state]


def test_changed_signal_emits_on_clear(qapp):
    store = RunStateStore()
    store.set(_sample())
    emissions: list[RunState | None] = []
    store.changed.connect(lambda s: emissions.append(s))
    store.clear()
    assert emissions == [None]
```

- [ ] **Step 2.2: Run the tests — should fail with ImportError**

Run: `.venv/bin/pytest tests/test_run_state_store.py -v`
Expected: ImportError.

- [ ] **Step 2.3: Create package marker**

Create `src/spiresight/ui/state/__init__.py` as an empty file.

- [ ] **Step 2.4: Create the store**

Create `src/spiresight/ui/state/run_state_store.py`:

```python
"""Qt-aware holder for the current RunState.

Single instance, owned by MainWindow. Emits `changed(state | None)`
on every mutation so UI widgets (and any other observer) can refresh.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from spiresight.core.run_state import RunState


class RunStateStore(QObject):
    changed = Signal(object)  # RunState | None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state: RunState | None = None

    def get(self) -> RunState | None:
        return self._state

    def set(self, state: RunState) -> None:
        self._state = state
        self.changed.emit(state)

    def clear(self) -> None:
        self._state = None
        self.changed.emit(None)
```

- [ ] **Step 2.5: Run the tests — all should pass**

Run: `.venv/bin/pytest tests/test_run_state_store.py -v`
Expected: 5 passed.

- [ ] **Step 2.6: Commit**

```bash
git add src/spiresight/ui/state/__init__.py src/spiresight/ui/state/run_state_store.py tests/test_run_state_store.py
git commit -m "feat(ui): add RunStateStore with changed signal"
```

---

## Task 3: Provider protocol — `json_mode` kwarg

**Files:**
- Modify: `src/spiresight/llm/provider.py`
- Modify: `src/spiresight/llm/providers/openai_provider.py`
- Modify: `src/spiresight/llm/providers/anthropic_provider.py`
- Modify: `src/spiresight/llm/providers/gemini_provider.py`
- Modify: `tests/test_openai_provider.py`
- Modify: `tests/test_provider_stubs.py`
- Modify: `tests/test_inference_runner.py` (the `_FakeProvider.stream` signature)

- [ ] **Step 3.1: Write the failing test for OpenAI JSON mode**

Append to `tests/test_openai_provider.py`:

```python
@respx.mock
def test_stream_with_json_mode_sets_response_format():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse('{"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}]}'),
        )
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-test"))
    list(p.stream(
        model="gpt-4o", system="sys", user_text="hi",
        image_png=None, cancel_event=threading.Event(),
        json_mode=True,
    ))
    body = route.calls.last.request.content.decode()
    assert '"response_format"' in body
    assert '"json_object"' in body


@respx.mock
def test_stream_without_json_mode_omits_response_format():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse('{"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}'),
        )
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-test"))
    list(p.stream(
        model="gpt-4o", system="sys", user_text="hi",
        image_png=None, cancel_event=threading.Event(),
    ))
    body = route.calls.last.request.content.decode()
    assert "response_format" not in body
```

- [ ] **Step 3.2: Run the new tests — should fail**

Run: `.venv/bin/pytest tests/test_openai_provider.py::test_stream_with_json_mode_sets_response_format tests/test_openai_provider.py::test_stream_without_json_mode_omits_response_format -v`
Expected: FAIL — TypeError (unexpected kwarg `json_mode`).

- [ ] **Step 3.3: Update the Protocol**

In `src/spiresight/llm/provider.py`, change `stream` signature to add `json_mode`:

```python
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
```

- [ ] **Step 3.4: Update OpenAI provider**

In `src/spiresight/llm/providers/openai_provider.py`, add `json_mode: bool = False` to `stream` signature, then conditionally set the payload:

```python
def stream(
    self,
    *,
    model: str,
    system: str,
    user_text: str,
    image_png: bytes | None,
    cancel_event: threading.Event,
    json_mode: bool = False,
) -> Iterator[StreamChunk]:
    if not self._config.api_key:
        raise MissingAPIKey(self.name)

    base_url = (self._config.base_url or _DEFAULT_BASE).rstrip("/")
    url = f"{base_url}/chat/completions"
    payload: dict = {
        "model": model,
        "stream": True,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": self._build_user_content(user_text, image_png)},
        ],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    # …rest unchanged
```

- [ ] **Step 3.5: Update stub providers**

In both `anthropic_provider.py` and `gemini_provider.py`, add `json_mode: bool = False,` to the `stream` signature (the body still just raises `NotImplementedError`).

- [ ] **Step 3.6: Update existing fake-provider tests**

In `tests/test_inference_runner.py`, update `_FakeProvider.stream` to accept the new kwarg:

```python
def stream(self, *, model, system, user_text, image_png, cancel_event, json_mode=False):
    self.last_call = dict(model=model, system=system, user_text=user_text,
                          image_png=image_png, json_mode=json_mode)
    yield from self._chunks
```

In `tests/test_provider_stubs.py`, update the call to pass `json_mode=False` explicitly:

```python
list(p.stream(
    model="x", system="s", user_text="u",
    image_png=None, cancel_event=threading.Event(),
    json_mode=False,
))
```

- [ ] **Step 3.7: Run the full provider + runner test suite — all pass**

Run: `.venv/bin/pytest tests/test_openai_provider.py tests/test_provider_stubs.py tests/test_inference_runner.py tests/test_provider_contract.py -v`
Expected: all green.

- [ ] **Step 3.8: Commit**

```bash
git add src/spiresight/llm/provider.py src/spiresight/llm/providers tests/test_openai_provider.py tests/test_provider_stubs.py tests/test_inference_runner.py
git commit -m "feat(llm): add json_mode kwarg to provider stream"
```

---

## Task 4: Runner — inject run-state into system prompt

**Files:**
- Modify: `src/spiresight/core/runner.py`
- Modify: `tests/test_inference_runner.py`

- [ ] **Step 4.1: Write the failing test**

Append to `tests/test_inference_runner.py`:

```python
from datetime import datetime, timezone

from spiresight.core.run_state import Card, RunState
from spiresight.ui.state.run_state_store import RunStateStore


def _stateful_runner(provider, loader, capture, store):
    cfg = AppConfig(active_provider="openai", active_model="gpt-4o")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    return InferenceRunner(
        config=cfg,
        prompt_loader=loader,
        provider_factory=lambda name, pcfg: provider,
        screen_capture=capture,
        run_state_store=store,
    )


def test_run_appends_run_state_block_to_system_when_store_has_state(qapp):
    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="t {custom_text}", requires_screenshot=False,
                     required_capabilities=[])
    sp = SystemPrompt(id="s", description="", content="base prompt")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o", frozenset(), 128_000)],
        chunks=[StreamChunk("ok", "stop")],
    )
    store = RunStateStore()
    store.set(RunState(
        cards=[Card(name="Heavy Blade+", count=1, rarity="uncommon", usefulness="key")],
        relics=[], potions=[], archetype_candidates=[],
        overall_eval="lean strength",
        inspected_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
    ))
    runner = _stateful_runner(provider, _FakeLoader(qa, sp), _FakeCapture(), store)
    list(runner.run(InferenceRequest("x", "", False), cancel_event=threading.Event()))
    assert provider.last_call["system"].startswith("base prompt")
    assert "## Current Run Context" in provider.last_call["system"]
    assert "Heavy Blade+" in provider.last_call["system"]
    assert "lean strength" in provider.last_call["system"]


def test_run_leaves_system_unchanged_when_store_empty(qapp):
    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="t", requires_screenshot=False,
                     required_capabilities=[])
    sp = SystemPrompt(id="s", description="", content="base prompt")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o", frozenset(), 128_000)],
        chunks=[StreamChunk("ok", "stop")],
    )
    store = RunStateStore()  # empty
    runner = _stateful_runner(provider, _FakeLoader(qa, sp), _FakeCapture(), store)
    list(runner.run(InferenceRequest("x", "", False), cancel_event=threading.Event()))
    assert provider.last_call["system"] == "base prompt"


def test_run_without_store_works_unchanged():
    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="t", requires_screenshot=False,
                     required_capabilities=[])
    sp = SystemPrompt(id="s", description="", content="base prompt")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o", frozenset(), 128_000)],
        chunks=[StreamChunk("ok", "stop")],
    )
    runner = _runner(provider=provider, loader=_FakeLoader(qa, sp))  # no store
    list(runner.run(InferenceRequest("x", "", False), cancel_event=threading.Event()))
    assert provider.last_call["system"] == "base prompt"
```

Also add a `qapp` fixture import at the top of the file (the store doesn't strictly need a QApplication for `set/get`, but having it ensures Qt is initialized for signal connections):

```python
import pytest
from PySide6.QtCore import QCoreApplication

@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app
```

- [ ] **Step 4.2: Run the tests — should fail**

Run: `.venv/bin/pytest tests/test_inference_runner.py -v`
Expected: FAIL — `InferenceRunner` doesn't accept `run_state_store`.

- [ ] **Step 4.3: Update the runner**

Edit `src/spiresight/core/runner.py`:

```python
"""Orchestrates a single inference request end-to-end.

Pure Python, no Qt. Wrapped by ui/workers/inference_worker for the
QThread-based UI integration.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from typing import Protocol

from spiresight.capture.screen import ScreenCapture
from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.core.request import InferenceRequest
from spiresight.core.run_state import RunState
from spiresight.llm.errors import MissingAPIKey, MissingCapabilityError
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import LLMProvider, StreamChunk
from spiresight.prompts.loader import PromptLoader

ProviderFactory = Callable[[str, ProviderConfig], LLMProvider]


class RunStateSource(Protocol):
    def get(self) -> RunState | None: ...


class InferenceRunner:
    def __init__(
        self,
        *,
        config: AppConfig,
        prompt_loader: PromptLoader,
        provider_factory: ProviderFactory,
        screen_capture: ScreenCapture,
        run_state_store: RunStateSource | None = None,
    ) -> None:
        self._config = config
        self._loader = prompt_loader
        self._factory = provider_factory
        self._capture = screen_capture
        self._store = run_state_store

    def run(
        self,
        request: InferenceRequest,
        *,
        cancel_event: threading.Event,
    ) -> Iterator[StreamChunk]:
        qa = self._loader.get_quick_action(request.prompt_id)
        sp = self._loader.get_system_prompt(qa.system_prompt_id)
        user_text = qa.user_template.format(custom_text=request.custom_text or "")

        provider_cfg = self._config.providers.get(
            self._config.active_provider, ProviderConfig()
        )
        if not provider_cfg.api_key:
            raise MissingAPIKey(self._config.active_provider)
        provider = self._factory(self._config.active_provider, provider_cfg)

        model = self._resolve_model(provider, self._config.active_model)
        missing = set(qa.required_capabilities) - set(model.capabilities)
        if missing:
            raise MissingCapabilityError(model=model.id, missing=missing)

        image_png: bytes | None = None
        if qa.requires_screenshot and request.include_screenshot:
            image_png = self._capture.grab_primary()

        system_prompt = self._compose_system(sp.content)

        yield from provider.stream(
            model=model.id,
            system=system_prompt,
            user_text=user_text,
            image_png=image_png,
            cancel_event=cancel_event,
        )

    def _compose_system(self, base: str) -> str:
        if self._store is None:
            return base
        state = self._store.get()
        if state is None:
            return base
        return f"{base}\n\n{state.to_prompt_block()}"

    @staticmethod
    def _resolve_model(provider: LLMProvider, model_id: str) -> ModelInfo:
        for m in provider.list_models():
            if m.id == model_id:
                return m
        raise KeyError(f"Model '{model_id}' not advertised by provider '{provider.name}'")
```

- [ ] **Step 4.4: Run tests — all should pass**

Run: `.venv/bin/pytest tests/test_inference_runner.py -v`
Expected: all green (original 4 + 3 new).

- [ ] **Step 4.5: Commit**

```bash
git add src/spiresight/core/runner.py tests/test_inference_runner.py
git commit -m "feat(core): inject RunState into system prompt when store has data"
```

---

## Task 5: Runner — `inspect()` method

**Files:**
- Modify: `src/spiresight/core/runner.py`
- Modify: `tests/test_inference_runner.py`

- [ ] **Step 5.1: Write the failing tests**

Append to `tests/test_inference_runner.py`:

```python
from spiresight.llm.capabilities import Capability as Cap


def _inspect_provider(*, models, chunks):
    return _FakeProvider(models=models, chunks=chunks)


def test_inspect_buffers_chunks_parses_json_returns_run_state():
    sp = SystemPrompt(id="inspector", description="", content="emit JSON only")
    provider = _inspect_provider(
        models=[ModelInfo("gpt-4o", "gpt-4o",
                          frozenset({Cap.VISION, Cap.JSON_MODE}), 128_000)],
        chunks=[
            StreamChunk('{"cards":[{"name":"Strike","count":4,"rarity":"starter",'),
            StreamChunk('"usefulness":"skip","note":""}],"relics":[],"potions":[],'),
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

    state = runner.inspect(cancel_event=threading.Event())
    assert state.cards[0].name == "Strike"
    assert state.cards[0].count == 4
    assert provider.last_call["json_mode"] is True
    assert provider.last_call["image_png"] == b"PNG_BYTES"
    assert provider.last_call["system"] == "emit JSON only"


def test_inspect_raises_value_error_on_malformed_json():
    sp = SystemPrompt(id="inspector", description="", content="json please")
    provider = _inspect_provider(
        models=[ModelInfo("gpt-4o", "gpt-4o",
                          frozenset({Cap.VISION, Cap.JSON_MODE}), 128_000)],
        chunks=[StreamChunk("not json at all", "stop")],
    )

    class _StaticLoader:
        def get_system_prompt(self, _): return sp

    cfg = AppConfig(active_provider="openai", active_model="gpt-4o")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    runner = InferenceRunner(
        config=cfg, prompt_loader=_StaticLoader(),
        provider_factory=lambda n, p: provider, screen_capture=_FakeCapture(),
    )

    with pytest.raises(ValueError):
        runner.inspect(cancel_event=threading.Event())


def test_inspect_raises_missing_capability_when_model_lacks_json_mode():
    sp = SystemPrompt(id="inspector", description="", content="json")
    provider = _inspect_provider(
        models=[ModelInfo("o3", "o3",
                          frozenset({Cap.VISION}), 200_000)],  # no JSON_MODE
        chunks=[],
    )

    class _StaticLoader:
        def get_system_prompt(self, _): return sp

    cfg = AppConfig(active_provider="openai", active_model="o3")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    runner = InferenceRunner(
        config=cfg, prompt_loader=_StaticLoader(),
        provider_factory=lambda n, p: provider, screen_capture=_FakeCapture(),
    )

    with pytest.raises(MissingCapabilityError) as exc:
        runner.inspect(cancel_event=threading.Event())
    assert Cap.JSON_MODE in exc.value.missing
    assert Cap.VISION not in exc.value.missing  # model has VISION
```

- [ ] **Step 5.2: Run the new tests — should fail**

Run: `.venv/bin/pytest tests/test_inference_runner.py -k inspect -v`
Expected: FAIL — `InferenceRunner` has no `inspect` attribute.

- [ ] **Step 5.3: Add the `inspect()` method**

Add to `src/spiresight/core/runner.py`. First, add module-level constants and import:

```python
from spiresight.llm.capabilities import Capability

INSPECTOR_PROMPT_ID = "sts_inspector"
INSPECTOR_USER_TEXT = (
    "Extract the current run state from this screenshot. "
    "Output JSON only, matching the schema specified in the system prompt."
)
_INSPECT_CAPS = frozenset({Capability.VISION, Capability.JSON_MODE})
```

Then add the method to `InferenceRunner`:

```python
def inspect(self, *, cancel_event: threading.Event) -> RunState:
    """Capture a fresh screenshot, ask the inspector prompt for JSON,
    parse it into a RunState. Always full-rebuild (does not inject the
    current run-state into its own prompt).

    Raises:
        MissingAPIKey: if the active provider has no key.
        MissingCapabilityError: if the active model lacks VISION or JSON_MODE.
        ValueError: if the model's response is not valid RunState JSON.
        LLMError: passed through from the provider.
    """
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

    image_png = self._capture.grab_primary()

    buffer: list[str] = []
    for chunk in provider.stream(
        model=model.id,
        system=sp.content,
        user_text=INSPECTOR_USER_TEXT,
        image_png=image_png,
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

- [ ] **Step 5.4: Run tests — all should pass**

Run: `.venv/bin/pytest tests/test_inference_runner.py -v`
Expected: all green.

- [ ] **Step 5.5: Commit**

```bash
git add src/spiresight/core/runner.py tests/test_inference_runner.py
git commit -m "feat(core): add InferenceRunner.inspect() for JSON state capture"
```

---

## Task 6: Inspector system prompt + sts_expert hint

**Files:**
- Modify: `prompts/system_prompts.yaml`
- Modify: `tests/test_default_prompts.py` (or `tests/test_prompt_loader.py` — pick whichever already exercises the YAML)

- [ ] **Step 6.1: Inspect existing test file to find the right one**

Run: `grep -l "sts_expert\|system_prompts" tests/*.py`

The existing test that lists system prompts is the one to extend. Add a test asserting `sts_inspector` exists and has expected content fragments.

- [ ] **Step 6.2: Write the failing test**

Add to whichever file matched (most likely `tests/test_default_prompts.py`):

```python
def test_sts_inspector_prompt_present_and_demands_json():
    loader = PromptLoader(Path(__file__).resolve().parents[1] / "prompts")
    loader.reload(language="en")
    sp = loader.get_system_prompt("sts_inspector")
    assert "JSON" in sp.content
    assert "cards" in sp.content
    assert "archetype_candidates" in sp.content


def test_sts_expert_mentions_run_context():
    loader = PromptLoader(Path(__file__).resolve().parents[1] / "prompts")
    loader.reload(language="en")
    sp = loader.get_system_prompt("sts_expert")
    assert "Current Run Context" in sp.content
```

(Adjust imports to match the file's existing pattern.)

- [ ] **Step 6.3: Run the tests — should fail**

Run: `.venv/bin/pytest tests/test_default_prompts.py -v`
Expected: FAIL — `sts_inspector` not in YAML.

- [ ] **Step 6.4: Update `prompts/system_prompts.yaml`**

Replace the file contents with:

```yaml
# prompts/system_prompts.yaml
- id: sts_expert
  description: General Slay the Spire II strategist
  content: |
    You are an expert Slay the Spire II strategist. You analyze game
    screenshots and provide concise, actionable advice.

    Conventions:
    - Lead with the recommendation in one sentence.
    - Justify in <= 3 bullet points.
    - Call out risks explicitly.
    - When uncertain, say so.

    Priorities, in order: immediate threats, long-run deck health,
    energy/economy curves.

    If a "## Current Run Context" section is appended below, use it to
    bias your advice toward the player's existing archetype direction
    and known deck contents. Do not contradict it unless the
    screenshot proves the context stale.

- id: sts_inspector
  description: Extracts current run state into strict JSON
  content: |
    You are a Slay the Spire II run-state extractor. Look at the
    screenshot and output a single JSON object matching this schema:

    {
      "cards":  [{"name": str, "count": int, "rarity": str,
                  "usefulness": str, "note": str}],
      "relics": [{"name": str, "synergy_tags": [str]}],
      "potions": [str],
      "archetype_candidates":
                [{"name": str, "confidence": str, "rationale": str}],
      "overall_eval": str,
      "inspected_at": "ISO-8601 timestamp"
    }

    Rules:
    - rarity ∈ {"starter", "common", "uncommon", "rare"}.
    - usefulness ∈ {"skip", "situational", "good", "key"}. Judge each
      card in the context of the candidate archetypes, not in absolute
      terms.
    - confidence ∈ {"low", "medium", "high"}.
    - archetype_candidates: 1–3 entries, highest confidence first.
    - overall_eval: 2–3 sentences. Diagnosis only — no advice.
    - "note" is one short sentence or "".
    - Output JSON only, no prose, no markdown fence.
```

- [ ] **Step 6.5: Run tests — all should pass**

Run: `.venv/bin/pytest tests/test_default_prompts.py tests/test_prompt_loader.py -v`
Expected: all green.

- [ ] **Step 6.6: Commit**

```bash
git add prompts/system_prompts.yaml tests/test_default_prompts.py
git commit -m "feat(prompts): add sts_inspector prompt, teach sts_expert to use run context"
```

---

## Task 7: InspectWorker (QThread wrapper for `runner.inspect()`)

**Files:**
- Create: `src/spiresight/ui/workers/inspect_worker.py`

No standalone unit tests for this — it's a thin wrapper. Coverage comes from manual smoke (Task 10) and from the runner tests in Task 5.

- [ ] **Step 7.1: Create the worker**

Create `src/spiresight/ui/workers/inspect_worker.py`:

```python
"""QThread wrapping InferenceRunner.inspect().

Buffers the entire response (the inspect call is not streamed to the
UI — it returns a parsed RunState all at once). Emits either
`ready(state)` or `failed(exception)`.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from spiresight.core.run_state import RunState
from spiresight.core.runner import InferenceRunner


class InspectWorker(QThread):
    ready = Signal(object)   # RunState
    failed = Signal(object)  # Exception

    def __init__(self, runner: InferenceRunner, parent=None) -> None:
        super().__init__(parent)
        self._runner = runner
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            state: RunState = self._runner.inspect(cancel_event=self._cancel)
            self.ready.emit(state)
        except Exception as exc:  # noqa: BLE001 — UI renders all errors
            self.failed.emit(exc)
```

- [ ] **Step 7.2: Smoke-import verification**

Run: `.venv/bin/python -c "from spiresight.ui.workers.inspect_worker import InspectWorker; print('ok')"`
Expected: `ok`.

- [ ] **Step 7.3: Commit**

```bash
git add src/spiresight/ui/workers/inspect_worker.py
git commit -m "feat(ui): add InspectWorker for buffered inspect calls"
```

---

## Task 8: RunStatePanel widget

**Files:**
- Create: `src/spiresight/ui/widgets/run_state_panel.py`

- [ ] **Step 8.1: Create the panel**

Create `src/spiresight/ui/widgets/run_state_panel.py`:

```python
"""Sidebar panel showing the current RunState with Inspect / Clear actions.

The widget is a passive observer of `RunStateStore`: it re-renders on
every `changed` emission. Inspect/Clear button clicks emit signals the
MainWindow wires to its InspectWorker and store.clear() respectively.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from spiresight.core.run_state import RunState
from spiresight.ui.state.run_state_store import RunStateStore

_USEFULNESS_COLORS = {
    "key":         "#d4a54a",  # tarnished gold
    "good":        "#6bb5e8",  # crystal blue
    "situational": "#d5cebf",  # parchment
    "skip":        "#6e7a89",  # muted
}

_RARITY_GLYPHS = {
    "starter":  "○",
    "common":   "●",
    "uncommon": "◆",
    "rare":     "◆",
}


class RunStatePanel(QWidget):
    inspect_requested = Signal()
    clear_requested = Signal()

    def __init__(self, store: RunStateStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        header = QLabel("Run State")
        header.setProperty("role", "section-header")
        outer.addWidget(header)

        button_row = QHBoxLayout()
        self._inspect_btn = QPushButton("Inspect Now")
        self._inspect_btn.setObjectName("primary")
        self._inspect_btn.clicked.connect(self.inspect_requested.emit)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self.clear_requested.emit)
        button_row.addWidget(self._inspect_btn)
        button_row.addWidget(self._clear_btn)
        outer.addLayout(button_row)

        # Scrollable content area — long decks need scrolling.
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
        self._render(store.get())

    # ─── rendering ────────────────────────────────────────────────

    def set_inspect_enabled(self, enabled: bool, tooltip: str = "") -> None:
        self._inspect_btn.setEnabled(enabled)
        self._inspect_btn.setToolTip(tooltip)

    def _clear_content(self) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render(self, state: RunState | None) -> None:
        self._clear_content()
        if state is None:
            empty = QLabel("Click Inspect Now to capture your current run.")
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
            # render in usefulness order: key → good → situational → skip
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

- [ ] **Step 8.2: Smoke-import verification**

Run: `.venv/bin/python -c "from spiresight.ui.widgets.run_state_panel import RunStatePanel; print('ok')"`
Expected: `ok`.

- [ ] **Step 8.3: Commit**

```bash
git add src/spiresight/ui/widgets/run_state_panel.py
git commit -m "feat(ui): add RunStatePanel sidebar widget"
```

---

## Task 9: Wire into MainWindow

**Files:**
- Modify: `src/spiresight/ui/windows/main_window.py`

- [ ] **Step 9.1: Add imports**

At the top of `src/spiresight/ui/windows/main_window.py`, add:

```python
from spiresight.core.run_state import RunState
from spiresight.llm.capabilities import Capability
from spiresight.ui.state.run_state_store import RunStateStore
from spiresight.ui.widgets.run_state_panel import RunStatePanel
from spiresight.ui.workers.inspect_worker import InspectWorker
```

- [ ] **Step 9.2: Resize the window and sidebar**

Change `self.resize(880, 520)` to `self.resize(980, 580)`.
Change `sidebar.setFixedWidth(240)` to `sidebar.setFixedWidth(280)`.

- [ ] **Step 9.3: Create the store before constructing the runner-using bits**

In `__init__`, after `self._capture = ScreenCapture()` add:

```python
self._run_state_store = RunStateStore(self)
self._inspect_worker: InspectWorker | None = None
```

- [ ] **Step 9.4: Mount RunStatePanel in the sidebar**

In the sidebar block (after `sb_layout.addWidget(self._prompt_panel)` and before `sb_layout.addStretch(1)`):

```python
sb_layout.addSpacing(12)
self._run_state_panel = RunStatePanel(self._run_state_store, parent=self)
self._run_state_panel.inspect_requested.connect(self._on_inspect_requested)
self._run_state_panel.clear_requested.connect(self._run_state_store.clear)
sb_layout.addWidget(self._run_state_panel, stretch=1)
```

Remove the `sb_layout.addStretch(1)` line below (the panel now provides the stretch).

- [ ] **Step 9.5: Inject store into the runner**

In `_on_action`, replace:

```python
runner = InferenceRunner(
    config=self._config,
    prompt_loader=self._loader,
    provider_factory=registry.get,
    screen_capture=self._capture,
)
```

with:

```python
runner = InferenceRunner(
    config=self._config,
    prompt_loader=self._loader,
    provider_factory=registry.get,
    screen_capture=self._capture,
    run_state_store=self._run_state_store,
)
```

- [ ] **Step 9.6: Add inspect handler + completion handlers**

Append these methods to `MainWindow` (near `_on_action` / `_on_failed`):

```python
def _on_inspect_requested(self) -> None:
    if self._inspect_worker is not None and self._inspect_worker.isRunning():
        return
    runner = InferenceRunner(
        config=self._config,
        prompt_loader=self._loader,
        provider_factory=registry.get,
        screen_capture=self._capture,
        run_state_store=self._run_state_store,
    )
    self._run_state_panel.set_inspect_enabled(False, "Inspecting…")
    self.statusBar().showMessage("Inspecting run state…")

    self._inspect_worker = InspectWorker(runner, self)
    self._inspect_worker.ready.connect(self._on_inspect_ready)
    self._inspect_worker.failed.connect(self._on_inspect_failed)
    self._inspect_worker.start()

def _on_inspect_ready(self, state: RunState) -> None:
    self._run_state_store.set(state)
    self._run_state_panel.set_inspect_enabled(True)
    self.statusBar().showMessage("Run state captured.", 3000)

def _on_inspect_failed(self, exc: Exception) -> None:
    self._run_state_panel.set_inspect_enabled(True)
    if isinstance(exc, MissingCapabilityError):
        missing = ", ".join(sorted(c.value for c in exc.missing))
        self.statusBar().showMessage(
            f"Inspect needs {missing} — switch model.", 8000)
    elif isinstance(exc, ValueError):
        self.statusBar().showMessage(
            "Inspect failed: malformed response, try again.", 8000)
    else:
        self.statusBar().showMessage(f"Inspect failed: {exc}", 8000)
```

- [ ] **Step 9.7: Disable Inspect when model lacks JSON_MODE**

Right after constructing `self._run_state_panel`, add a helper and call it on init + on picker changes:

```python
def _refresh_inspect_availability(self) -> None:
    """Disable Inspect when the active model lacks VISION + JSON_MODE."""
    try:
        provider_cfg = self._config.providers.get(self._config.active_provider)
        if provider_cfg is None:
            self._run_state_panel.set_inspect_enabled(
                False, "Configure a provider first."
            )
            return
        provider = registry.get(self._config.active_provider, provider_cfg)
        model = next(
            (m for m in provider.list_models()
             if m.id == self._config.active_model), None
        )
        if model is None:
            self._run_state_panel.set_inspect_enabled(False, "Select a model.")
            return
        needed = {Capability.VISION, Capability.JSON_MODE}
        missing = needed - set(model.capabilities)
        if missing:
            names = ", ".join(sorted(c.value for c in missing))
            self._run_state_panel.set_inspect_enabled(
                False, f"Active model lacks {names}."
            )
        else:
            self._run_state_panel.set_inspect_enabled(True)
    except Exception:  # noqa: BLE001 — best effort, fall back to enabled
        self._run_state_panel.set_inspect_enabled(True)
```

Call `self._refresh_inspect_availability()` at the end of `__init__` and at the end of `_on_picker_changed`.

- [ ] **Step 9.8: Run the full test suite to make sure nothing broke**

Run: `.venv/bin/pytest -v`
Expected: all green.

- [ ] **Step 9.9: Smoke-launch the app**

Run: `.venv/bin/python -m spiresight`
Expected: app starts, sidebar shows the new *Run State* section with "Click Inspect Now to capture your current run." Click *Clear* — no error (state was already empty). Inspect button enabled iff active model has VISION+JSON_MODE.

- [ ] **Step 9.10: Commit**

```bash
git add src/spiresight/ui/windows/main_window.py
git commit -m "feat(ui): mount RunStatePanel, wire Inspect/Clear and state injection"
```

---

## Task 10: End-to-end smoke + cleanup

**Files:** none changed unless smoke surfaces a bug.

- [ ] **Step 10.1: Manual smoke test with real API**

With OpenAI API key set:

1. Launch app: `.venv/bin/python -m spiresight`
2. Switch active model to `gpt-4o` (has VISION + JSON_MODE).
3. Take a STS screenshot (or any game-like image works for shape) on screen.
4. Click *Inspect Now*.
5. Verify: panel populates with cards/archetype/eval; status bar says "Run state captured."
6. Trigger any quick-action (e.g., Card Selection Guide). Open the LLM response and verify the model references the captured archetype/cards.
7. Click *Clear*. Verify the panel returns to empty state and subsequent quick-actions no longer mention the run context.
8. Switch active model to `o3` (no JSON_MODE). Verify Inspect button is disabled with tooltip "Active model lacks json_mode."

- [ ] **Step 10.2: Run the full test suite one more time**

Run: `.venv/bin/pytest -v`
Expected: all green.

- [ ] **Step 10.3: Run mypy / lint if configured**

Run: `.venv/bin/ruff check src tests 2>/dev/null || true; .venv/bin/mypy src 2>/dev/null || true`
Fix any errors introduced by this change. (If neither tool is wired up, skip.)

- [ ] **Step 10.4: Final commit if any cleanup was needed**

```bash
git add -A
git commit -m "chore: smoke-test cleanup for run-state memory"
```

---

## Notes for the Implementer

- **`MainWindow._on_action` already builds a fresh `InferenceRunner` per call.** That pattern is preserved — the store is injected into each new runner. Don't try to keep a long-lived runner.
- **The store lives on `MainWindow` for the app's lifetime.** When `MainWindow` is destroyed, Qt cleans it up via the parent-child relationship.
- **`store.changed` always emits, even on `set()` with an identical state.** That's intentional — the panel is the only consumer and re-rendering identical state is cheap.
- **The inspector prompt asks for raw JSON** (no markdown fence). OpenAI's `response_format=json_object` guarantees the response is parseable; we still defensively `.strip()` before parsing.
- **`required_capabilities` for the inspect path is hardcoded in `runner.py`**, not in YAML. The inspect call is not a `quick_action`; only `quick_action`s use the YAML capability list.
- **The mini-bar is intentionally untouched.** State display is desktop-only for now (see spec "Out of Scope").
