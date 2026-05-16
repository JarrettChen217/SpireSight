# Multi-Frame Capture for Run-State Inspect

**Status:** Design
**Date:** 2026-05-16
**Branch:** `main`
**Builds on:** `2026-05-16-prompt-run-state-design.md` (shipped, commits
`0228110`..`d4c00c6`)

## Problem

The shipped Inspect flow captures a single screenshot. Slay the Spire II's
deck-view screen is scrollable: once a deck grows past ~10 cards, a single
frame cannot show the full hand. Today the user either gets a partial
snapshot (missing the off-screen cards) or has to scroll back and re-Inspect
(losing the previous snapshot's data).

We want the user to be able to scroll through the deck, capture multiple
frames, and have the LLM produce a single, complete `RunState` from all of
them in one call.

## Scope

- **Multi-frame capture session** for the Inspect path only. The Inspect
  button is replaced with a `Capture` / `Done` / `Clear` flow: press
  `Capture` for each visible portion of the deck, then `Done` to send the
  whole batch to the LLM.
- **Quick-action flow is unchanged.** `InferenceRunner.run()` still takes
  one screenshot per call. Multi-image is an inspect-only concept.
- **Hard cap of 6 frames per session.** Covers a 30+ card deck at ~6
  visible cards per scroll page. Capture button disables at the cap.
- **No on-disk persistence.** Frames live in memory in an `InspectSession`
  alongside the existing `RunStateStore`.
- **Provider interface upgrade.** `LLMProvider.stream()` takes
  `images: list[bytes]` instead of `image_png: bytes | None`. Empty list
  means "no image". This is a mechanical migration across the protocol,
  three provider implementations, the runner, and the test doubles.

Explicit non-goals (carried from the prior spec):
- Persisting frames or RunState across app restart.
- In-app image stitching (would require feature-matching across frames;
  out of scope and unnecessary if the LLM accepts N images directly).
- Incremental merging into a prior RunState. `Done` always produces a
  fresh `RunState` and replaces whatever was in the store.

## Architecture

Four edits to the shipped run-state machinery:

1. **New: `core/inspect_session.py`** — an in-memory buffer holding the
   PNG bytes for the current session, with a Qt `changed` signal so the
   panel can refresh thumbnails.
2. **`llm/provider.py` + three providers + call sites** — rename
   `image_png: bytes | None` to `images: list[bytes]`. OpenAI builds N
   `image_url` content parts when the list is non-empty; the stub
   providers (Anthropic, Gemini) keep their `NotImplementedError`
   bodies but match the new signature.
3. **`core/runner.py::inspect()`** — signature becomes
   `inspect(*, images: list[bytes], cancel_event) -> RunState`. The
   runner no longer calls `screen_capture.grab_primary()` itself; the
   caller (the worker) supplies the buffered frames. `run()` still
   captures internally — unchanged.
4. **`ui/widgets/run_state_panel.py`** — button row becomes
   `[Capture] [Done] [Clear]`; new horizontally-scrollable thumbnail
   strip above the buttons; thumbnails carry a `×` to remove individual
   frames before sending.

Plus:
- **`ui/workers/inspect_worker.py`** — accepts `frames: list[bytes]` in
  its constructor and passes them through to `runner.inspect()`.
- **`prompts/system_prompts.yaml::sts_inspector`** — adds one paragraph
  explaining that 1–N screenshots may be supplied and that overlap is
  expected.
- **`ui/windows/main_window.py`** — instantiates the `InspectSession`,
  passes it to the panel, wires the new signal handlers.

## Data Model

```python
# core/inspect_session.py

class InspectSession(QObject):
    """In-memory buffer of captured PNG frames for one Inspect batch."""

    changed = Signal()                   # emitted after any add/remove/clear
    MAX_FRAMES = 6

    def __init__(self, parent: QObject | None = None) -> None: ...

    def add_frame(self, png: bytes) -> None:
        """Append a frame. Raises RuntimeError if MAX_FRAMES reached."""

    def remove_frame(self, index: int) -> None: ...

    def clear(self) -> None: ...

    @property
    def frames(self) -> list[bytes]: ...     # returns a defensive copy

    @property
    def count(self) -> int: ...
```

Lifecycle: one instance, created in `MainWindow.__init__`, lives as long
as the window. Not persisted, not multi-session — the user is expected
to be inspecting one deck at a time.

## Capture Flow

1. User opens the in-game deck view, scrolls to the top.
2. Presses **Capture** → panel emits `capture_requested`. Main_window
   handles it: calls `screen_capture.grab_primary()` inline on the UI
   thread (one grab is fast — sub-100ms — and a worker per click is
   overkill), then `session.add_frame(png)`. Session emits `changed`,
   panel re-renders the thumbnail strip.
3. User scrolls, presses **Capture** again. Repeat up to
   `MAX_FRAMES = 6`. At the cap, the Capture button disables with
   tooltip `"Maximum 6 frames per session."`.
4. User may click `×` on any thumbnail to remove a bad frame from the
   buffer (panel handles this internally via `session.remove_frame(i)`).
5. Presses **Done** (enabled only when `session.count >= 1`) → panel
   emits `done_requested`. Main_window spawns
   `InspectWorker(runner, frames=session.frames)`, calls
   `panel.set_busy(True)`.
6. Worker calls `runner.inspect(images=frames, cancel_event=...)`,
   which sends one LLM call with N image content parts. Buffers the
   response, parses into `RunState`, emits `ready(state)`.
7. On `ready`: `store.set(state)` (panel updates via existing
   `RunStateStore.changed` path), then `session.clear()` (thumbnails
   disappear, buffer empty), `panel.set_busy(False)`.
8. On `failed`: status-bar shows `"Inspect failed: <message>"`, the
   session buffer is **preserved** so the user can retry without
   recapturing, `panel.set_busy(False)`.

**Clear** wipes both the `InspectSession` buffer **and** the
`RunStateStore` state. One button, one mental model: "reset the panel."
Implemented as: panel emits `clear_requested`; main_window calls
`session.clear()` then `store.clear()`.

**Capability gate.** Main_window calls `panel.set_capture_enabled(bool,
tooltip)` when the active model lacks VISION+JSON_MODE; this disables
both Capture and Done with the supplied tooltip. The busy state
(`set_busy(True)` during inference) is independent and additive — it
disables Capture/Done with the `"Analyzing…"` tooltip regardless of
capability state.

## Panel API

```python
class RunStatePanel(QWidget):
    # Signals
    capture_requested = Signal()             # user clicked Capture
    done_requested    = Signal()             # user clicked Done (count >= 1)
    clear_requested   = Signal()             # user clicked Clear

    # Slots / control API (called by main_window)
    def set_capture_enabled(self, enabled: bool, tooltip: str = "") -> None:
        """Capability gate. Disables both Capture and Done."""

    def set_busy(self, busy: bool) -> None:
        """Inference in flight. Disables Capture+Done, swaps Done label
        to 'Analyzing…'. Re-enables based on capability + session state
        when set_busy(False) is called."""
```

The shipped `inspect_requested` signal and `set_inspect_enabled` method
are **removed** — every call site moves to the new API.

## Prompt Update

`prompts/system_prompts.yaml::sts_inspector` gains one paragraph between
the schema block and the rules block:

> You will receive one or more screenshots of the deck view, possibly
> with overlap from the player scrolling. Treat them as views of the
> same deck — a card visible in multiple frames is the same card and
> must be counted exactly once. Aggregate the full deck from all frames
> before emitting the JSON.

No other prompt changes.

## Provider Interface Migration

```python
# Before
def stream(
    self, *, model: str, system: str, user_text: str,
    image_png: bytes | None,
    cancel_event: threading.Event,
    json_mode: bool = False,
) -> Iterator[StreamChunk]: ...

# After
def stream(
    self, *, model: str, system: str, user_text: str,
    images: list[bytes],            # empty list = no image
    cancel_event: threading.Event,
    json_mode: bool = False,
) -> Iterator[StreamChunk]: ...
```

OpenAI's `_build_user_content` becomes:

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

Call sites:
- `runner.run()` → `images=[image_png] if image_png else []`
- `runner.inspect()` → `images=images` (passed through from worker)
- Anthropic / Gemini stubs → signature only; still raise
  `NotImplementedError`
- Tests: mechanical rename in `tests/test_openai_provider.py`,
  `tests/test_inference_runner.py`, `tests/test_provider_stubs.py`,
  `tests/test_provider_contract.py`. The fake provider classes in
  these tests also need the new signature.

## UI: Panel Layout Delta

```
─── Run State ─────────────────────
[ thumb1 × ] [ thumb2 × ] [ thumb3 × ]   ← horizontal strip, scrollable
                                            (empty when count == 0)
[Capture]  [Done]  [Clear]

(... existing RunState rendering below, unchanged ...)
───────────────────────────────────
```

Thumbnail spec:
- Each thumbnail is 64 × 36 px (16:9 mini), `QPixmap.scaled()` with
  `KeepAspectRatio + SmoothTransformation`.
- `×` button: 12 × 12 px, top-right corner of the thumbnail, removes
  that single frame.
- Strip height: 44 px when populated, 0 px when empty (no reserved gap).
- Hover tooltip on each thumbnail: `"Frame N of {count}"`.

Done button states (in priority order, first match wins):
- Inference in flight (`set_busy(True)`): disabled, label `"Analyzing…"`,
  tooltip empty.
- Capability gate failed (`set_capture_enabled(False, t)`): disabled,
  tooltip from main_window.
- `count == 0`: disabled, tooltip `"Capture at least one frame first."`
- Otherwise: enabled, label `"Done"`.

Capture button states (in priority order, first match wins):
- Inference in flight (`set_busy(True)`): disabled, tooltip empty.
- Capability gate failed: disabled, tooltip from main_window.
- `count == MAX_FRAMES`: disabled, tooltip
  `"Maximum 6 frames per session."`
- Otherwise: enabled.

## Files Touched

New:
- `src/spiresight/core/inspect_session.py`
- `tests/test_inspect_session.py`

Modified:
- `src/spiresight/llm/provider.py` — protocol signature
- `src/spiresight/llm/providers/openai_provider.py` — signature +
  multi-image `_build_user_content`
- `src/spiresight/llm/providers/anthropic_provider.py` — signature only
- `src/spiresight/llm/providers/gemini_provider.py` — signature only
- `src/spiresight/core/runner.py` — `inspect()` signature + `run()`
  call-site adapter
- `src/spiresight/ui/workers/inspect_worker.py` — accept `frames` arg
- `src/spiresight/ui/widgets/run_state_panel.py` — button row,
  thumbnail strip, signal wiring
- `src/spiresight/ui/windows/main_window.py` — instantiate
  `InspectSession`, wire Capture/Done/Clear handlers
- `prompts/system_prompts.yaml` — sts_inspector multi-image paragraph
- `tests/test_openai_provider.py` — `image_png=` → `images=`
- `tests/test_inference_runner.py` — fake provider signature, runner
  inspect-path test now passes `images=[b"..."]`
- `tests/test_provider_stubs.py` — signature update
- `tests/test_provider_contract.py` — fake provider signature

## Testing

`tests/test_inspect_session.py`:
- `add_frame` appends; `frames` returns a list (defensive copy — mutating
  the returned list does not affect the session).
- `MAX_FRAMES` cap: 7th `add_frame` raises `RuntimeError`.
- `remove_frame(i)` removes the i-th frame; out-of-range raises
  `IndexError`.
- `clear` empties the buffer.
- `changed` signal emits exactly once per `add_frame` / `remove_frame` /
  `clear`.

Extend `tests/test_inference_runner.py`:
- `inspect()` with `images=[b"a"]` calls provider once with that single
  image.
- `inspect()` with `images=[b"a", b"b", b"c"]` calls provider once with
  all three images.
- `inspect()` with `images=[]` raises `ValueError("inspect requires at
  least one frame")` before touching the provider.

Extend `tests/test_openai_provider.py`:
- `_build_user_content` with 0 images returns the plain text string.
- With 1 image returns `[text_part, image_part]`.
- With 3 images returns `[text_part, img, img, img]` (order preserved).

Existing tests: mechanically updated for the renamed kwarg. No behavior
change.

UI panel rendering (thumbnail strip, button states): manual smoke test
only — pixel assertions are low ROI.

## Out of Scope

- Persisting frames or `RunState` across app restart.
- In-app image stitching.
- Long-press / hold-to-capture-burst.
- Drag-to-reorder thumbnails (order doesn't matter — the LLM merges).
- Multi-session history (comparing two Inspects).
- Removing one image_png call site by routing everything through a
  shared content-builder helper. The mechanical rename suffices.
