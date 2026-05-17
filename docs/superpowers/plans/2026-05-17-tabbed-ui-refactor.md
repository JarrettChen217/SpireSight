# Tabbed UI Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure `MainWindow`'s right pane into a six-tab widget with a persistent Compose dock, split `RunStatePanel` into an `InspectPanel` (sidebar) + a grouped Run State renderer, and upgrade the Markdown rendering pipeline to `markdown-it-py` + Pygments.

**Architecture:** All changes stay inside `src/spiresight/ui/`. New stores (`HistoryStore`, `ScreenshotStore`) follow the existing `QObject + Signal` pattern. The Markdown renderer is a pure-Python module unit-tested without Qt. Each tab is its own thin widget. Mini-bar mode is untouched.

**Tech Stack:** PySide6, `markdown-it-py`, `Pygments`, pytest (with `QCoreApplication` fixture, no `pytest-qt`).

**Spec:** `docs/superpowers/specs/2026-05-17-tabbed-ui-refactor-design.md`

---

## Conventions used in this plan

- Tests use the existing `qapp` fixture from `tests/conftest.py` (a module-scoped `QCoreApplication`). **Never use `pytest-qt` / `qtbot`** — it is not a project dependency.
- Run tests with `pytest -q tests/<file>::<test>` from the repo root inside the project venv (`source .venv/bin/activate` first if not already in it).
- Always create / use the project venv at `.venv` — never install into system Python.
- Each task ends with a commit. Use the message shown in the final step verbatim (one-line subject + blank line + Co-Authored-By footer).

---

## Phase 1 — Foundations

### Task 1: Add `markdown-it-py` and `Pygments` to dependencies

**Files:**
- Modify: `pyproject.toml` (the `dependencies` list under `[project]`)

- [ ] **Step 1: Edit `pyproject.toml`**

Add one line inside the `dependencies = [...]` array, in alphabetical-ish order (after `httpx`, before `mss`):

```toml
  "markdown-it-py>=3.0",
```

And after `Pillow`:

```toml
  "Pygments>=2.17",
```

The `markdown-it-py` `gfm-like` preset (used in Task 2) covers tables, strikethrough, and autolinks out of the box, so no `mdit-py-plugins` is needed.

- [ ] **Step 2: Install into the venv**

Run from repo root:

```bash
source .venv/bin/activate && pip install -e ".[dev]"
```

Expected: no errors; `Successfully installed markdown-it-py-... mdit-py-plugins-... Pygments-...` (or "already satisfied" for ones that come transitively).

- [ ] **Step 3: Verify imports work**

```bash
python -c "import markdown_it, pygments; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "$(cat <<'EOF'
build(deps): add markdown-it-py and Pygments for richer Markdown rendering

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Markdown renderer module + style sheet + tests

**Files:**
- Create: `src/spiresight/ui/markdown/__init__.py`
- Create: `src/spiresight/ui/markdown/renderer.py`
- Create: `src/spiresight/ui/markdown/style.css`
- Create: `tests/test_markdown_renderer.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_markdown_renderer.py`:

```python
from spiresight.ui.markdown.renderer import render


def test_render_basic_paragraph_returns_html():
    html = render("Hello **world**.")
    assert "<p>" in html
    assert "<strong>world</strong>" in html


def test_render_includes_inline_style_tag():
    html = render("# Title")
    assert "<style>" in html
    assert "</style>" in html


def test_render_heading_level_one():
    html = render("# Title")
    assert "<h1>" in html
    assert ">Title</h1>" in html


def test_render_fenced_code_block_uses_pygments_classes():
    md = "```python\nx = 1\n```"
    html = render(md)
    # Pygments wraps tokens in <span class="..."> with its token classes.
    # The Name token for `x` is class="n"; the operator '=' is class="o".
    assert "highlight" in html  # Pygments highlight container
    assert "<span" in html


def test_render_unknown_code_lang_does_not_raise():
    md = "```bogusLang\nfoo\n```"
    # Pygments falls back to plain text for unknown lexers.
    html = render(md)
    assert "<pre" in html


def test_render_gfm_table():
    md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    html = render(md)
    assert "<table" in html
    assert "<th>A</th>" in html
    assert "<td>1</td>" in html


def test_render_blockquote():
    html = render("> note")
    assert "<blockquote>" in html
    assert "note" in html


def test_render_tolerates_incomplete_midstream_markdown():
    # Streaming may flush half a fence or a half-finished table row.
    # render() must not raise.
    render("```python\nx = 1")
    render("| A | B |\n|---|---|\n| 1 |")
    render("# heading without newline")


def test_render_postprocess_badges_hook_is_identity():
    # v2 will replace this. Verify the hook exists as no-op for now.
    from spiresight.ui.markdown.renderer import _postprocess_badges
    assert _postprocess_badges("<p>x</p>") == "<p>x</p>"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest -q tests/test_markdown_renderer.py
```

Expected: `ModuleNotFoundError: No module named 'spiresight.ui.markdown'`.

- [ ] **Step 3: Create the package `__init__.py`**

Create `src/spiresight/ui/markdown/__init__.py` containing only:

```python
from spiresight.ui.markdown.renderer import render

