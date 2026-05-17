# Tabbed UI Refactor — Design

**Date:** 2026-05-17
**Status:** Approved — ready for implementation plan
**Scope:** `src/spiresight/ui/` only (plus 2 new pure-Python deps)

## 1. Goal

Restructure the main window so the right pane is a multi-tab widget,
elevate Markdown rendering quality, and present the parsed Run State
in a more reader-friendly grouped layout — without changing the
"left = inputs, right = outputs" mental model or breaking mini-bar mode.

## 2. Out of scope

The following are explicitly deferred to v2 to keep this slice small:

- Game-term badges and TIP/WARN callouts in Markdown
  (`{{card:Strike}}`, `{{relic:...}}`, `{{hp}}`, `{{energy}}` parsing).
  A no-op `_postprocess_badges(html)` hook is left in the renderer.
- Prompts library tab (browse `prompts/` as readable cards).
- History persistence to disk (current scope is in-memory only).
- Writing Logs to a file, or showing system-prompt text in the UI.
- Switching to `QWebEngineView` for rendering.

## 3. High-level layout

```
┌─ MainWindow ────────────────────────────────────────────────┐
│ ┌─ Left Sidebar (280px) ──────────────────┐ ┌─ Right Pane ─┐│
│ │ ProviderPicker                          │ │ TabBar       ││
│ │ ───────────────────                     │ │ ┌──────────┐ ││
│ │ PromptPanel  (quick actions)            │ │ │  active  │ ││
│ │ ───────────────────                     │ │ │   tab    │ ││
│ │ InspectPanel  (NEW: thumbnails +        │ │ │ content  │ ││
│ │   Capture / Done / Clear)               │ │ └──────────┘ ││
│ │                                         │ │ ┌─ Compose ─┐││
│ │                                         │ │ │ Custom 📎 │││
│ │                                         │ │ │      Send │││
│ │                                         │ │ └───────────┘││
│ └─────────────────────────────────────────┘ └──────────────┘│
└─────────────────────────────────────────────────────────────┘
```

Right-pane tabs (in this order):

`[Chat] [Run State*] [History] [Screenshot] [Logs] [Help]`

`*` is a small badge dot that appears when the tab's content updates
while it is inactive. The dot clears the next time the tab becomes
active.

The 280px left-sidebar width is unchanged. The Custom-text /
Include-screenshot / Send / Cancel controls (currently in the right
pane above the OutputView) move into a persistent **Compose dock** at
the bottom of the right pane, visible across all tabs.

## 4. Module structure

All changes are inside `src/spiresight/ui/`. The boundary rule
("`ui/` is the only package that imports PySide6") is preserved.

```
ui/
├── theme.py                        (unchanged)
├── markdown/                       ★ NEW
│   ├── __init__.py
│   ├── renderer.py                 # md → html (markdown-it-py + Pygments)
│   └── style.css                   # injected into QTextBrowser
├── state/
│   ├── run_state_store.py          (unchanged)
│   ├── history_store.py            ★ NEW
│   └── screenshot_store.py         ★ NEW
├── widgets/
│   ├── mini_bar.py                 (unchanged)
│   ├── prompt_panel.py             (unchanged)
│   ├── provider_picker.py          (unchanged)
│   ├── output_view.py              ✎ use markdown.renderer, keep streaming
│   ├── inspect_panel.py            ★ NEW (split from run_state_panel)
│   ├── compose_dock.py             ★ NEW (Custom + 📎 + Send/Cancel)
│   └── run_state_panel.py          ✎ buttons/thumbnails removed; only
│                                     the grouped renderer remains
├── tabs/                           ★ NEW
│   ├── __init__.py
│   ├── tab_widget.py               # QTabWidget subclass with badge dots
│   ├── chat_tab.py                 # wraps OutputView
│   ├── run_state_tab.py            # wraps RunStatePanel
│   ├── history_tab.py              # list (220px) + detail
│   ├── screenshot_tab.py           # latest frame / multi-frame gallery
│   ├── logs_tab.py                 # scrolling log + Copy all / Clear
│   └── help_tab.py                 # i18n markdown render
├── windows/
│   ├── main_window.py              ✎ new layout; wires stores, tabs, dock
│   ├── permission_dialog.py        (unchanged)
│   └── settings_dialog.py          (unchanged)
└── workers/                        (unchanged)
```

### 4.1 New dependencies

Added to `pyproject.toml` runtime deps:

- `markdown-it-py` — Markdown → HTML
- `Pygments` — code-block syntax highlighting

Both are pure Python and do not affect PyInstaller bundle size
meaningfully.

## 5. Signal flow

- `PromptPanel.action_clicked` and `ComposeDock.send_clicked` →
  `MainWindow` constructs an `InferenceRequest`, switches the tab
  widget to `ChatTab`, then starts `InferenceWorker`.
- `InferenceWorker.chunk` → `ChatTab.append_delta` (existing streaming
  path).
