# Card Knowledge Gateway for SpireSight Prompts

**Status:** Design
**Date:** 2026-05-24
**Branch:** `codex-card-knowledge-gateway-design`

## Problem

The card selection quick action is still too dependent on the active
vision model's built-in knowledge. It can recognize an offered card name
from the screenshot but fail to connect that name to the card's current
Slay the Spire 2 behavior, especially while the game is still changing.

SpireSight needs a local, inspectable card knowledge layer that can
provide up-to-date card facts to the prompt without requiring the app to
reach the network during normal inference.

## Goals

- Improve `card_selection` accuracy by binding card names, aliases, and
  descriptions before the model writes advice.
- Keep first-version retrieval local, fast, and easy to package.
- Add a user-controlled gateway mode: `auto`, `on`, or `off`.
- Record whether knowledge was injected in request/debug metadata.
- Add a chat-side thinking trace widget that shows the current step,
  live elapsed time, and a retained total duration after completion.
- Leave clear extension points for future per-action gateway settings,
  FAISS/vector retrieval, and provider-native tool calling.

## Non-Goals

- Do not add FAISS, sentence-transformer embeddings, or a local model in
  the first version.
- Do not make the desktop app scrape wiki pages at runtime.
- Do not machine-translate all card descriptions in the first version.
- Do not build a full general tool-use protocol for every provider yet.

## Approach

Use an offline Python fetch script to generate a local card knowledge
resource. At runtime, a `CardKnowledgeStore` loads that resource and a
`KnowledgeGateway` decides whether to append a compact card facts block
to the existing quick-action system prompt.

The first gateway implementation affects only the `card_selection`
quick action. The API shape should allow later per-action policies, but
the first UI exposes one global setting.

## Offline Fetch Script

Add:

```text
tools/fetch_sts2_cards.py
```

Run it manually:

```bash
uv run python tools/fetch_sts2_cards.py --output data/sts2_cards
```

Behavior:

- Primary source: `wiki.gg` Slay the Spire 2 card pages.
- Fetch path: prefer MediaWiki API and wikitext; fall back to HTML when
  needed.
- Parsing dependencies: `httpx`, `beautifulsoup4`,
  `mwparserfromhell`.
- Secondary source: SpireWiki support is reserved behind an optional
  interface, such as `--verify-secondary`, but disabled by default.
  When enabled in a later iteration, it should record missing or
  conflicting pages as warnings instead of overwriting primary-source
  data automatically.

Outputs:

- `data/sts2_cards/cards.json`: normalized card records.
- `data/sts2_cards/metadata.json`: source name, source URLs, fetched
  time, script version, card count, and warnings.
- `data/sts2_cards/zh_aliases.yaml`: hand-maintained Chinese aliases.
  The fetch script must not overwrite this file.
- Optional `data/sts2_cards/cards.sqlite`: generated when local SQLite
  supports FTS5. Runtime must still work from JSON if the SQLite index
  is missing.

## Card Data Model

Add a Pydantic model under `src/spiresight/knowledge/`:

```python
class CardKnowledge(BaseModel):
    id: str
    name_en: str
    aliases: list[str]
    character: str | None
    rarity: str | None
    card_type: str | None
    cost: str | None
    description: str
    upgraded_description: str | None
    mechanics: list[str]
    source_name: str
    source_url: str
    fetched_at: datetime
```

English descriptions are authoritative in the first version. Chinese
support is handled through aliases so Chinese UI text or user input can
resolve to the English card record. Full Chinese card descriptions can
be added later once the source data is stable.

## Runtime Components

### `CardKnowledgeStore`

Add:

```text
src/spiresight/knowledge/card_store.py
```

Responsibilities:

- Load `cards.json`, `metadata.json`, `zh_aliases.yaml`, and optionally
  `cards.sqlite`.
- Normalize card names and aliases for lookup.
- Search by exact English name, alias, fuzzy name, and keyword/FTS.
- Return an empty result instead of raising when the index is missing or
  corrupt.

First-version retrieval order:

1. Exact match against normalized English names and aliases.
2. Fuzzy name match with `rapidfuzz`.
3. Keyword or SQLite FTS match against descriptions and mechanics.
4. Limit to the top 3-5 cards.

Prompt output should also enforce a character budget, initially around
1200-1800 characters.

### `KnowledgeGateway`

Add:

```text
src/spiresight/knowledge/gateway.py
```

Inputs:

- Quick action id.
- Gateway mode: `auto`, `on`, or `off`.
- User text and custom text.
- Current run-state, when available.
- Future candidate card names from OCR or vision extraction.

Behavior:

- `off`: never inject.
- `on`: inject for `card_selection`; if the index is missing, skip
  injection but record the missing status.
- `auto`: inject for `card_selection`; skip other quick actions.

The first `auto` behavior is deliberately simple and equivalent to
enabling the gateway for `card_selection`. The decision point remains
isolated so future actions can add their own heuristics.

Gateway output:

```python
class KnowledgeGatewayResult(BaseModel):
    injected: bool
    status: Literal["disabled", "skipped", "missing_index", "hit", "no_hits"]
    prompt_block: str
    hits: list[str]
```

Prompt block example:

```text
## Card Knowledge Context
Use these cached card facts when evaluating the offered cards. Prefer
the screenshot if it clearly shows a newer patch description.

- Abyssal Wave [Silent, uncommon, skill, cost 1]: ...
  Upgrade: ...
  Source: wiki.gg, fetched 2026-05-24
```

## Prompt Composition