__all__ = ["render"]
```

- [ ] **Step 4: Create `style.css`**

Create `src/spiresight/ui/markdown/style.css` with:

```css
body { font-family: -apple-system, "Helvetica Neue", "PingFang SC", "Inter", sans-serif;
       font-size: 13px; line-height: 1.55; color: #d8d4cc; }
h1, h2, h3, h4 { color: #f0e9d8; margin: 14px 0 6px; }
h1 { font-size: 18px; border-bottom: 1px solid #4a443a; padding-bottom: 4px; }
h2 { font-size: 16px; }
h3 { font-size: 14px; }
h4 { font-size: 13px; color: #d4a54a; }
p  { margin: 6px 0; }
a  { color: #8fb6e0; }
strong { color: #f0e9d8; }
em { color: #d5cebf; }
ul, ol { margin: 4px 0 8px 22px; padding: 0; }
li { margin: 2px 0; }
blockquote { margin: 8px 0; padding: 4px 10px;
             border-left: 3px solid #6e7a89; color: #b8b1a1;
             background: rgba(110,122,137,0.08); }
code { font-family: ui-monospace, Menlo, "Consolas", monospace;
       font-size: 12px; background: rgba(255,255,255,0.06);
       padding: 1px 4px; border-radius: 3px; color: #f0e9d8; }
pre  { background: #1e1e2e; color: #cdd6f4; padding: 8px 10px;
       border-radius: 5px; overflow-x: auto; margin: 8px 0; }
pre code { background: transparent; padding: 0; color: inherit; }
.highlight { background: transparent; }
.highlight .k  { color: #c792ea; }                /* keyword   */
.highlight .kn { color: #c792ea; }                /* keyword.namespace */
.highlight .s, .highlight .s1, .highlight .s2 { color: #a6e3a1; } /* string */
.highlight .n  { color: #cdd6f4; }                /* name      */
.highlight .nb { color: #82aaff; }                /* name.builtin */
.highlight .nf { color: #82aaff; }                /* name.function */
.highlight .nc { color: #ffcb6b; }                /* name.class */
.highlight .mi, .highlight .mf { color: #fab387; } /* number   */
.highlight .c, .highlight .c1, .highlight .cm { color: #7a8eac; font-style: italic; } /* comment */
.highlight .o  { color: #f38ba8; }                /* operator */
.highlight .p  { color: #cdd6f4; }                /* punctuation */
table { border-collapse: collapse; margin: 8px 0; width: 100%; }
th, td { padding: 4px 8px; border-bottom: 1px solid #3a3a3a;
         text-align: left; font-size: 12.5px; }
th { background: rgba(255,255,255,0.04); color: #f0e9d8; font-weight: 600; }
hr { border: none; border-top: 1px solid #3a3a3a; margin: 12px 0; }
```

- [ ] **Step 5: Create `renderer.py`**

Create `src/spiresight/ui/markdown/renderer.py`:

```python
"""Markdown → HTML pipeline for OutputView and HelpTab.

Pure Python, no Qt. The returned HTML embeds an inline <style> block
so it is safe to feed directly to QTextBrowser.setHtml without needing
an external stylesheet resource.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

_STYLE_PATH = Path(__file__).with_name("style.css")


def _highlight_code(code: str, lang: str | None, _attrs: object) -> str:
    """markdown-it-py highlight callback. Falls back to <pre> for unknown langs."""
    if lang:
        try:
            lexer = get_lexer_by_name(lang, stripall=False)
        except ClassNotFound:
            return ""  # let markdown-it render the default <pre><code> wrapper
    else:
        return ""
    formatter = HtmlFormatter(nowrap=False, noclasses=False, cssclass="highlight")
    return highlight(code, lexer, formatter)


@lru_cache(maxsize=1)
def _style_tag() -> str:
    css = _STYLE_PATH.read_text(encoding="utf-8")
    return f"<style>{css}</style>"


@lru_cache(maxsize=1)
def _md() -> MarkdownIt:
    # "gfm-like" preset = commonmark + tables + strikethrough + linkify.
    return MarkdownIt("gfm-like", {"html": False, "highlight": _highlight_code})


def _postprocess_badges(html: str) -> str:
    """v2 hook for game-term badges ({{card:...}}, {{relic:...}}, etc.).

    Currently identity. Do not remove — callers expect this to be the
    last transformation before returning HTML.
    """
    return html


def render(md_text: str) -> str:
    """Convert a Markdown fragment to a self-contained HTML document.

    Tolerant of mid-stream truncated input (streaming flushes). Never raises.
    """
    try:
        body = _md().render(md_text or "")
    except Exception:
        # Defensive: keep streaming output flowing even if markdown-it
        # trips on a partial structure.
        body = f"<pre>{(md_text or '').replace('<', '&lt;')}</pre>"
    body = _postprocess_badges(body)
    return f"{_style_tag()}<body>{body}</body>"
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest -q tests/test_markdown_renderer.py
```

Expected: 9 passed.

- [ ] **Step 7: Commit**

```bash
git add src/spiresight/ui/markdown tests/test_markdown_renderer.py
git commit -m "$(cat <<'EOF'
feat(ui): markdown-it-py + Pygments rendering pipeline

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `HistoryStore` + `HistoryEntry` dataclass + tests

**Files:**
- Create: `src/spiresight/ui/state/history_store.py`
- Create: `tests/test_history_store.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_history_store.py`:

```python
from datetime import datetime, timezone

from spiresight.ui.state.history_store import HistoryEntry, HistoryStore


def _entry(prompt_id: str = "hand_eval", ts: datetime | None = None) -> HistoryEntry:
    return HistoryEntry(
        timestamp=ts or datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
        prompt_id=prompt_id,
        custom_text="",
        model_id="gpt-4o",
        include_screenshot=True,
        screenshot_png=b"\x89PNG\r\n\x1a\n",
        markdown="**hi**",
    )


def test_initial_entries_empty(qapp):
    store = HistoryStore()
    assert store.entries() == []


def test_append_emits_changed(qapp):
    store = HistoryStore()
    fired: list[int] = []
    store.changed.connect(lambda: fired.append(1))
    store.append(_entry())
    assert fired == [1]


def test_entries_returns_newest_first(qapp):
    store = HistoryStore()
    older = _entry(ts=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc))
    newer = _entry(ts=datetime(2026, 5, 17, 12, 1, tzinfo=timezone.utc))
    store.append(older)
    store.append(newer)
    assert store.entries()[0] is newer
    assert store.entries()[1] is older


def test_capacity_caps_at_20(qapp):
    store = HistoryStore()
    for i in range(25):
        store.append(_entry(prompt_id=f"p{i}"))
    assert len(store.entries()) == 20
    # Newest appended is at index 0; oldest five (p0..p4) evicted.
    assert store.entries()[0].prompt_id == "p24"
    assert all(e.prompt_id != "p0" for e in store.entries())


def test_clear_empties_and_emits(qapp):
    store = HistoryStore()
    store.append(_entry())
    fired: list[int] = []
    store.changed.connect(lambda: fired.append(1))
    store.clear()
    assert store.entries() == []
    assert fired == [1]


def test_entry_is_frozen():
    e = _entry()
    import pytest
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        e.prompt_id = "x"  # type: ignore[misc]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest -q tests/test_history_store.py
```

Expected: `ModuleNotFoundError: No module named 'spiresight.ui.state.history_store'`.

- [ ] **Step 3: Create `history_store.py`**

Create `src/spiresight/ui/state/history_store.py`:

```python
"""In-memory ring buffer of past inference results.

Holds up to MAX_ENTRIES entries, newest first. Not persisted to disk
in this slice (see spec §2 and §6.1).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, Signal


MAX_ENTRIES = 20


@dataclass(frozen=True)
class HistoryEntry:
    timestamp: datetime
    prompt_id: str               # quick-action id, or "custom"
    custom_text: str
    model_id: str
    include_screenshot: bool
    screenshot_png: bytes | None
    markdown: str


class HistoryStore(QObject):
    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: deque[HistoryEntry] = deque(maxlen=MAX_ENTRIES)

    def entries(self) -> list[HistoryEntry]:
        # Newest first.
        return list(reversed(self._entries))

    def append(self, entry: HistoryEntry) -> None:
        self._entries.append(entry)
        self.changed.emit()

    def clear(self) -> None:
        if not self._entries:
            return
        self._entries.clear()
        self.changed.emit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest -q tests/test_history_store.py
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/state/history_store.py tests/test_history_store.py
git commit -m "$(cat <<'EOF'
feat(ui): HistoryStore — in-memory ring buffer of past responses

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `ScreenshotStore` + tests

**Files:**
- Create: `src/spiresight/ui/state/screenshot_store.py`
- Create: `tests/test_screenshot_store.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_screenshot_store.py`:

```python
from datetime import datetime, timezone

from spiresight.ui.state.screenshot_store import ScreenshotBundle, ScreenshotStore


PNG_A = b"\x89PNG\r\n\x1a\nA"
PNG_B = b"\x89PNG\r\n\x1a\nB"


def test_initial_get_is_none(qapp):
    store = ScreenshotStore()
    assert store.get() is None


def test_set_then_get(qapp):
    store = ScreenshotStore()
    bundle = ScreenshotBundle(
        frames=(PNG_A,),
        timestamp=datetime(2026, 5, 17, tzinfo=timezone.utc),
        width=1920, height=1080,
    )
    store.set(bundle)
    assert store.get() == bundle


def test_set_emits_changed_when_frames_differ(qapp):
    store = ScreenshotStore()
    fired: list[int] = []
    store.changed.connect(lambda: fired.append(1))
    ts = datetime(2026, 5, 17, tzinfo=timezone.utc)
    store.set(ScreenshotBundle(frames=(PNG_A,), timestamp=ts, width=10, height=10))
    store.set(ScreenshotBundle(frames=(PNG_B,), timestamp=ts, width=10, height=10))
    assert fired == [1, 1]


def test_set_skips_emit_when_frames_identical(qapp):
    store = ScreenshotStore()
    ts = datetime(2026, 5, 17, tzinfo=timezone.utc)
    store.set(ScreenshotBundle(frames=(PNG_A,), timestamp=ts, width=10, height=10))
    fired: list[int] = []
    store.changed.connect(lambda: fired.append(1))
    # Same bytes again — no emit.
    store.set(ScreenshotBundle(frames=(PNG_A,), timestamp=ts, width=10, height=10))
    assert fired == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest -q tests/test_screenshot_store.py
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `screenshot_store.py`**

Create `src/spiresight/ui/state/screenshot_store.py`:

```python
"""Most recent screenshot bundle sent to the LLM.

Holds the frames that were attached to the latest request so the
Screenshot tab can display what the model actually saw. Not persisted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True)
class ScreenshotBundle:
    frames: tuple[bytes, ...]
    timestamp: datetime
    width: int
    height: int


class ScreenshotStore(QObject):
    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bundle: ScreenshotBundle | None = None

    def get(self) -> ScreenshotBundle | None:
        return self._bundle

    def set(self, bundle: ScreenshotBundle) -> None:
        if self._bundle is not None and self._bundle.frames == bundle.frames:
            self._bundle = bundle  # update metadata silently
            return
        self._bundle = bundle
        self.changed.emit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest -q tests/test_screenshot_store.py
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/state/screenshot_store.py tests/test_screenshot_store.py
git commit -m "$(cat <<'EOF'
feat(ui): ScreenshotStore — latest frames sent to the LLM

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Add `include_screenshot_default` field to `AppConfig`

**Files:**
- Modify: `src/spiresight/config/schema.py`
- Modify: `tests/test_config_store.py` (add one assertion)

- [ ] **Step 1: Write a failing assertion in the existing config test**

Open `tests/test_config_store.py`, find the test that constructs a fresh `AppConfig` (most files have one called something like `test_default_app_config` or `test_round_trip`). Read the file to find a place to add this assertion:

```python
def test_include_screenshot_default_defaults_to_true():
    from spiresight.config.schema import AppConfig
    cfg = AppConfig()
    assert cfg.include_screenshot_default is True
```

If no fitting place exists, add it as a new top-level test in the file.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest -q tests/test_config_store.py::test_include_screenshot_default_defaults_to_true
```

Expected: `AttributeError` or pydantic validation error for unknown field.

- [ ] **Step 3: Add the field to `AppConfig`**

In `src/spiresight/config/schema.py`, inside the `AppConfig` class, after the existing `last_used_prompt_id: str | None = None` line, append:

```python
    include_screenshot_default: bool = True
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest -q tests/test_config_store.py
```

Expected: all existing tests + new one pass.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/config/schema.py tests/test_config_store.py
git commit -m "$(cat <<'EOF'
feat(config): persist include_screenshot toggle default

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2 — Widget building blocks

### Task 6: `OutputView` uses the new markdown renderer

**Files:**
- Modify: `src/spiresight/ui/widgets/output_view.py`

- [ ] **Step 1: Open and rewrite `output_view.py`**

Replace the entire file contents with:

```python
"""Streaming markdown view.

Buffers incoming text deltas and re-renders at most every 50ms (or
every 32 deltas) to keep the UI responsive. Each flush runs the buffer
through spiresight.ui.markdown.renderer.render so we get Pygments-
highlighted code, real tables, and the shared CSS theme.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import QTextBrowser

from spiresight.ui.markdown.renderer import render as render_markdown

_FLUSH_INTERVAL_MS = 50
_FLUSH_DELTA_COUNT = 32


class OutputView(QTextBrowser):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self._buffer: list[str] = []
        self._pending = 0
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush)

    def reset(self) -> None:
        self._buffer.clear()
        self._pending = 0
        self.setHtml(render_markdown(""))

    def load_static(self, markdown: str) -> None:
        """Render a non-streaming markdown blob (used by HistoryTab detail)."""
        self._flush_timer.stop()
        self._buffer = [markdown]
        self._pending = 0
        self.setHtml(render_markdown(markdown))

    @Slot(str)
    def append_delta(self, text: str) -> None:
        self._buffer.append(text)
        self._pending += 1
        if self._pending >= _FLUSH_DELTA_COUNT:
            self._flush()
        elif not self._flush_timer.isActive():
            self._flush_timer.start(_FLUSH_INTERVAL_MS)

    @Slot()
    def finalize(self) -> None:
        self._flush_timer.stop()
        self._flush()

    def current_markdown(self) -> str:
        return "".join(self._buffer)

    def _flush(self) -> None:
        self.setHtml(render_markdown("".join(self._buffer)))
        self._pending = 0
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())
```

- [ ] **Step 2: Run the full test suite to confirm nothing regressed**

```bash
pytest -q
```

Expected: same number of passed tests as before this task (no `OutputView` tests exist today; widget code is exercised via smoke tests later).

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/ui/widgets/output_view.py
git commit -m "$(cat <<'EOF'
feat(ui): OutputView renders via markdown-it-py pipeline

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Extract `InspectPanel` from `RunStatePanel`

**Files:**
- Create: `src/spiresight/ui/widgets/inspect_panel.py`
- Create: `tests/test_inspect_panel.py`

- [ ] **Step 1: Write the failing smoke test**

Create `tests/test_inspect_panel.py`:

```python
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

import pytest

from spiresight.core.inspect_session import InspectSession
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.widgets.inspect_panel import InspectPanel


# InspectPanel uses QWidget which needs QApplication (not just QCoreApplication).
@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def locale(tmp_path: Path) -> UILocale:
    en = tmp_path / "en"
    en.mkdir()
    (en / "ui_strings.yaml").write_text(
        "panel:\n"
        "  capture: 'Cap'\n"
        "  done: 'Done'\n"
        "  done_busy: 'Busy'\n"
        "  clear: 'Clear'\n"
        "  max_frames: 'Max {max}'\n"
        "  no_frames: 'Need a frame'\n"
        "  empty_hint: 'hint'\n"
        "  frame_tooltip: 'Frame {n}'\n",
        encoding="utf-8",
    )
    return UILocale(tmp_path, language="en")


def test_capture_clicked_emits_signal(qtwidgets_app, locale):
    session = InspectSession()
    panel = InspectPanel(session, locale)
    fired: list[int] = []
    panel.capture_requested.connect(lambda: fired.append(1))
    panel._capture_btn.click()
    assert fired == [1]


def test_done_disabled_when_no_frames(qtwidgets_app, locale):
    session = InspectSession()
    panel = InspectPanel(session, locale)
    assert panel._done_btn.isEnabled() is False


def test_done_enabled_after_frame_added(qtwidgets_app, locale):
    session = InspectSession()
    panel = InspectPanel(session, locale)
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    assert panel._done_btn.isEnabled() is True


def test_set_capture_enabled_false_disables_buttons(qtwidgets_app, locale):
    session = InspectSession()
    panel = InspectPanel(session, locale)
    panel.set_capture_enabled(False, "no model")
    assert panel._capture_btn.isEnabled() is False
    assert panel._done_btn.isEnabled() is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest -q tests/test_inspect_panel.py
```

Expected: `ModuleNotFoundError: No module named 'spiresight.ui.widgets.inspect_panel'`.

- [ ] **Step 3: Create `inspect_panel.py`**

Create `src/spiresight/ui/widgets/inspect_panel.py`:

```python
"""Sidebar input widget for the multi-frame inspect flow.

Owns: the thumbnail strip showing currently-captured (but not yet
submitted) frames + the three buttons that drive the InspectSession
state machine. Emits the same three signals MainWindow already wires
(capture_requested / done_requested / clear_requested).

The previous RunStatePanel embedded both these controls AND the
state rendering; in the tabbed layout the rendering moves to
RunStateTab and only this input piece stays in the sidebar.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from spiresight.core.inspect_session import InspectSession
from spiresight.prompts.ui_locale import UILocale


class _Thumbnail(QFrame):
    remove_clicked = Signal(int)

    def __init__(
        self, png: bytes, index: int, tooltip: str, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._index = index
        self.setFixedSize(64, 36)
        self.setFrameShape(QFrame.Shape.Box)
        self.setStyleSheet("background-color: #2a2a2a; border: 1px solid #444;")

        pix = QPixmap()
        pix.loadFromData(png)
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

        self.setToolTip(tooltip)


class InspectPanel(QWidget):
    capture_requested = Signal()
    done_requested    = Signal()
    clear_requested   = Signal()

    def __init__(
        self,
        session: InspectSession,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._locale = locale
        self._capability_ok = True
        self._capability_tooltip = ""
        self._busy = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self._header_label = QLabel("Inspect")
        self._header_label.setProperty("role", "section-header")
        outer.addWidget(self._header_label)

        # thumbnail strip
        self._strip_scroll = QScrollArea()
        self._strip_scroll.setWidgetResizable(True)
        self._strip_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._strip_scroll.setFixedHeight(0)
        self._strip_host = QWidget()
        self._strip_layout = QHBoxLayout(self._strip_host)
        self._strip_layout.setContentsMargins(0, 0, 0, 0)
        self._strip_layout.setSpacing(4)
        self._strip_layout.addStretch(1)
        self._strip_scroll.setWidget(self._strip_host)
        outer.addWidget(self._strip_scroll)

        # buttons
        button_row = QHBoxLayout()
        self._capture_btn = QPushButton(locale.get("panel.capture"))
        self._capture_btn.setObjectName("primary")
        self._capture_btn.clicked.connect(self.capture_requested.emit)
        self._done_btn = QPushButton(locale.get("panel.done"))
        self._done_btn.clicked.connect(self.done_requested.emit)
        self._clear_btn = QPushButton(locale.get("panel.clear"))
        self._clear_btn.clicked.connect(self.clear_requested.emit)
        button_row.addWidget(self._capture_btn)
        button_row.addWidget(self._done_btn)
        button_row.addWidget(self._clear_btn)
        outer.addLayout(button_row)

        session.changed.connect(self._refresh_thumbnails)
        locale.changed.connect(self._retranslate)
        self._refresh_thumbnails()

    # ── public control API ──
    def set_capture_enabled(self, enabled: bool, tooltip: str = "") -> None:
        self._capability_ok = enabled
        self._capability_tooltip = tooltip
        self._update_button_states()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_button_states()

    # ── internals ──
    def _refresh_thumbnails(self) -> None:
        while self._strip_layout.count():
            item = self._strip_layout.takeAt(0)
            if item is not None:
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
            tip = self._locale.get("panel.frame_tooltip", n=i + 1)
            thumb = _Thumbnail(png, i, tip, parent=self._strip_host)
            thumb.remove_clicked.connect(self._session.remove_frame)
            self._strip_layout.addWidget(thumb)
        self._strip_layout.addStretch(1)
        self._update_button_states()

    def _update_button_states(self) -> None:
        loc = self._locale
        count = self._session.count
        at_cap = count >= InspectSession.MAX_FRAMES

        if self._busy:
            self._capture_btn.setEnabled(False)
            self._capture_btn.setToolTip("")
            self._done_btn.setEnabled(False)
            self._done_btn.setText(loc.get("panel.done_busy"))
            self._done_btn.setToolTip("")
            return

        self._done_btn.setText(loc.get("panel.done"))

        if not self._capability_ok:
            self._capture_btn.setEnabled(False)
            self._capture_btn.setToolTip(self._capability_tooltip)
            self._done_btn.setEnabled(False)
            self._done_btn.setToolTip(self._capability_tooltip)
            return

        if at_cap:
            self._capture_btn.setEnabled(False)
            self._capture_btn.setToolTip(
                loc.get("panel.max_frames", max=InspectSession.MAX_FRAMES)
            )
        else:
            self._capture_btn.setEnabled(True)
            self._capture_btn.setToolTip("")

        if count == 0:
            self._done_btn.setEnabled(False)
            self._done_btn.setToolTip(loc.get("panel.no_frames"))
        else:
            self._done_btn.setEnabled(True)
            self._done_btn.setToolTip("")

    def _retranslate(self) -> None:
        loc = self._locale
        self._capture_btn.setText(loc.get("panel.capture"))
        self._done_btn.setText(
            loc.get("panel.done_busy") if self._busy else loc.get("panel.done")
        )
        self._clear_btn.setText(loc.get("panel.clear"))
        self._refresh_thumbnails()
        self._update_button_states()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest -q tests/test_inspect_panel.py
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/widgets/inspect_panel.py tests/test_inspect_panel.py
git commit -m "$(cat <<'EOF'
feat(ui): InspectPanel — sidebar widget owning the capture flow

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Refactor `RunStatePanel` to grouped-by-usefulness layout

**Files:**
- Modify: `src/spiresight/ui/widgets/run_state_panel.py` (replace entire file)

- [ ] **Step 1: Replace `run_state_panel.py` contents**

Overwrite `src/spiresight/ui/widgets/run_state_panel.py` with:

```python
"""Display-only widget that renders a parsed RunState.

The capture/done/clear buttons and the in-progress thumbnail strip
have moved to InspectPanel; this widget now only renders the latest
state from RunStateStore, grouped by card usefulness.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from spiresight.core.run_state import RunState
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.run_state_store import RunStateStore


_USEFULNESS_ORDER = ("key", "good", "situational", "skip")

_GROUP_STYLE = {
    "key":         ("#fdf4dc", "#f0d68e", "#8a5a00"),
    "good":        ("#e8f1f8", "#c3d9eb", "#2d5a85"),
    "situational": ("#f4f2ed", "#e0dcd2", "#7a715f"),
    "skip":        ("#f0f0f0", "#d8d8d8", "#888888"),
}

_RARITY_GLYPHS = {
    "starter":  "○",
    "common":   "●",
    "uncommon": "◆",
    "rare":     "◆",
}


class RunStatePanel(QWidget):
    """Pure display. Subscribes to RunStateStore.changed."""

    def __init__(
        self,
        store: RunStateStore,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._locale = locale

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

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
        locale.changed.connect(self._re_render)
        self._render(store.get())

    # ── rendering ──
    def _clear_content(self) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()

    def _re_render(self) -> None:
        self._render(self._store.get())

    def _render(self, state: RunState | None) -> None:
        self._clear_content()
        loc = self._locale
        if state is None:
            empty = QLabel(loc.get("panel.empty_hint"))
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #6e7a89;")
            self._content_layout.addWidget(empty)
            self._content_layout.addStretch(1)
            return

        if state.archetype_candidates:
            self._content_layout.addWidget(self._subheader(loc.get("panel.archetype")))
            for a in state.archetype_candidates:
                tag = QLabel(f"{a.name} ({a.confidence})")
                if a.confidence == "high":
                    tag.setStyleSheet(
                        "background:#fef3d8; color:#8a5a00; padding:3px 9px;"
                        "border-radius:11px; border:1px solid #f0d68e; font-weight:600;"
                    )
                else:
                    tag.setStyleSheet(
                        "background:#f4f4f4; color:#666; padding:3px 9px;"
                        "border-radius:11px; border:1px solid #e0e0e0;"
                    )
                tag.setMaximumHeight(22)
                self._content_layout.addWidget(tag)

        if state.cards:
            total = sum(c.count for c in state.cards)
            self._content_layout.addWidget(
                self._subheader(loc.get("panel.cards", total=total))
            )
            buckets: dict[str, list] = {u: [] for u in _USEFULNESS_ORDER}
            for c in state.cards:
                bucket = c.usefulness if c.usefulness in buckets else "situational"
                buckets[bucket].append(c)
            for u in _USEFULNESS_ORDER:
                items = buckets[u]
                if not items:
                    continue
                self._content_layout.addWidget(self._cards_group(u, items))

        if state.relics:
            self._content_layout.addWidget(self._subheader(loc.get("panel.relics")))
            relic_text = " · ".join(r.name for r in state.relics)
            relic_label = QLabel(relic_text)
            relic_label.setWordWrap(True)
            self._content_layout.addWidget(relic_label)

        if state.potions:
            self._content_layout.addWidget(self._subheader(loc.get("panel.potions")))
            self._content_layout.addWidget(QLabel(" · ".join(state.potions)))

        if state.overall_eval.strip():
            self._content_layout.addWidget(self._subheader(loc.get("panel.eval")))
            eval_label = QLabel(state.overall_eval.strip())
            eval_label.setWordWrap(True)
            eval_label.setStyleSheet("color: #d5cebf;")
            self._content_layout.addWidget(eval_label)

        self._content_layout.addStretch(1)

    def _cards_group(self, usefulness: str, items: list) -> QWidget:
        loc = self._locale
        bg, border, header_color = _GROUP_STYLE[usefulness]
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        wrapper.setStyleSheet(
            f"background:{bg}; border:1px solid {border}; border-radius:6px;"
        )

        header_key = f"panel.cards_group.{usefulness}"
        header = QLabel(loc.get(header_key))
        header.setStyleSheet(
            f"color:{header_color}; font-size:10.5px; font-weight:700;"
            f"text-transform:uppercase; letter-spacing:0.5px;"
        )
        layout.addWidget(header)

        for c in items:
            glyph = _RARITY_GLYPHS.get(c.rarity, "●")
            label_text = c.name if c.count == 1 else f"{c.name} ×{c.count}"
            row = QLabel(f"{glyph}  {label_text}")
            row.setStyleSheet(f"color:{header_color};")
            layout.addWidget(row)
            if c.note:
                note = QLabel(f"    {c.note}")
                note.setWordWrap(True)
                note.setStyleSheet("color:#666; font-size:11px; font-style:italic;")
                layout.addWidget(note)
        return wrapper

    @staticmethod
    def _subheader(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #6e7a89; font-size: 10px; "
                          "text-transform: uppercase; margin-top: 4px;")
        return lbl
```

- [ ] **Step 2: Update / delete the old `run_state_panel` tests if present**

```bash
ls tests/ | grep run_state_panel || echo "no panel tests to update"
```

If a `tests/test_run_state_panel.py` exists, open it and either delete it (the panel is now smoke-tested transitively through `RunStateTab` in Task 12) or rewrite it to only assert that `_render(None)` shows the empty hint and `_render(<state with cards>)` produces ≥1 child widget. The current spec covers the rendering via the upcoming `RunStateTab` smoke test, so deletion is acceptable.

- [ ] **Step 3: Run the full test suite**

```bash
pytest -q
```

Expected: same number of passed tests as after Task 7 (existing inference / store / locale tests all pass; the `RunStatePanel` import in `main_window.py` is now broken because the constructor signature changed — we will rewire it in Task 18).

If `tests/test_run_state_panel.py` was kept and now fails on the constructor signature, delete the broken cases.

- [ ] **Step 4: Commit**

```bash
git add src/spiresight/ui/widgets/run_state_panel.py
# include `git rm tests/test_run_state_panel.py` if you deleted it
git commit -m "$(cat <<'EOF'
feat(ui): RunStatePanel — display-only, grouped by usefulness

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: `ComposeDock` widget

**Files:**
- Create: `src/spiresight/ui/widgets/compose_dock.py`
- Create: `tests/test_compose_dock.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_compose_dock.py`:

```python
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.widgets.compose_dock import ComposeDock


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def locale(tmp_path: Path) -> UILocale:
    en = tmp_path / "en"
    en.mkdir()
    (en / "ui_strings.yaml").write_text(
        "compose:\n"
        "  placeholder: 'type'\n"
        "  send: 'Send'\n"
        "  cancel: 'Cancel'\n"
        "  include_screenshot: 'Screenshot'\n",
        encoding="utf-8",
    )
    return UILocale(tmp_path, language="en")


def test_send_clicked_emits_with_text(qtwidgets_app, locale):
    dock = ComposeDock(locale, include_screenshot_default=True)
    captured: list[tuple[str, bool]] = []
    dock.send_clicked.connect(lambda t, s: captured.append((t, s)))
    dock._text.setPlainText("hello")
    dock._send_btn.click()
    assert captured == [("hello", True)]


def test_include_screenshot_toggle_emits(qtwidgets_app, locale):
    dock = ComposeDock(locale, include_screenshot_default=True)
    seen: list[bool] = []
    dock.include_screenshot_toggled.connect(lambda v: seen.append(v))
    dock._screenshot_chk.click()
    assert seen == [False]


def test_set_streaming_swaps_button_label(qtwidgets_app, locale):
    dock = ComposeDock(locale, include_screenshot_default=True)
    assert dock._send_btn.text() == "Send"
    dock.set_streaming(True)
    assert dock._send_btn.text() == "Cancel"
    dock.set_streaming(False)
    assert dock._send_btn.text() == "Send"


def test_clicking_send_while_streaming_emits_cancel(qtwidgets_app, locale):
    dock = ComposeDock(locale, include_screenshot_default=True)
    cancelled: list[int] = []
    dock.cancel_clicked.connect(lambda: cancelled.append(1))
    dock.set_streaming(True)
    dock._send_btn.click()
    assert cancelled == [1]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest -q tests/test_compose_dock.py
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `compose_dock.py`**

Create `src/spiresight/ui/widgets/compose_dock.py`:

```python
"""Persistent bottom-of-right-pane compose bar.

Always visible regardless of which tab is active. Owns the Custom-text
input, the Include-screenshot toggle, and the dual-purpose Send/Cancel
button. The Send button morphs into Cancel while a request is in
flight (see set_streaming).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from spiresight.prompts.ui_locale import UILocale


class _CtrlEnterTextEdit(QPlainTextEdit):
    """QPlainTextEdit that fires submit() on Ctrl/Cmd+Enter."""

    submit = Signal()
    cancel = Signal()

    def keyPressEvent(self, ev: QKeyEvent) -> None:
        mod = ev.modifiers()
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
            mod & Qt.KeyboardModifier.ControlModifier
            or mod & Qt.KeyboardModifier.MetaModifier
        ):
            self.submit.emit()
            return
        if ev.key() == Qt.Key.Key_Escape:
            self.cancel.emit()
            return
        super().keyPressEvent(ev)


class ComposeDock(QWidget):
    send_clicked = Signal(str, bool)            # text, include_screenshot
    cancel_clicked = Signal()
    include_screenshot_toggled = Signal(bool)

    def __init__(
        self,
        locale: UILocale,
        include_screenshot_default: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._locale = locale
        self._streaming = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)
        outer.setSpacing(4)

        self._text = _CtrlEnterTextEdit()
        self._text.setPlaceholderText(locale.get("compose.placeholder"))
        self._text.setFixedHeight(64)
        self._text.submit.connect(self._on_send_or_cancel)
        self._text.cancel.connect(self._on_escape)
        outer.addWidget(self._text)

        row = QHBoxLayout()
        self._screenshot_chk = QCheckBox(locale.get("compose.include_screenshot"))
        self._screenshot_chk.setChecked(include_screenshot_default)
        self._screenshot_chk.toggled.connect(self.include_screenshot_toggled.emit)
        row.addWidget(self._screenshot_chk)
        row.addStretch(1)
        self._send_btn = QPushButton(locale.get("compose.send"))
        self._send_btn.setObjectName("primary")
        self._send_btn.clicked.connect(self._on_send_or_cancel)
        row.addWidget(self._send_btn)
        outer.addLayout(row)

        locale.changed.connect(self._retranslate)

    # ── public API ──
    def text(self) -> str:
        return self._text.toPlainText().strip()

    def clear_text(self) -> None:
        self._text.clear()

    def include_screenshot(self) -> bool:
        return self._screenshot_chk.isChecked()

    def set_streaming(self, streaming: bool) -> None:
        self._streaming = streaming
        self._send_btn.setText(
            self._locale.get("compose.cancel") if streaming
            else self._locale.get("compose.send")
        )

    # ── internals ──
    def _on_send_or_cancel(self) -> None:
        if self._streaming:
            self.cancel_clicked.emit()
            return
        self.send_clicked.emit(self.text(), self.include_screenshot())

    def _on_escape(self) -> None:
        if self._streaming:
            self.cancel_clicked.emit()

    def _retranslate(self) -> None:
        loc = self._locale
        self._text.setPlaceholderText(loc.get("compose.placeholder"))
        self._screenshot_chk.setText(loc.get("compose.include_screenshot"))
        self._send_btn.setText(
            loc.get("compose.cancel") if self._streaming else loc.get("compose.send")
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest -q tests/test_compose_dock.py
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/widgets/compose_dock.py tests/test_compose_dock.py
git commit -m "$(cat <<'EOF'
feat(ui): ComposeDock — persistent bottom compose bar

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3 — Tab infrastructure & tabs

### Task 10: `TabWidget` subclass with badge dots

**Files:**
- Create: `src/spiresight/ui/tabs/__init__.py`
- Create: `src/spiresight/ui/tabs/tab_widget.py`
- Create: `tests/test_tab_widget.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tab_widget.py`:

```python
import pytest
from PySide6.QtWidgets import QApplication, QLabel

from spiresight.ui.tabs.tab_widget import TabWidget


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_mark_dirty_other_tab_sets_badge(qtwidgets_app):
    w = TabWidget()
    w.addTab(QLabel("a"), "A")
    w.addTab(QLabel("b"), "B")
    w.setCurrentIndex(0)
    w.mark_dirty(1)
    assert w.tabText(1).endswith("●")


def test_mark_dirty_active_tab_is_noop(qtwidgets_app):
    w = TabWidget()
    w.addTab(QLabel("a"), "A")
    w.addTab(QLabel("b"), "B")
    w.setCurrentIndex(1)
    w.mark_dirty(1)
    assert w.tabText(1) == "B"


def test_switching_to_dirty_tab_clears_badge(qtwidgets_app):
    w = TabWidget()
    w.addTab(QLabel("a"), "A")
    w.addTab(QLabel("b"), "B")
    w.setCurrentIndex(0)
    w.mark_dirty(1)
    assert w.tabText(1).endswith("●")
    w.setCurrentIndex(1)
    assert w.tabText(1) == "B"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest -q tests/test_tab_widget.py
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create the package and module**

Create `src/spiresight/ui/tabs/__init__.py` (empty file).

Create `src/spiresight/ui/tabs/tab_widget.py`:

```python
"""QTabWidget subclass that supports per-tab "unread" badge dots.

The dot appears in the tab label as a trailing " ●" when a store
update targets a tab that is not currently active. Switching to the
tab clears its dot. This is intentionally simple — no animation, no
counts, just a binary marker.
"""
from __future__ import annotations

from PySide6.QtWidgets import QTabWidget


_DOT = " ●"


class TabWidget(QTabWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._base_labels: list[str] = []
        self.currentChanged.connect(self._on_current_changed)

    def addTab(self, widget, label):  # type: ignore[override]
        idx = super().addTab(widget, label)
        self._base_labels.append(label)
        return idx

    def mark_dirty(self, index: int) -> None:
        if index == self.currentIndex():
            return
        if 0 <= index < self.count():
            base = self._base_labels[index]
            if not self.tabText(index).endswith(_DOT):
                self.setTabText(index, base + _DOT)

    def set_label(self, index: int, label: str) -> None:
        """Update a tab's base label (e.g., on locale change)."""
        if 0 <= index < self.count():
            self._base_labels[index] = label
            dirty = self.tabText(index).endswith(_DOT)
            self.setTabText(index, label + (_DOT if dirty else ""))

    def _on_current_changed(self, idx: int) -> None:
        if 0 <= idx < self.count():
            self.setTabText(idx, self._base_labels[idx])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest -q tests/test_tab_widget.py
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/tabs/__init__.py src/spiresight/ui/tabs/tab_widget.py tests/test_tab_widget.py
git commit -m "$(cat <<'EOF'
feat(ui): TabWidget with per-tab dirty-dot badges

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: `ChatTab`

**Files:**
- Create: `src/spiresight/ui/tabs/chat_tab.py`

- [ ] **Step 1: Create `chat_tab.py`**

Create `src/spiresight/ui/tabs/chat_tab.py`:

```python
"""Thin wrapper around OutputView so it can live as a tab."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from spiresight.ui.widgets.output_view import OutputView


class ChatTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.output = OutputView()
        layout.addWidget(self.output)

    # convenience pass-throughs
    def reset(self) -> None:
        self.output.reset()

    def append_delta(self, text: str) -> None:
        self.output.append_delta(text)

    def finalize(self) -> None:
        self.output.finalize()

    def load_static(self, markdown: str) -> None:
        self.output.load_static(markdown)

    def current_markdown(self) -> str:
        return self.output.current_markdown()
```

- [ ] **Step 2: Sanity-import**

```bash
python -c "from spiresight.ui.tabs.chat_tab import ChatTab; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/ui/tabs/chat_tab.py
git commit -m "$(cat <<'EOF'
feat(ui): ChatTab — wraps OutputView for the tab layout

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: `RunStateTab`

**Files:**
- Create: `src/spiresight/ui/tabs/run_state_tab.py`
- Create: `tests/test_run_state_tab.py`

- [ ] **Step 1: Write the failing smoke test**

Create `tests/test_run_state_tab.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.core.run_state import Archetype, Card, RunState
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.run_state_store import RunStateStore
from spiresight.ui.tabs.run_state_tab import RunStateTab


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def locale(tmp_path: Path) -> UILocale:
    en = tmp_path / "en"
    en.mkdir()
    (en / "ui_strings.yaml").write_text(
        "panel:\n"
        "  empty_hint: 'hint'\n"
        "  archetype: 'Archetype'\n"
        "  cards: 'Cards ({total})'\n"
        "  relics: 'Relics'\n"
        "  potions: 'Potions'\n"
        "  eval: 'Eval'\n"
        "  cards_group:\n"
        "    key: 'KEY'\n"
        "    good: 'GOOD'\n"
        "    situational: 'SITUATIONAL'\n"
        "    skip: 'SKIP'\n",
        encoding="utf-8",
    )
    return UILocale(tmp_path, language="en")


def test_construct_with_empty_store(qtwidgets_app, locale):
    store = RunStateStore()
    tab = RunStateTab(store, locale)
    assert tab is not None


def test_renders_after_store_set(qtwidgets_app, locale):
    store = RunStateStore()
    tab = RunStateTab(store, locale)
    state = RunState(
        cards=[
            Card(name="Cold Snap", count=2, rarity="common", usefulness="key", note="core"),
            Card(name="Defend", count=3, rarity="common", usefulness="good"),
        ],
        relics=[], potions=[],
        archetype_candidates=[Archetype(name="Frost", confidence="high")],
        overall_eval="",
        inspected_at=datetime(2026, 5, 17, tzinfo=timezone.utc),
    )
    store.set(state)
    # Did not raise; at least one child widget exists under the scroll area.
    assert tab._panel._content_layout.count() > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest -q tests/test_run_state_tab.py
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `run_state_tab.py`**

Create `src/spiresight/ui/tabs/run_state_tab.py`:

```python
"""Read-only tab that displays the latest RunState via RunStatePanel."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.run_state_store import RunStateStore
from spiresight.ui.widgets.run_state_panel import RunStatePanel


class RunStateTab(QWidget):
    def __init__(
        self,
        store: RunStateStore,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._panel = RunStatePanel(store, locale)
        layout.addWidget(self._panel)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest -q tests/test_run_state_tab.py
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/tabs/run_state_tab.py tests/test_run_state_tab.py
git commit -m "$(cat <<'EOF'
feat(ui): RunStateTab — display-only tab wrapping RunStatePanel

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: `HistoryTab` (list + detail + Resend)

**Files:**
- Create: `src/spiresight/ui/tabs/history_tab.py`
- Create: `tests/test_history_tab.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_history_tab.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.history_store import HistoryEntry, HistoryStore
from spiresight.ui.tabs.history_tab import HistoryTab


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def locale(tmp_path: Path) -> UILocale:
    en = tmp_path / "en"
    en.mkdir()
    (en / "ui_strings.yaml").write_text(
        "history:\n"
        "  empty: 'No history yet.'\n"
        "  resend: 'Resend'\n"
        "  copy_md: 'Copy'\n"
        "  row_format: '{time} · {label} · {model}'\n",
        encoding="utf-8",
    )
    return UILocale(tmp_path, language="en")


def _entry(prompt_id: str = "hand", ts: datetime | None = None) -> HistoryEntry:
    return HistoryEntry(
        timestamp=ts or datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
        prompt_id=prompt_id,
        custom_text="",
        model_id="gpt-4o",
        include_screenshot=True,
        screenshot_png=None,
        markdown=f"# {prompt_id}",
    )


def test_empty_state(qtwidgets_app, locale):
    store = HistoryStore()
    tab = HistoryTab(store, locale)
    assert tab._list.count() == 0


def test_entries_populate_list_newest_first(qtwidgets_app, locale):
    store = HistoryStore()
    tab = HistoryTab(store, locale)
    store.append(_entry("a", ts=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)))
    store.append(_entry("b", ts=datetime(2026, 5, 17, 12, 1, tzinfo=timezone.utc)))
    assert tab._list.count() == 2
    # Newest first means item 0 is "b".
    assert "b" in tab._list.item(0).text()


def test_resend_emits_with_entry(qtwidgets_app, locale):
    store = HistoryStore()
    tab = HistoryTab(store, locale)
    e = _entry("x")
    store.append(e)
    tab._list.setCurrentRow(0)
    fired: list[HistoryEntry] = []
    tab.resend_requested.connect(lambda en: fired.append(en))
    tab._resend_btn.click()
    assert fired == [e]


def test_selecting_row_loads_detail(qtwidgets_app, locale):
    store = HistoryStore()
    tab = HistoryTab(store, locale)
    store.append(_entry("xyz"))
    tab._list.setCurrentRow(0)
    # OutputView buffers in current_markdown()
    assert "xyz" in tab._detail.current_markdown()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest -q tests/test_history_tab.py
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `history_tab.py`**

Create `src/spiresight/ui/tabs/history_tab.py`:

```python
"""History tab: 220px list on the left + detail view on the right.

Selecting a row loads that entry's markdown into the detail OutputView.
Resend re-fires the entry as a new request; the wiring is done in
MainWindow (this tab only emits resend_requested(entry)).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.history_store import HistoryEntry, HistoryStore
from spiresight.ui.widgets.output_view import OutputView


class HistoryTab(QWidget):
    resend_requested = Signal(object)   # HistoryEntry

    def __init__(
        self,
        store: HistoryStore,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._locale = locale

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        # left: list
        left = QWidget()
        left.setFixedWidth(220)
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        left_l.addWidget(self._list)
        row.addWidget(left)

        # right: detail with Resend / Copy / placeholder header
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(4)

        bar = QHBoxLayout()
        self._resend_btn = QPushButton(locale.get("history.resend"))
        self._resend_btn.clicked.connect(self._on_resend)
        self._copy_btn = QPushButton(locale.get("history.copy_md"))
        self._copy_btn.clicked.connect(self._on_copy)
        bar.addWidget(self._resend_btn)
        bar.addWidget(self._copy_btn)
        bar.addStretch(1)
        right_l.addLayout(bar)

        self._detail = OutputView()
        right_l.addWidget(self._detail, stretch=1)

        self._empty_label = QLabel(locale.get("history.empty"))
        self._empty_label.setStyleSheet("color:#6e7a89;")
        right_l.addWidget(self._empty_label)

        row.addWidget(right, stretch=1)

        store.changed.connect(self._reload)
        locale.changed.connect(self._retranslate)
        self._reload()

    # ── public hooks used by MainWindow ──
    def selected_entry(self) -> HistoryEntry | None:
        idx = self._list.currentRow()
        if idx < 0 or idx >= len(self._entries):
            return None
        return self._entries[idx]

    # ── internals ──
    def _reload(self) -> None:
        self._entries: list[HistoryEntry] = self._store.entries()
        self._list.clear()
        loc = self._locale
        for e in self._entries:
            label = e.prompt_id if e.prompt_id else "custom"
            txt = loc.get(
                "history.row_format",
                time=e.timestamp.strftime("%H:%M"),
                label=label,
                model=e.model_id,
            )
            self._list.addItem(QListWidgetItem(txt))
        self._update_empty_state()
        # auto-select newest after a fresh append
        if self._entries:
            self._list.setCurrentRow(0)

    def _update_empty_state(self) -> None:
        empty = not self._entries
        self._empty_label.setVisible(empty)
        self._detail.setVisible(not empty)
        self._resend_btn.setEnabled(not empty)
        self._copy_btn.setEnabled(not empty)

    def _on_row_changed(self, idx: int) -> None:
        if 0 <= idx < len(self._entries):
            self._detail.load_static(self._entries[idx].markdown)

    def _on_resend(self) -> None:
        entry = self.selected_entry()
        if entry is not None:
            self.resend_requested.emit(entry)

    def _on_copy(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            return
        QGuiApplication.clipboard().setText(entry.markdown)

    def _retranslate(self) -> None:
        loc = self._locale
        self._resend_btn.setText(loc.get("history.resend"))
        self._copy_btn.setText(loc.get("history.copy_md"))
        self._empty_label.setText(loc.get("history.empty"))
        self._reload()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest -q tests/test_history_tab.py
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/tabs/history_tab.py tests/test_history_tab.py
git commit -m "$(cat <<'EOF'
feat(ui): HistoryTab — list + detail + Resend / Copy

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: `ScreenshotTab`

**Files:**
- Create: `src/spiresight/ui/tabs/screenshot_tab.py`
- Create: `tests/test_screenshot_tab.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_screenshot_tab.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.screenshot_store import ScreenshotBundle, ScreenshotStore
from spiresight.ui.tabs.screenshot_tab import ScreenshotTab


# 1x1 transparent PNG bytes (valid header).
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000000500010d0a2db40000000049454e44"
    "ae426082"
)


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def locale(tmp_path: Path) -> UILocale:
    en = tmp_path / "en"
    en.mkdir()
    (en / "ui_strings.yaml").write_text(
        "screenshot:\n"
        "  empty: 'No screenshot yet.'\n"
        "  save_as: 'Save as…'\n"
        "  dims_format: '{w}×{h}'\n",
        encoding="utf-8",
    )
    return UILocale(tmp_path, language="en")


def test_empty_state(qtwidgets_app, locale):
    store = ScreenshotStore()
    tab = ScreenshotTab(store, locale)
    assert tab._empty_label.isVisible() is True
    assert tab._save_btn.isEnabled() is False


def test_renders_after_set(qtwidgets_app, locale):
    store = ScreenshotStore()
    tab = ScreenshotTab(store, locale)
    bundle = ScreenshotBundle(
        frames=(_PNG_1x1,),
        timestamp=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
        width=1, height=1,
    )
    store.set(bundle)
    assert tab._empty_label.isVisible() is False
    assert tab._save_btn.isEnabled() is True
    # one frame label exists
    assert tab._frames_layout.count() >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest -q tests/test_screenshot_tab.py
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `screenshot_tab.py`**

Create `src/spiresight/ui/tabs/screenshot_tab.py`:

```python
"""Tab that displays the latest screenshot(s) sent to the LLM."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.screenshot_store import ScreenshotBundle, ScreenshotStore


class ScreenshotTab(QWidget):
    def __init__(
        self,
        store: ScreenshotStore,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._locale = locale

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(6)

        # header row
        self._header = QHBoxLayout()
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color:#888; font-size:11px;")
        self._save_btn = QPushButton(locale.get("screenshot.save_as"))
        self._save_btn.clicked.connect(self._on_save)
        self._save_btn.setEnabled(False)
        self._header.addWidget(self._info_label)
        self._header.addStretch(1)
        self._header.addWidget(self._save_btn)
        outer.addLayout(self._header)

        # frames area — horizontal scroll
        self._frames_scroll = QScrollArea()
        self._frames_scroll.setWidgetResizable(True)
        self._frames_host = QWidget()
        self._frames_layout = QHBoxLayout(self._frames_host)
        self._frames_layout.setContentsMargins(0, 0, 0, 0)
        self._frames_layout.setSpacing(8)
        self._frames_scroll.setWidget(self._frames_host)
        outer.addWidget(self._frames_scroll, stretch=1)

        # empty state
        self._empty_label = QLabel(locale.get("screenshot.empty"))
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color:#6e7a89;")
        outer.addWidget(self._empty_label, stretch=1)

        store.changed.connect(self._refresh)
        locale.changed.connect(self._retranslate)
        self._refresh()

    def _refresh(self) -> None:
        bundle = self._store.get()
        # clear existing frame widgets
        while self._frames_layout.count():
            item = self._frames_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()

        if bundle is None or not bundle.frames:
            self._info_label.setText("")
            self._save_btn.setEnabled(False)
            self._empty_label.setVisible(True)
            self._frames_scroll.setVisible(False)
            return

        self._empty_label.setVisible(False)
        self._frames_scroll.setVisible(True)
        self._save_btn.setEnabled(True)

        loc = self._locale
        dims = loc.get("screenshot.dims_format", w=bundle.width, h=bundle.height)
        ts = bundle.timestamp.strftime("%H:%M:%S")
        self._info_label.setText(f"{ts} · {dims} · {len(bundle.frames)} frame(s)")

        for i, png in enumerate(bundle.frames):
            pix = QPixmap()
            pix.loadFromData(png)
            # scale to fit-height ~360px max for readability
            if pix.height() > 360:
                pix = pix.scaledToHeight(360, Qt.TransformationMode.SmoothTransformation)
            container = QWidget()
            c_l = QVBoxLayout(container)
            c_l.setContentsMargins(0, 0, 0, 0)
            c_l.setSpacing(2)
            img = QLabel()
            img.setPixmap(pix)
            caption = QLabel(f"#{i + 1}")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setStyleSheet("color:#888; font-size:10px;")
            c_l.addWidget(img)
            c_l.addWidget(caption)
            self._frames_layout.addWidget(container)
        self._frames_layout.addStretch(1)

    def _on_save(self) -> None:
        bundle = self._store.get()
        if bundle is None or not bundle.frames:
            return
        ts = bundle.timestamp.strftime("%Y%m%d-%H%M%S")
        suggested = f"spiresight-{ts}.png"
        path, _ = QFileDialog.getSaveFileName(self, "Save screenshot", suggested, "PNG (*.png)")
        if not path:
            return
        # If multi-frame, save the first frame; v2 could offer a chooser.
        with open(path, "wb") as f:
            f.write(bundle.frames[0])

    def _retranslate(self) -> None:
        loc = self._locale
        self._save_btn.setText(loc.get("screenshot.save_as"))
        self._empty_label.setText(loc.get("screenshot.empty"))
        self._refresh()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest -q tests/test_screenshot_tab.py
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/tabs/screenshot_tab.py tests/test_screenshot_tab.py
git commit -m "$(cat <<'EOF'
feat(ui): ScreenshotTab — latest frames + Save as

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: `LogsTab`

**Files:**
- Create: `src/spiresight/ui/tabs/logs_tab.py`
- Create: `tests/test_logs_tab.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_logs_tab.py`:

```python
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.tabs.logs_tab import LogsTab


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def locale(tmp_path: Path) -> UILocale:
    en = tmp_path / "en"
    en.mkdir()
    (en / "ui_strings.yaml").write_text(
        "logs:\n"
        "  empty: 'No events yet.'\n"
        "  copy_all: 'Copy'\n"
        "  clear: 'Clear'\n",
        encoding="utf-8",
    )
    return UILocale(tmp_path, language="en")


def test_starts_empty(qtwidgets_app, locale):
    tab = LogsTab(locale)
    assert tab._view.toPlainText() == ""


def test_log_appends_newest_on_top(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log("first")
    tab.log("second")
    text = tab._view.toPlainText()
    assert text.splitlines()[0].endswith("second")
    assert text.splitlines()[1].endswith("first")


def test_clear_empties(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log("a")
    tab._clear_btn.click()
    assert tab._view.toPlainText() == ""


def test_ring_buffer_caps_at_200(qtwidgets_app, locale):
    tab = LogsTab(locale)
    for i in range(250):
        tab.log(f"line-{i}")
    assert len(tab._view.toPlainText().splitlines()) == 200
    # oldest evicted: line-0 not present
    assert "line-0\n" not in tab._view.toPlainText()
    assert "line-49" not in tab._view.toPlainText()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest -q tests/test_logs_tab.py
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `logs_tab.py`**

Create `src/spiresight/ui/tabs/logs_tab.py`:

```python
"""Lightweight in-memory log viewer.

Owns its own ring buffer (max 200 entries). MainWindow calls `log()`
on capability mismatches, API errors, etc. — no separate LogsStore
is needed because nothing else needs to read these entries.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from spiresight.prompts.ui_locale import UILocale


MAX_LINES = 200


class LogsTab(QWidget):
    def __init__(
        self,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._locale = locale
        self._buffer: deque[str] = deque(maxlen=MAX_LINES)

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

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setStyleSheet("font-family: ui-monospace, Menlo, monospace; font-size:11.5px;")
        outer.addWidget(self._view, stretch=1)

        locale.changed.connect(self._retranslate)

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._buffer.appendleft(f"[{ts}] {message}")
        self._redraw()

    def _redraw(self) -> None:
        self._view.setPlainText("\n".join(self._buffer))

    def _on_copy(self) -> None:
        QGuiApplication.clipboard().setText(self._view.toPlainText())

    def _on_clear(self) -> None:
        self._buffer.clear()
        self._view.clear()

    def _retranslate(self) -> None:
        loc = self._locale
        self._copy_btn.setText(loc.get("logs.copy_all"))
        self._clear_btn.setText(loc.get("logs.clear"))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest -q tests/test_logs_tab.py
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/tabs/logs_tab.py tests/test_logs_tab.py
git commit -m "$(cat <<'EOF'
feat(ui): LogsTab — in-memory ring buffer log viewer

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 16: `HelpTab` + help markdown content files

**Files:**
- Create: `src/spiresight/ui/tabs/help_tab.py`
- Create: `prompts/locales/en/help.md`
- Create: `prompts/locales/zh/help.md`

- [ ] **Step 1: Create the English help content**

Create `prompts/locales/en/help.md`:

```markdown
# SpireSight — Quick Help

## Global hotkey

`Ctrl/Cmd + Shift + S` re-runs your last quick action with the current
screen.

## Mini-bar mode

Click the mini-bar icon in the top-right (or use the **App** menu) to
collapse the main window into a small always-on-top bar that still
fires quick actions. Click it again to restore.

## Inspect flow

1. Press **📷 Capture** in the sidebar to grab one or more deck-view
   frames (up to 6). Thumbnails appear in a strip; the × on each
   thumbnail removes that frame.
2. Press **✓ Done** to send the frames to the LLM for parsing.
3. The parsed run state appears in the **Run State** tab and is
   automatically attached to every subsequent quick action so the
   advice stays context-aware.
4. **✕ Clear** drops the captured frames and the parsed state.

## Adding an API key

**App → Settings → API Keys** — paste your provider key, save. Keys are
stored in plaintext in your local config file for the MVP; switching
to OS keyring is on the roadmap.

## Slay the Spire II terms

- **Archetype**: a deck identity (Frost, Focus, Strength, etc.) the
  Inspect prompt tries to detect.
- **Usefulness**: how the LLM rates a card for the detected archetype
  — Key / Good / Situational / Skip. Rendered as colored groups in
  the Run State tab.
- **Rarity glyphs**: `○` starter · `●` common · `◆` uncommon/rare.
```

- [ ] **Step 2: Create the Chinese help content**

Create `prompts/locales/zh/help.md`:

```markdown
# SpireSight — 快速帮助

## 全局快捷键

`Ctrl/Cmd + Shift + S` 用当前截图重新触发上一次的 Quick Action。

## 迷你栏模式

点击右上角的迷你栏图标（或菜单 **App → Mini-bar mode**），主窗口会折叠
成一条常驻置顶的小条，仍然能触发 Quick Action。再次点击恢复。

## Inspect 流程

1. 在侧栏按 **📷 Capture** 抓取一张或多张牌组截图（最多 6 张）。
   缩略图会以条带显示，每张缩略图上的 × 可移除该帧。
2. 按 **✓ Done** 将所有帧一起送给 LLM 解析。
3. 解析结果显示在 **Run State** tab，并自动附加到后续每次 Quick Action
   作为上下文。
4. **✕ Clear** 清掉已捕获的帧和已解析的状态。

## 添加 API Key

**App → Settings → API Keys** — 粘贴 Provider Key 并保存。MVP 阶段
Key 以明文存储于本地配置文件；切换到操作系统 keyring 在路线图中。

## 杀戮尖塔 II 术语

- **Archetype（流派）**：Inspect 尝试识别的牌组身份（Frost / Focus /
  Strength 等）。
- **Usefulness（实用度）**：LLM 针对识别出的流派给每张牌打的分
  — Key / Good / Situational / Skip。在 Run State tab 中按颜色分组。
- **稀有度图标**：`○` starter · `●` common · `◆` uncommon/rare。
```

- [ ] **Step 3: Create `help_tab.py`**

Create `src/spiresight/ui/tabs/help_tab.py`:

```python
"""Help tab. Renders prompts/locales/<lang>/help.md via the markdown pipeline."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.markdown.renderer import render as render_markdown


class HelpTab(QWidget):
    def __init__(
        self,
        locales_dir: Path,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._locales_dir = Path(locales_dir)
        self._locale = locale

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._view = QTextBrowser()
        self._view.setOpenExternalLinks(True)
        layout.addWidget(self._view)

        locale.changed.connect(self._reload)
        self._reload()

    def _reload(self) -> None:
        lang = self._locale._language  # private, but stable in this codebase
        candidate = self._locales_dir / lang / "help.md"
        if not candidate.exists():
            candidate = self._locales_dir / "en" / "help.md"
        try:
            md = candidate.read_text(encoding="utf-8")
        except FileNotFoundError:
            md = "# Help\n\nNo help content available."
        self._view.setHtml(render_markdown(md))
```

- [ ] **Step 4: Sanity-import**

```bash
python -c "from spiresight.ui.tabs.help_tab import HelpTab; print('ok')"
```

Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/tabs/help_tab.py prompts/locales/en/help.md prompts/locales/zh/help.md
git commit -m "$(cat <<'EOF'
feat(ui): HelpTab + bilingual help.md content

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4 — Wiring

### Task 17: Extend `ui_strings.yaml` (en + zh)

**Files:**
- Modify: `prompts/locales/en/ui_strings.yaml`
- Modify: `prompts/locales/zh/ui_strings.yaml`

- [ ] **Step 1: Append new keys to the English file**

Open `prompts/locales/en/ui_strings.yaml` and append to the file (preserving the existing `panel:` and `main:` blocks):

```yaml
panel:
  cards_group:
    key: "⭐ Key"
    good: "Good"
    situational: "Situational"
    skip: "Skip"

tab:
  chat: "Chat"
  run_state: "Run State"
  history: "History"
  screenshot: "Shots"
  logs: "Logs"
  help: "Help"

compose:
  placeholder: "Custom context (optional)…"
  send: "Send"
  cancel: "Cancel"
  include_screenshot: "Include screenshot"

history:
  empty: "No history yet. Send a request to get started."
  resend: "Resend"
  copy_md: "Copy"
  row_format: "{time} · {label} · {model}"

screenshot:
  empty: "No screenshot captured yet."
  save_as: "Save as…"
  dims_format: "{w}×{h}"

logs:
  empty: "No events recorded."
  copy_all: "Copy all"
  clear: "Clear"
```

Note: top-level key `panel` already exists in the file. YAML does not
allow duplicate mapping keys — open the file and *merge* the
`cards_group` block under the existing `panel:` map rather than
appending a second `panel:` block at the bottom.

- [ ] **Step 2: Append the equivalent Chinese keys**

Open `prompts/locales/zh/ui_strings.yaml` and merge:

```yaml
panel:
  cards_group:
    key: "⭐ 核心"
    good: "推荐"
    situational: "可选"
    skip: "舍弃"

tab:
  chat: "Chat"
  run_state: "Run State"
  history: "历史"
  screenshot: "截图"
  logs: "日志"
  help: "帮助"

compose:
  placeholder: "可选自定义上下文…"
  send: "发送"
  cancel: "取消"
  include_screenshot: "附截图"

history:
  empty: "暂无历史。发送一次请求开始。"
  resend: "重发"
  copy_md: "复制"
  row_format: "{time} · {label} · {model}"

screenshot:
  empty: "尚未捕获截图。"
  save_as: "另存为…"
  dims_format: "{w}×{h}"

logs:
  empty: "暂无事件。"
  copy_all: "复制全部"
  clear: "清空"
```

Same merge note: keep a single top-level `panel:` key.

- [ ] **Step 3: Verify locale loading**

```bash
python -c "
from pathlib import Path
from spiresight.prompts.ui_locale import UILocale
loc = UILocale(Path('prompts/locales'), language='en')
for k in ['tab.chat','tab.help','compose.send','history.empty',
          'screenshot.save_as','logs.copy_all',
          'panel.cards_group.key','panel.cards_group.skip']:
    print(k, '→', loc.get(k))
"
```

Expected: each line prints the English string. Repeat with `language='zh'` to confirm the Chinese file resolves the same keys.

- [ ] **Step 4: Commit**

```bash
git add prompts/locales/en/ui_strings.yaml prompts/locales/zh/ui_strings.yaml
git commit -m "$(cat <<'EOF'
feat(i18n): add tab / compose / history / screenshot / logs / card group keys

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 18: Rebuild `MainWindow`

**Files:**
- Modify: `src/spiresight/ui/windows/main_window.py` (replace entire file)

This is the most invasive task. The structure is: sidebar (Provider /
PromptPanel / InspectPanel) on the left, `TabWidget` on the right
with `ComposeDock` docked below it. All inference paths route through
helpers that:

1. switch to the Chat tab,
2. reset the OutputView,
3. set the compose dock to streaming mode,
4. on `finished_ok`, append a `HistoryEntry`, push the screenshot bundle, mark non-active tabs dirty.

- [ ] **Step 1: Replace `main_window.py` contents**

Overwrite `src/spiresight/ui/windows/main_window.py` with:

```python
"""Primary application window — tabbed layout.

Sidebar: Provider / Quick Actions / Inspect.
Right pane: TabWidget [Chat | Run State | History | Screenshot | Logs | Help]
            with a persistent ComposeDock anchored at the bottom.
"""
from __future__ import annotations

from datetime import datetime, timezone

from PIL import Image
import io

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout, QMainWindow, QMessageBox, QPushButton, QStatusBar,
    QVBoxLayout, QWidget,
)

from spiresight.capture.screen import ScreenCapture
from spiresight.config.schema import AppConfig
from spiresight.config.store import ConfigStore
from spiresight.core.inspect_session import InspectSession
from spiresight.core.request import InferenceRequest
from spiresight.core.run_state import RunState
from spiresight.core.runner import InferenceRunner
from spiresight.llm import registry
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import (
    AuthError, MissingAPIKey, MissingCapabilityError, NetworkError, RateLimitError,
)
from spiresight.prompts.loader import PromptLoader
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.history_store import HistoryEntry, HistoryStore
from spiresight.ui.state.run_state_store import RunStateStore
from spiresight.ui.state.screenshot_store import ScreenshotBundle, ScreenshotStore
from spiresight.ui.tabs.chat_tab import ChatTab
from spiresight.ui.tabs.help_tab import HelpTab
from spiresight.ui.tabs.history_tab import HistoryTab
from spiresight.ui.tabs.logs_tab import LogsTab
from spiresight.ui.tabs.run_state_tab import RunStateTab
from spiresight.ui.tabs.screenshot_tab import ScreenshotTab
from spiresight.ui.tabs.tab_widget import TabWidget
from spiresight.ui.theme import icon_path
from spiresight.ui.widgets.compose_dock import ComposeDock
from spiresight.ui.widgets.inspect_panel import InspectPanel
from spiresight.ui.widgets.mini_bar import MiniBar
from spiresight.ui.widgets.prompt_panel import PromptPanel
from spiresight.ui.widgets.provider_picker import ProviderPicker
from spiresight.ui.windows.settings_dialog import SettingsDialog
from spiresight.ui.workers.inference_worker import InferenceWorker
from spiresight.ui.workers.inspect_worker import InspectWorker


_TAB_CHAT, _TAB_RUN, _TAB_HISTORY, _TAB_SHOT, _TAB_LOGS, _TAB_HELP = range(6)


class MainWindow(QMainWindow):

    fire_action_signal = Signal()

    def __init__(self, config: AppConfig, store: ConfigStore, loader: PromptLoader) -> None:
        super().__init__()
        self.setWindowTitle("SpireSight")
        self.resize(1080, 640)
        self._config = config
        self._store = store
        self._loader = loader
        self._capture = ScreenCapture()
        self._worker: InferenceWorker | None = None
        self._mini_bar: MiniBar | None = None

        # stores
        self._run_state_store = RunStateStore(self)
        self._history_store = HistoryStore(self)
        self._screenshot_store = ScreenshotStore(self)
        self._inspect_session = InspectSession(self)
        self._ui_locale = UILocale(
            self._loader._root / "locales", self._config.language, parent=self
        )
        self._inspect_worker: InspectWorker | None = None

        # streaming-state bookkeeping for HistoryEntry assembly
        self._last_screenshot_png: bytes | None = None
        self._last_request: InferenceRequest | None = None
        self._stream_buffer: list[str] = []

        self.fire_action_signal.connect(self.fire_last_action)
        self._apply_always_on_top()

        # ── sidebar ──
        self._picker = ProviderPicker()
        self._picker.set_active(config.active_provider, config.active_model)
        self._picker.selection_changed.connect(self._on_picker_changed)

        self._prompt_panel = PromptPanel(loader)
        self._prompt_panel.action_clicked.connect(self._on_action)

        self._inspect_panel = InspectPanel(self._inspect_session, self._ui_locale)
        self._inspect_panel.capture_requested.connect(self._on_capture_requested)
        self._inspect_panel.done_requested.connect(self._on_done_requested)
        self._inspect_panel.clear_requested.connect(self._on_clear_requested)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(12, 12, 12, 12)
        sb_layout.addWidget(self._picker)
        sb_layout.addSpacing(12)
        sb_layout.addWidget(self._prompt_panel)
        sb_layout.addSpacing(12)
        sb_layout.addWidget(self._inspect_panel, stretch=1)
        sidebar.setFixedWidth(280)

        # ── right pane: corner buttons + tabs + compose ──
        self._pin_btn = QPushButton()
        self._pin_btn.setCheckable(True)
        self._pin_btn.setObjectName("corner-pin")
        self._pin_btn.setChecked(config.always_on_top)
        self._pin_btn.setIconSize(QSize(18, 18))
        self._pin_btn.setToolTip("Always on top")
        self._pin_btn.setFixedSize(28, 28)
        self._pin_btn.clicked.connect(self._toggle_pin)
        self._update_pin_icon()

        self._mini_mode_btn = QPushButton()
        self._mini_mode_btn.setObjectName("corner-pin")
        self._mini_mode_btn.setIcon(QIcon(icon_path("mini_mode")))
        self._mini_mode_btn.setIconSize(QSize(18, 18))
        self._mini_mode_btn.setToolTip("Switch to mini-bar mode")
        self._mini_mode_btn.setFixedSize(28, 28)
        self._mini_mode_btn.clicked.connect(self._toggle_mini_bar)

        corner_row = QHBoxLayout()
        corner_row.setContentsMargins(0, 0, 0, 0)
        corner_row.addStretch(1)
        corner_row.addWidget(self._mini_mode_btn)
        corner_row.addWidget(self._pin_btn)

        # tabs
        self._tabs = TabWidget()
        self._chat_tab = ChatTab()
        self._run_state_tab = RunStateTab(self._run_state_store, self._ui_locale)
        self._history_tab = HistoryTab(self._history_store, self._ui_locale)
        self._history_tab.resend_requested.connect(self._on_resend)
        self._screenshot_tab = ScreenshotTab(self._screenshot_store, self._ui_locale)
        self._logs_tab = LogsTab(self._ui_locale)
        self._help_tab = HelpTab(self._loader._root / "locales", self._ui_locale)

        loc = self._ui_locale
        self._tabs.addTab(self._chat_tab,       loc.get("tab.chat"))
        self._tabs.addTab(self._run_state_tab,  loc.get("tab.run_state"))
        self._tabs.addTab(self._history_tab,    loc.get("tab.history"))
        self._tabs.addTab(self._screenshot_tab, loc.get("tab.screenshot"))
        self._tabs.addTab(self._logs_tab,       loc.get("tab.logs"))
        self._tabs.addTab(self._help_tab,       loc.get("tab.help"))

        # mark tabs dirty on store updates (when not the current tab)
        self._run_state_store.changed.connect(
            lambda _s: self._tabs.mark_dirty(_TAB_RUN)
        )
        self._history_store.changed.connect(
            lambda: self._tabs.mark_dirty(_TAB_HISTORY)
        )
        self._screenshot_store.changed.connect(
            lambda: self._tabs.mark_dirty(_TAB_SHOT)
        )

        # compose dock
        self._compose = ComposeDock(self._ui_locale, config.include_screenshot_default)
        self._compose.send_clicked.connect(self._on_compose_send)
        self._compose.cancel_clicked.connect(self._on_cancel)
        self._compose.include_screenshot_toggled.connect(self._on_screenshot_toggled)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(6)
        right_layout.addLayout(corner_row)
        right_layout.addWidget(self._tabs, stretch=1)
        right_layout.addWidget(self._compose)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.addWidget(sidebar)
        body_layout.addWidget(right, stretch=1)
        self.setCentralWidget(body)

        # menubar
        menu = self.menuBar().addMenu("&App")
        menu.addAction("Settings…", self._open_settings)
        menu.addAction("Mini-bar mode", self._toggle_mini_bar)
        menu.addSeparator()
        menu.addAction("Quit", self.close)

        self.setStatusBar(QStatusBar())
        self._refresh_inspect_availability()
        self._ui_locale.changed.connect(self._retranslate)

    # ─── lifecycle helpers ───────────────────────────────────────

    def _toggle_pin(self) -> None:
        pinned = self._pin_btn.isChecked()
        self._config.always_on_top = pinned
        self._store.save(self._config)
        self._apply_always_on_top()
        self._update_pin_icon()

    def _update_pin_icon(self) -> None:
        icon_name = "pin_filled" if self._config.always_on_top else "pin_outline"
        self._pin_btn.setIcon(QIcon(icon_path(icon_name)))

    def _apply_always_on_top(self) -> None:
        handle = self.windowHandle()
        if handle is not None:
            handle.setFlag(Qt.WindowType.WindowStaysOnTopHint, self._config.always_on_top)
        else:
            flags = self.windowFlags()
            if self._config.always_on_top:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            else:
                flags &= ~Qt.WindowType.WindowStaysOnTopHint
            self.setWindowFlags(flags)

    def _on_picker_changed(self, provider: str, model_id: str) -> None:
        if provider:
            self._config.active_provider = provider
        if model_id:
            self._config.active_model = model_id
        self._store.save(self._config)
        self._refresh_inspect_availability()

    def _on_screenshot_toggled(self, value: bool) -> None:
        self._config.include_screenshot_default = value
        self._store.save(self._config)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._config, self)
        if dlg.exec():
            self._store.save(self._config)
            self._loader.reload(language=self._config.language)
            self._ui_locale.set_language(self._config.language)
            self._prompt_panel.rebuild()
            self._apply_always_on_top()
            self.show()

    def _toggle_mini_bar(self) -> None:
        if self._mini_bar is None:
            self._mini_bar = MiniBar(self._loader, hotkey_hint=self._config.hotkey,
                                      pinned=self._config.always_on_top)
            self._mini_bar.action_clicked.connect(self._on_action)
            self._mini_bar.expand_requested.connect(self._exit_mini_bar)
        elif self._mini_bar.is_pinned != self._config.always_on_top:
            self._mini_bar._toggle_pin()
        self.hide()
        self._mini_bar.show()
        self._config.mini_bar_mode = True
        self._store.save(self._config)

    def _exit_mini_bar(self) -> None:
        if self._mini_bar is not None:
            self._config.always_on_top = self._mini_bar.is_pinned
            self._store.save(self._config)
            self._apply_always_on_top()
            self._update_pin_icon()
            self._pin_btn.setChecked(self._config.always_on_top)
            self._mini_bar.hide()
        self.show()
        self._config.mini_bar_mode = False
        self._store.save(self._config)

    def _retranslate(self) -> None:
        loc = self._ui_locale
        self._tabs.set_label(_TAB_CHAT,    loc.get("tab.chat"))
        self._tabs.set_label(_TAB_RUN,     loc.get("tab.run_state"))
        self._tabs.set_label(_TAB_HISTORY, loc.get("tab.history"))
        self._tabs.set_label(_TAB_SHOT,    loc.get("tab.screenshot"))
        self._tabs.set_label(_TAB_LOGS,    loc.get("tab.logs"))
        self._tabs.set_label(_TAB_HELP,    loc.get("tab.help"))
        self._refresh_inspect_availability()

    # ─── inference flow ──────────────────────────────────────────

    def fire_last_action(self) -> None:
        if self._config.last_used_prompt_id:
            self._on_action(self._config.last_used_prompt_id)

    def _on_compose_send(self, text: str, include_screenshot: bool) -> None:
        actions = self._loader.quick_actions()
        if not actions:
            return
        action_id = self._config.last_used_prompt_id or actions[0].id
        # honor compose dock's screenshot toggle for this send
        self._on_action(
            action_id,
            custom_text_override=text,
            include_screenshot_override=include_screenshot,
        )

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

        request = InferenceRequest(
            prompt_id=action_id,
            custom_text=custom_text,
            include_screenshot=include_screenshot,
        )

        # capture screenshot up-front so we can pass the same bytes into
        # both the request and the ScreenshotStore / HistoryEntry
        screenshot_png: bytes | None = None
        if include_screenshot:
            try:
                screenshot_png = self._capture.grab_primary()
            except Exception as exc:  # noqa: BLE001
                self._log(f"capture failed: {exc}")
                screenshot_png = None

        # push to ScreenshotStore so the Screenshot tab updates
        if screenshot_png is not None:
            w, h = _png_dims(screenshot_png)
            self._screenshot_store.set(ScreenshotBundle(
                frames=(screenshot_png,),
                timestamp=datetime.now(tz=timezone.utc),
                width=w, height=h,
            ))

        # bookkeeping for HistoryEntry on finish
        self._last_screenshot_png = screenshot_png
        self._last_request = request
        self._stream_buffer = []

        runner = InferenceRunner(
            config=self._config,
            prompt_loader=self._loader,
            provider_factory=registry.get,
            screen_capture=_PrecapturedScreen(screenshot_png) if screenshot_png else self._capture,
            run_state_store=self._run_state_store,
        )

        # UI: switch to Chat, reset, mark streaming
        self._tabs.setCurrentIndex(_TAB_CHAT)
        self._chat_tab.reset()
        self._compose.set_streaming(True)
        self.statusBar().showMessage("Streaming…")

        self._worker = InferenceWorker(runner, request, self)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_chunk(self, text: str) -> None:
        self._stream_buffer.append(text)
        self._chat_tab.append_delta(text)

    def _on_resend(self, entry: HistoryEntry) -> None:
        # Resend uses the stored screenshot if present; otherwise capture fresh.
        screenshot_png = entry.screenshot_png
        if entry.include_screenshot and screenshot_png is None:
            try:
                screenshot_png = self._capture.grab_primary()
            except Exception as exc:  # noqa: BLE001
                self._log(f"resend capture failed: {exc}")
                screenshot_png = None

        request = InferenceRequest(
            prompt_id=entry.prompt_id,
            custom_text=entry.custom_text,
            include_screenshot=entry.include_screenshot and screenshot_png is not None,
        )

        if screenshot_png is not None:
            w, h = _png_dims(screenshot_png)
            self._screenshot_store.set(ScreenshotBundle(
                frames=(screenshot_png,),
                timestamp=datetime.now(tz=timezone.utc),
                width=w, height=h,
            ))

        self._last_screenshot_png = screenshot_png
        self._last_request = request
        self._stream_buffer = []

        runner = InferenceRunner(
            config=self._config,
            prompt_loader=self._loader,
            provider_factory=registry.get,
            screen_capture=_PrecapturedScreen(screenshot_png) if screenshot_png else self._capture,
            run_state_store=self._run_state_store,
        )
        self._tabs.setCurrentIndex(_TAB_CHAT)
        self._chat_tab.reset()
        self._compose.set_streaming(True)
        self.statusBar().showMessage("Streaming…")
        self._worker = InferenceWorker(runner, request, self)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _on_finished(self) -> None:
        self._chat_tab.finalize()
        self._compose.set_streaming(False)
        self.statusBar().showMessage("Done.", 3000)

        if self._last_request is not None:
            entry = HistoryEntry(
                timestamp=datetime.now(tz=timezone.utc),
                prompt_id=self._last_request.prompt_id,
                custom_text=self._last_request.custom_text,
                model_id=self._config.active_model,
                include_screenshot=self._last_request.include_screenshot,
                screenshot_png=self._last_screenshot_png,
                markdown="".join(self._stream_buffer),
            )
            self._history_store.append(entry)

        self._last_request = None
        self._last_screenshot_png = None
        self._stream_buffer = []

    def _on_failed(self, exc: Exception) -> None:
        self._chat_tab.finalize()
        self._compose.set_streaming(False)
        msg = str(exc) or exc.__class__.__name__
        self._log(f"{exc.__class__.__name__}: {msg}")
        if isinstance(exc, MissingAPIKey):
            QMessageBox.warning(self, "API key required",
                                "Add your API key under App → Settings → API Keys.")
        elif isinstance(exc, MissingCapabilityError):
            missing = ", ".join(sorted(c.value for c in exc.missing))
            QMessageBox.warning(self, "Model can't do that",
                                f"Model '{exc.model}' lacks: {missing}.")
        elif isinstance(exc, AuthError):
            QMessageBox.warning(self, "Authentication failed",
                                "The API key was rejected. Check it in Settings.")
        elif isinstance(exc, RateLimitError):
            retry = f" Retry in {exc.retry_after:.0f}s." if exc.retry_after else ""
            self.statusBar().showMessage(f"Rate limited.{retry}", 8000)
        elif isinstance(exc, NetworkError):
            self.statusBar().showMessage(f"Network error: {exc}", 8000)
        else:
            self.statusBar().showMessage(f"Error: {exc}", 8000)

        self._last_request = None
        self._last_screenshot_png = None
        self._stream_buffer = []

    def _log(self, message: str) -> None:
        self._logs_tab.log(message)

    # ─── inspect flow ────────────────────────────────────────────

    def _on_capture_requested(self) -> None:
        loc = self._ui_locale
        try:
            png = self._capture.grab_primary()
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(loc.get("main.capture_failed", error=str(exc)), 5000)
            self._log(f"capture failed: {exc}")
            return
        try:
            self._inspect_session.add_frame(png)
        except RuntimeError as exc:
            self.statusBar().showMessage(str(exc), 5000)
            return
        self.statusBar().showMessage(
            loc.get("main.captured_frame", count=self._inspect_session.count), 2000
        )

    def _on_done_requested(self) -> None:
        loc = self._ui_locale
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
        self._inspect_panel.set_busy(True)
        self.statusBar().showMessage(loc.get("main.inspecting", count=len(frames)))

        self._inspect_worker = InspectWorker(runner, frames, self)
        self._inspect_worker.ready.connect(self._on_inspect_ready)
        self._inspect_worker.failed.connect(self._on_inspect_failed)
        self._inspect_worker.start()

    def _on_clear_requested(self) -> None:
        self._inspect_session.clear()
        self._run_state_store.clear()
        self.statusBar().showMessage(self._ui_locale.get("main.run_state_cleared"), 2000)

    def _on_inspect_ready(self, state: RunState) -> None:
        self._run_state_store.set(state)
        self._inspect_session.clear()
        self._inspect_panel.set_busy(False)
        self.statusBar().showMessage(self._ui_locale.get("main.run_state_captured"), 3000)
        self._inspect_worker = None

    def _on_inspect_failed(self, exc: Exception) -> None:
        loc = self._ui_locale
        self._inspect_panel.set_busy(False)
        self._log(f"inspect failed: {exc.__class__.__name__}: {exc}")
        if isinstance(exc, MissingCapabilityError):
            missing = ", ".join(sorted(c.value for c in exc.missing))
            self.statusBar().showMessage(loc.get("main.inspect_needs", missing=missing), 8000)
        elif isinstance(exc, ValueError):
            self.statusBar().showMessage(loc.get("main.inspect_malformed"), 8000)
        else:
            self.statusBar().showMessage(loc.get("main.inspect_failed", error=str(exc)), 8000)
        self._inspect_worker = None

    def _refresh_inspect_availability(self) -> None:
        loc = self._ui_locale
        try:
            provider_cfg = self._config.providers.get(self._config.active_provider)
            if provider_cfg is None:
                self._inspect_panel.set_capture_enabled(False, loc.get("main.no_provider"))
                return
            provider = registry.get(self._config.active_provider, provider_cfg)
            model = next(
                (m for m in provider.list_models() if m.id == self._config.active_model), None
            )
            if model is None:
                self._inspect_panel.set_capture_enabled(False, loc.get("main.no_model"))
                return
            needed = {Capability.VISION, Capability.JSON_MODE}
            missing = needed - set(model.capabilities)
            if missing:
                names = ", ".join(sorted(c.value for c in missing))
                self._inspect_panel.set_capture_enabled(False, loc.get("main.lacks_caps", caps=names))
            else:
                self._inspect_panel.set_capture_enabled(True)
        except Exception:  # noqa: BLE001
            self._inspect_panel.set_capture_enabled(True)


# ── helpers ──

def _png_dims(png: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(png)) as im:
        return im.width, im.height


class _PrecapturedScreen:
    """Adapter so InferenceRunner sees a pre-captured PNG instead of grabbing again."""

    def __init__(self, png: bytes) -> None:
        self._png = png

    def grab_primary(self) -> bytes:
        return self._png
```

- [ ] **Step 2: Run the full test suite**

```bash
pytest -q
```

Expected: all tests pass. If a `tests/test_main_window.py` exists from earlier work, it may need its `RunStatePanel` import updated to `InspectPanel` — read the file and adjust signal-emission assertions accordingly.

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/ui/windows/main_window.py
git commit -m "$(cat <<'EOF'
feat(ui): rewire MainWindow to tabbed right pane + ComposeDock

Sidebar splits into Provider / Quick Actions / InspectPanel. Right pane
is now a TabWidget with [Chat, Run State, History, Screenshot, Logs,
Help] plus a persistent ComposeDock. Sending a request auto-switches
to Chat; finishing records a HistoryEntry; store updates mark non-
active tabs with a dirty dot.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 19: Manual smoke test

**Files:** none

- [ ] **Step 1: Launch the app**

```bash
source .venv/bin/activate && python -m spiresight
```

- [ ] **Step 2: Verify the layout**

Check that all of the following are visible and behave as described:

1. Left sidebar (280px): Provider picker → Quick Actions → InspectPanel (with empty thumbnail strip + three buttons).
2. Right pane: corner pin / mini-bar buttons → six-tab bar `[Chat | Run State | History | Shots | Logs | Help]` → tab content area → Compose dock (text area + Include screenshot checkbox + Send button).
3. Chat tab is the active default.
4. Help tab renders the help markdown via the new pipeline (verify code blocks / headings render with the dark theme).

- [ ] **Step 3: Run an inference**

With an API key configured, click a quick action (or type into Compose and click Send). Verify:

- Tab auto-switches to Chat.
- Output streams in.
- Send button reads "Cancel" while streaming.
- When the stream finishes, History tab gets a dirty-dot badge; clicking History shows the new entry at top and the detail pane renders it.
- Screenshot tab shows the screenshot that was sent.

- [ ] **Step 4: Run an inspect**

Press Capture in the sidebar a few times; verify thumbnails appear. Press Done. Verify Run State tab gets a dirty dot, clicking it shows the parsed cards grouped by usefulness with colored backgrounds. Press Clear and verify both the thumbnail strip and the Run State tab content clear.

- [ ] **Step 5: Resend**

Open History, select an entry, click Resend. Verify the stream replays into Chat without re-grabbing the screen (or with a fresh capture if the entry had `include_screenshot=False`).

- [ ] **Step 6: Language switch**

Open Settings, switch language between English and Chinese. Verify tab labels, compose placeholder, capture button labels, and Help tab content all update.

- [ ] **Step 7: Mini-bar**

Click the mini-mode button. Verify the main window collapses to the mini-bar, quick actions still fire, and clicking back expands the window with all tabs intact.

- [ ] **Step 8: Final commit (if any docstring / styling tweaks were made during smoke test)**

If smoke testing surfaced no changes, skip this step. Otherwise:

```bash
git add -p
git commit -m "$(cat <<'EOF'
fix(ui): smoke-test follow-ups

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Verification checklist (run before marking the plan complete)

- [ ] `pytest -q` passes from the repo root with the project venv activated.
- [ ] `python -m spiresight` launches and the six tabs / compose dock all render.
- [ ] `git log --oneline` shows one commit per task (no squashed mega-commits).
- [ ] No regressions in mini-bar mode.
- [ ] No new dependencies beyond `markdown-it-py`, `mdit-py-plugins`, `Pygments`.
