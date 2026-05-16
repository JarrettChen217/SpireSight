# Run-State Memory for SpireSight Prompts

**Status:** Design
**Date:** 2026-05-16
**Branch:** `spiresight-v1.2-prompt`

## Problem

Today every LLM call is stateless: `InferenceRunner.run()` sends only
`system_prompt + user_template + screenshot`. The model has no idea what
deck / relics / archetype the player is currently building, so advice
during card picks is generic ("this card is strong") rather than
contextual ("Heavy Blade fits your strength build — take it over
Pommel Strike").

We need a lightweight **per-run memory** that:

- Captures the current deck + relics + archetype direction as
  structured data (not free text — text bloats).
- Is updated on demand via an explicit user action (no auto-write
  during normal calls → no error propagation).
- Is injected into every subsequent `quick_action` so the model
  reasons in context.
- Is visible in the UI so the player can sanity-check it.

## Scope

- Run-state contains **cards, relics, potions, archetype candidates,
  overall evaluation**. HP / gold / floor are intentionally out — the
  screenshot already conveys them per-call.
- Lifecycle is **per-run, manual** — user presses *Inspect Now* to
  build/rebuild; *Clear* to discard. Not persisted to disk; lost on
  app exit.
- Updates are **full rebuilds only** (option A from Q3). No
  incremental patching on card picks.

## Architecture

Three additions:

1. **`core/run_state.py`** — Pydantic schema + in-memory store.
2. **`prompts/system_prompts.yaml`** — new `sts_inspector` prompt that
   instructs the LLM to emit strict JSON; existing `sts_expert`
   updated to consume an optional "Current Run Context" appendix.
3. **`ui/widgets/run_state_panel.py`** — sidebar widget rendering the
   current state plus *Inspect Now* / *Clear* buttons.

Plus targeted edits:

- `core/runner.py` — accept a `RunStateStore`; append the formatted
  state block to `system` when non-empty.
- A new code path for the inspect call (does **not** stream into
  `OutputView`; buffers the full response and parses it).
- `windows/main_window.py` — wire the store, mount the panel, widen
  the layout slightly.

## Data Model

```python
# core/run_state.py
class Card(BaseModel):
    name: str
    count: int = 1
    rarity: Literal["starter", "common", "uncommon", "rare"]
    usefulness: Literal["skip", "situational", "good", "key"]
    note: str = ""           # ≤ one sentence

class Relic(BaseModel):
    name: str
    synergy_tags: list[str]  # e.g. ["strength", "exhaust"]

class ArchetypeCandidate(BaseModel):
    name: str                # "Strength" / "Exhaust" / "Poison" / ...
    confidence: Literal["low", "medium", "high"]
    rationale: str           # ≤ one sentence

class RunState(BaseModel):
    cards: list[Card]
    relics: list[Relic]
    potions: list[str]
    archetype_candidates: list[ArchetypeCandidate]
    overall_eval: str        # 2–3 sentences
    inspected_at: datetime

    def to_prompt_block(self) -> str: ...
```

`RunStateStore` (separate class in the same module):

- Holds `Optional[RunState]`.
- API: `get() / set(state) / clear()`.
- Emits a Qt `changed` signal so `RunStatePanel` can subscribe.
- Single instance, created in `MainWindow.__init__`, passed to
  `InferenceRunner` and `RunStatePanel`.

## Inspect Flow

1. User clicks **Inspect Now** in `RunStatePanel`.
2. Panel calls a new `InferenceRunner.inspect()` method (separate from
   `run()` because the response isn't markdown for display).
3. Runner builds the request with:
   - `system` = `sts_inspector` prompt (strict JSON instructions).
   - `user_text` = "Extract the current run state from this
     screenshot."
   - Screenshot required; `json_mode` requested when the model
     supports it.
4. Provider returns a stream; runner buffers all chunks into a single
   string.
5. `RunState.model_validate_json(buffered)` produces the state object.
6. `store.set(state)` → panel auto-refreshes via the `changed` signal.
7. On parse failure: status bar shows
   *"Inspect failed: malformed response, try again."* Existing state
   in the store is preserved.

**Capability gate:** the inspect path requires
`required_capabilities = [VISION, JSON_MODE]`. If the active model
lacks JSON mode, the *Inspect Now* button is disabled with a tooltip
explaining why (mirrors the existing `MissingCapabilityError` modal
pattern).

The inspect call itself does **not** inject the prior run state — it
always rebuilds from scratch.

## Prompt Injection for Quick Actions

In `InferenceRunner.run()`:

```python
sp_content = sp.content
state = self._store.get()
if state is not None:
    sp_content = f"{sp.content}\n\n{state.to_prompt_block()}"
```

`to_prompt_block()` returns a compact natural-language summary, not
raw JSON, to save tokens. Example:

```
## Current Run Context
Archetype: Strength (high) / Exhaust (low)
Key cards: Heavy Blade x1, Inflame+ x1, Pommel Strike x2
Filler: Strike x4, Defend x4
Relics: Akabeko (strength), Vajra (strength)
Eval: Strong strength curve, next pick should prioritize scaling.
```

Applies to **all** quick actions (Q5/A). No per-action opt-out — if
the user has a current state, every call sees it.

The `sts_expert` system prompt gains one line:

> If a *Current Run Context* section is appended, use it to bias your
> advice; do not contradict it unless the screenshot proves it stale.

## `sts_inspector` Prompt (Sketch)

```
You are a Slay the Spire II run-state extractor. Look at the
screenshot and output a JSON object matching this schema:

{
  "cards":  [{"name", "count", "rarity", "usefulness", "note"}],
  "relics": [{"name", "synergy_tags"}],
  "potions":[string],
  "archetype_candidates":
            [{"name", "confidence", "rationale"}],
  "overall_eval": string,
  "inspected_at": ISO-8601 timestamp
}

Rules:
- usefulness ∈ {skip, situational, good, key}; judge in the
  context of the candidate archetypes, not in absolute terms.
- rarity ∈ {starter, common, uncommon, rare}.
- archetype_candidates: 1–3 entries, highest confidence first.
- overall_eval: 2–3 sentences. No advice — just diagnosis.
- Output JSON only, no prose, no markdown fence.
```

## UI: `RunStatePanel`

Mounted in the sidebar, below `PromptPanel`, above the stretch.

Layout:

```
─── Run State ─────────────────────
[Inspect Now]  [Clear]

Archetype
  ● Strength   (high)
  ● Exhaust    (low)

Cards (12)
  ◆ Heavy Blade+      key
  ◆ Inflame+          key
  ● Pommel Strike x2  good
  ○ Strike x4         skip
  ○ Defend x4         skip

Relics
  Akabeko · Vajra

Eval
  Strong strength curve. Next pick
  should prioritize scaling.
───────────────────────────────────
```

Color coding (re-uses the Arcane Tome palette):

| Usefulness   | Color                |
|--------------|----------------------|
| `key`        | `#d4a54a` (gold)     |
| `good`       | `#6bb5e8` (crystal)  |
| `situational`| `#d5cebf` (parchment)|
| `skip`       | `#6e7a89` (muted)    |

Rarity shown via the leading glyph (`◆` rare/uncommon, `●` common,
`○` starter) — small, doesn't dominate.

**Empty state:** "Click *Inspect Now* to capture your current run."

**Layout sizing:** widen main window 880 → 980, sidebar 240 → 280, so
card names fit on one line.

**Mini-bar:** state is not displayed in mini-bar mode (the bar is for
quick triggers, not state browsing). The bar may grow an *Inspect*
button in a future iteration; out of scope here.

## Files Touched

New:
- `src/spiresight/core/run_state.py`
- `src/spiresight/ui/widgets/run_state_panel.py`
- `tests/test_run_state.py`

Modified:
- `prompts/system_prompts.yaml` — add `sts_inspector`, tweak
  `sts_expert`.
- `src/spiresight/core/runner.py` — accept store, append prompt
  block, add `inspect()` method.
- `src/spiresight/ui/windows/main_window.py` — instantiate store,
  mount panel, widen layout, wire inspect button.
- `src/spiresight/ui/workers/inference_worker.py` — add a sibling
  worker (or a mode flag) for the buffered inspect call.

## Testing

- `test_run_state.py`:
  - `RunState.to_prompt_block()` produces the expected compact
    summary for a sample state.
  - `RunStateStore` emits `changed` exactly once per `set` / `clear`.
  - `model_validate_json` round-trips through a sample inspector
    response payload.
- Extend an existing runner test: when the store has a state,
  `run()` appends the prompt block to `system`; when empty, the
  system prompt is unchanged.
- Capability gate: inspect path raises `MissingCapabilityError` when
  the active model lacks `JSON_MODE`.

UI panel rendering is left to manual smoke testing — pixel-level
assertions are low ROI here.

## Out of Scope

- Persisting run-state across app restarts.
- Incremental updates after each card pick.
- Run-state display in the mini-bar.
- Multi-run history / comparing runs.
- Per-quick-action opt-out for state injection.