`InferenceRunner.snapshot_quick_action()` currently builds the system
prompt from:

1. Base system prompt.
2. Optional current run context.

Extend that sequence to:

1. Base system prompt.
2. Optional current run context.
3. Optional card knowledge context.

The knowledge block should be appended after run-state context so the
model sees the player's deck first and the candidate card facts second.

`RequestSnapshot.params` should include:

```python
{
    "knowledge_gateway": "auto",
    "knowledge_injected": True,
    "knowledge_status": "hit",
    "knowledge_hits": ["Abyssal Wave", "Deflect", "Strike"],
}
```

If no index exists, `auto` skips silently in the user-facing flow but
records `knowledge_status="missing_index"`. In `on` mode, the request
still continues, and the UI/status/log surface should make the missing
index visible.

## Configuration And Settings UI

Add to `AppConfig`:

```python
knowledge_gateway_mode: Literal["auto", "on", "off"] = "auto"
```

Add a combo box in `SettingsDialog -> General`, near the existing image
policy setting:

- `Auto`: card selection automatically injects local card knowledge.
- `On`: card selection always tries to inject local card knowledge.
- `Off`: local card knowledge is disabled.

Future per-action configuration can evolve to:

```python
knowledge_gateway_modes: dict[str, Literal["auto", "on", "off"]]
```

The first version should not add another control to the main prompt
panel. This keeps quick actions compact and treats the gateway as a
long-lived preference.

## Thinking Trace Widget

The chat transcript should include a request trace widget for current
and completed assistant turns.

Placement:

- Inline in the chat transcript.
- Immediately after the user's message and before the assistant answer.
- Same conversation turn as the assistant output.

Collapsed running state:

- Spinner.
- Current step label.
- Live elapsed time, such as `00:03`.

Expanded state:

- Current step label.
- Live elapsed time.
- Step list with statuses: `pending`, `running`, `done`, `skipped`,
  `failed`.
- Optional detail text per step.

Interaction:

- Click collapsed row to expand.
- Click expanded strip to collapse.
- On completion, automatically collapse.
- Do not remove the widget after completion.
- Replace the spinner with a completed state and show fixed total time,
  such as `Done · 00:08`.
- If knowledge was skipped or the index was missing, keep that summary
  visible, such as `No card facts injected · 00:02`.

Trace model:

```python
@dataclass
class RequestTraceStep:
    key: str
    label: str
    status: Literal["pending", "running", "done", "skipped", "failed"]
    detail: str = ""
    elapsed_ms: int | None = None

@dataclass
class RequestTrace:
    started_at: float
    finished_at: float | None
    summary: str
    steps: tuple[RequestTraceStep, ...]
```

The trace widget should not depend on the card gateway. It will start
with knowledge-related steps but should be able to display future RAG,
tool-calling, or provider stages.

Initial quick-action steps:

1. Capture screenshot.
2. Load card knowledge index.
3. Match offered card facts.
4. Compose prompt.
5. Call model.

## Dependencies

Add runtime/project dependencies:

- `beautifulsoup4`: fetch script HTML fallback parsing.
- `mwparserfromhell`: MediaWiki wikitext parsing in the fetch script.
- `rapidfuzz`: runtime fuzzy card-name matching.

Do not add FAISS, hnswlib, sentence-transformers, or embedding model
dependencies in this version.

## Error Handling

- Missing card data directory: skip injection and record
  `missing_index`.
- Corrupt JSON or SQLite index: skip injection, log a warning, and keep
  inference working.
- Network error in fetch script: exit non-zero with a clear message and
  leave existing generated files untouched.
- Partial fetch output: write to a temporary directory or temporary
  files, then atomically replace generated files only after validation.
- Conflicting secondary-source data: record warning metadata; do not
  auto-merge.
- Prompt budget overflow: trim lower-ranked hits and then shorten long
  descriptions.

## Testing

### Fetch Script Parsing

- Use fixture wikitext/HTML for a normal card, a card with an upgraded
  description, and a card with missing optional fields.
- Do not call the real network in unit tests.
- Verify script output includes stable ids, source URLs, fetched time,
  and warnings.

### Store And Retrieval

- English exact name match.
- Chinese alias match to English card.
- Fuzzy typo match through `rapidfuzz`.
- Keyword/FTS fallback.
- Missing index returns no hits without crashing.
- Prompt block respects hit count and character budget.

### Gateway

- `off` never injects.
- `auto` injects only for `card_selection`.
- `on` for `card_selection` records `missing_index` without blocking
  inference.
- `KnowledgeGatewayResult` includes expected hits and status.

### Runner

- Quick-action snapshots append the knowledge prompt block after the
  run-state block.
- Snapshot params include gateway mode, status, injected flag, and hit
  names.
- Existing quick actions without card knowledge preserve current
  behavior.

### UI

- Settings dialog loads and saves `knowledge_gateway_mode`.
- Old config files without the new field still load with default
  `auto`.
- Conversation transcript can insert a trace widget before the assistant
  output.
- Trace widget supports collapsed, expanded, running, completed,
  skipped, and failed states.
- Completed trace remains visible with total elapsed time.

## Open Extension Points

- Replace the store backend with FAISS or another vector index while
  preserving `CardKnowledgeStore.search_cards()`.
- Add per-action gateway modes for combat, relic, and pathfinding
  actions.
- Add a provider-native tool-calling gateway once the provider
  abstraction supports tools consistently.
- Add a user-facing "refresh card data" action after the offline fetch
  path is stable.