- `InferenceWorker.finished_ok` → `HistoryStore.append(entry)`. Entry
  contains: timestamp, prompt_id (or `"custom"`), custom-text snippet,
  model id, screenshot bytes (or None), final markdown.
- `InferenceWorker.finished_ok` / `finished_failed` →
  `MainWindow._reset_compose()` (restores Send button, clears Cancel).
- Sending a request also pushes the screenshot used into
  `ScreenshotStore.set(frames)` so the Screenshot tab reflects what
  was actually sent.
- `InspectPanel` emits `capture_requested` / `done_requested` /
  `clear_requested` — wired to the existing `MainWindow` handlers.
  On `_on_inspect_ready` (success), `RunStateStore.set()` fires, which
  the `RunStateTab` already listens to.
- Any store update that targets a non-active tab causes the
  `TabWidget` to mark that tab with a badge dot. Activating the tab
  clears the dot.

## 6. State stores

All three stores are `QObject` subclasses living in
`spiresight.ui.state`. They expose a `changed` signal and a getter,
matching the existing `RunStateStore` pattern.

### 6.1 `HistoryStore`

- Backed by an in-memory `collections.deque(maxlen=20)`.
- `append(entry: HistoryEntry)` prepends (newest first) and emits
  `changed`.
- `HistoryEntry` is a frozen dataclass: `timestamp`, `prompt_id`,
  `custom_text`, `model_id`, `include_screenshot` (bool),
  `screenshot_png` (bytes | None), `markdown` (str). No PII beyond
  what the user already sent.
- Cleared on app quit; not persisted to disk in this slice.

### 6.2 `ScreenshotStore`

- Holds the most recent frame set sent to the LLM, as
  `tuple[bytes, ...]` plus a timestamp and pixel dimensions.
- `set(frames)` overwrites and emits `changed`.

## 7. Compose dock behavior

- Single-line initial height, grows to a max of ~4 text lines, then
  scrolls. Never overlaps the active tab content.
- Streaming state: Send button label switches to "Cancel" and triggers
  `InferenceWorker.cancel()`. Text input remains editable so the user
  can prepare the next prompt.
- Keyboard: `Ctrl/Cmd+Enter` submits; `Esc` triggers Cancel while
  streaming, otherwise no-op.
- `📎 Include screenshot` toggle state persists into
  `AppConfig.include_screenshot_default` (new field, default `True`),
  saved via `ConfigStore` on toggle.
- Submitting from any tab auto-switches to the Chat tab before the
  first chunk arrives.

## 8. Tab specifics

### 8.1 Chat tab

Wraps the existing `OutputView`. Streaming behavior unchanged: ~50ms
debounce or 32 chunks, scroll-pinned to bottom. The only change is
the rendering pipeline (see §9).

### 8.2 Run State tab

Wraps the slimmed-down `RunStatePanel`. Layout: vertical column with
the existing top-level sections (Archetype / Cards / Relics / Potions
/ Overall), plus the new grouping for cards.

**Cards grouping:** cards render inside four colored container blocks
keyed by `usefulness`:

- `key` — warm gold tint, "⭐ KEY" header
- `good` — cool blue tint, "GOOD" header
- `situational` — neutral tan tint, "SITUATIONAL" header
- `skip` — muted gray, dimmed, "SKIP" header

Within each block: one card per row, columns `[rarity glyph] [name]
[× count]`; an italic gray sub-line for `note` if present. Empty
groups are omitted. The existing `_USEFULNESS_COLORS` / `_RARITY_GLYPHS`
constants are reused (and extended where needed).

Capture / Done / Clear buttons and the in-progress thumbnail strip
**no longer live here** — they have moved to `InspectPanel` in the
left sidebar.

### 8.3 History tab

Two-pane split inside the tab:

```
┌─ list (220px) ─────┐ ┌─ detail ───────────────┐
│ 12:34 Hand · gpt-4o│ │ [Resend] [Copy MD]     │
│ 12:30 Map · gpt-4o │ │                        │
│ 12:28 Custom       │ │  rendered markdown     │
│ ...                │ │  (read-only)           │
└────────────────────┘ └────────────────────────┘
```

- List sorted newest-first; row shows `HH:MM · <prompt label or
  "Custom"> · <model id>`.
- Selecting a row renders that entry's stored markdown in the detail
  pane (re-using the markdown renderer).
- "Resend" rebuilds an `InferenceRequest` from the entry
  (`prompt_id`, `custom_text`, `include_screenshot`). It **does not
  re-grab the screen** — if `screenshot_png` was stored we pass it
  through; otherwise we fall back to a fresh capture. Sending switches
  back to the Chat tab.
- "Copy MD" copies the raw markdown to clipboard.
- Empty state: a centered hint.

### 8.4 Screenshot tab

- Header row: timestamp · pixel dimensions · "Save as…" button.
- Body: the latest screenshot displayed at fit-to-width (downscale
  only, never upscale). If multiple frames are stored (multi-frame
  inspect), they render as a horizontal scrolling gallery with frame
  numbers.
- "Save as…" opens a `QFileDialog` defaulting to `~/spiresight-<ts>.png`.
- Empty state: hint text plus a reminder that screenshots are not
  persisted on disk by default.

### 8.5 Logs tab

- Monospace scrolling text view, newest at top.
- Captured events: capability mismatches, API errors (with
  `retry_after`), token usage (if the provider returned it), network
  timings.
- In-memory ring buffer, max 200 entries.
- Top toolbar: "Copy all" (full buffer to clipboard) and "Clear"
  (resets the buffer).
- Out of scope for this slice: writing logs to disk, showing
  system-prompt content.

### 8.6 Help tab

- Renders a static Markdown file through the same renderer as Chat.
- Content lives in `prompts/locales/help.en.md` and `help.zh.md`; the
  active file follows `AppConfig.language` and reloads on language
  switch via `UILocale.changed`.
- Sections: global hotkey · mini-bar toggle · inspect flow · adding
  API keys · StS2 term cheat sheet.

## 9. Markdown rendering pipeline

`spiresight.ui.markdown.renderer` is a pure-Python module.

- Public API: `render(md: str) -> str` returning a complete HTML
  fragment safe to feed to `QTextBrowser.setHtml`.
- Internals: `markdown-it-py` with the `gfm-like` preset (tables,
  strikethrough, autolinks); a Pygments-backed fenced-code renderer
  using the `default` style (light theme) recoloured to match the
  rest of the UI; `style.css` embedded inline at the top of the
  returned HTML for portability.
- A `_postprocess_badges(html: str) -> str` hook is called at the end
  of `render`. In this slice it is the identity function; v2 will
  parse `{{card:...}}` / `{{relic:...}}` / `{{hp}}` / `{{energy}}`
  into styled spans here.
- Tolerant of mid-stream incomplete Markdown — the existing
  streaming flush cadence (`OutputView`: ~50ms or 32 chunks) is
  preserved, but each flush now goes through `render()` and
  `setHtml()` instead of `setMarkdown()`.

## 10. i18n keys (additions)

- `tab.chat`, `tab.run_state`, `tab.history`, `tab.screenshot`,
  `tab.logs`, `tab.help`
- `compose.placeholder`, `compose.send`, `compose.cancel`,
  `compose.include_screenshot`
- `history.empty`, `history.resend`, `history.copy_md`,
  `history.row_format` (`"{time} · {label} · {model}"`)
- `screenshot.empty`, `screenshot.save_as`, `screenshot.dims_format`
- `logs.empty`, `logs.copy_all`, `logs.clear`
- `panel.cards_group.key`, `panel.cards_group.good`,
  `panel.cards_group.situational`, `panel.cards_group.skip`

All added to `prompts/locales/en.yaml` and `zh.yaml` in lockstep.

## 11. Testing strategy

- `ui/markdown/renderer.py`: pure-function unit tests covering fenced
  code (with and without a language tag), tables, blockquotes, and a
  mid-stream truncated input that must not raise.
- `state/history_store.py` and `state/screenshot_store.py`: signal-
  emission tests using `qtbot`, following the existing
  `RunStateStore` pattern.
- Widget smoke tests (`qtbot`): each new tab and the
  `ComposeDock` / `InspectPanel` should construct cleanly, wire their
  signals, and respond to one representative event without raising.
- No new end-to-end test is required; the existing inference smoke
  flow continues to cover the happy path.

## 12. Risks and mitigations

- **Streaming with `setHtml` may flicker more than `setMarkdown`.**
  Mitigation: keep the existing debounce; if visible flicker shows up
  during testing, switch to `QTextDocument.setHtml` against a cached
  document and swap pointers, or fall back to `insertHtml` for
  incremental append.
- **`markdown-it-py` mid-stream output may render half-formed
  structures.** Mitigation: rendering already happens at most every
  ~50ms; users see at most one frame of awkward output before the
  next flush. The final `finalize()` always renders the complete
  buffer.
- **Tab badge dot logic creates UX noise if every store update
  fires.** Mitigation: only set the dot when the update would change
  what the user sees (e.g., `HistoryStore.append` always counts;
  `ScreenshotStore.set` only counts if frames differ from the prior
  set). Activating the tab always clears.
- **Width pressure.** With six tabs in a ~700px right pane, the tab
  bar may need ellipsis or icon-only mode at narrow widths. The
  `tabs/tab_widget.py` subclass owns this responsibility; first cut
  uses short labels (e.g., "Chat", "Cards", "History", "Shots",
  "Logs", "Help") tuned to fit at the default 980×580 window size.

## 13. Mini-bar mode

Unchanged. `MiniBar` is an independent top-level widget unaffected by
the right-pane restructure; the existing show/hide flow in
`MainWindow._toggle_mini_bar` / `_exit_mini_bar` keeps working.
