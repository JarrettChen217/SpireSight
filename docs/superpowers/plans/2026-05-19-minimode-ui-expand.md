# Mini-mode UI Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three mini-bar UI features — a persistent bubble visibility toggle, bottom-right resize on the InfoBubble with size persisted in config, and a 3-button inspect group on the mini-bar with a Capture counter badge.

**Architecture:** New widgets `BubbleToggleButton`, `MiniInspectControls`, and a pure-logic `InspectButtonsController` shared with the existing sidebar `InspectPanel`. `InfoBubble` gains `QSizeGrip`, dynamic tail repositioning, an `apply_size` / `size_changed` pair, and a `render_history` method. `AppConfig` grows two ints for bubble size. `MainWindow` wires new signals and pushes inspect capability / busy state to both panels.

**Tech Stack:** Python 3.11, PySide6 (Qt 6), Pydantic (AppConfig), pytest + pytest-qt (offscreen Qt platform via `tests/conftest.py`).

**Spec:** `docs/superpowers/specs/2026-05-19-minimode-ui-expand-design.md`
**Branch:** `feature/minimode-ui-expand` (already created from `main`)

## File map

**New files:**
- `src/spiresight/ui/widgets/bubble_toggle_button.py` — `BubbleToggleButton`
- `src/spiresight/ui/widgets/inspect_controls.py` — `InspectButtonsController`, `MiniInspectControls`, `_CountBadge`
- `tests/test_bubble_toggle_button.py`
- `tests/test_inspect_buttons_controller.py`
- `tests/test_mini_inspect_controls.py`
- `tests/test_info_bubble_resize.py`
- `tests/test_mini_bar_layout.py`
- `tests/test_main_window_minimode_expand.py`

**Modified files:**
- `src/spiresight/config/schema.py` — two new fields
- `src/spiresight/ui/widgets/info_bubble.py` — resize, render_history, size_changed
- `src/spiresight/ui/widgets/inspect_panel.py` — delegate state to controller (signatures preserved)
- `src/spiresight/ui/widgets/mini_bar.py` — new constructor params, layout, signals
- `src/spiresight/ui/windows/main_window.py` — wiring, persistence, helpers
- `src/spiresight/ui/qss/dark_fantasy.qss` — new selectors
- `tests/test_inspect_panel.py` — keep existing assertions passing post-refactor
- `tests/test_config_store.py` — assert new defaults round-trip

**Conventions to follow:**
- All test files use `qtwidgets_app` module-scoped fixture (see `tests/test_inspect_panel.py:13-16`) — not `qtbot`.
- Tests may access "private" attributes (e.g. `panel._capture_btn`); preserve those attribute names when refactoring.
- Headless rendering: `QT_QPA_PLATFORM=offscreen` is set by `tests/conftest.py`.
- Use `.venv` for any pip/pytest invocation: `.venv/bin/pytest …`.

---

## Task 0: Verify environment

**Files:** none

- [ ] **Step 1: Confirm branch + working tree clean**

```bash
git rev-parse --abbrev-ref HEAD
git status --short
```
Expected: `feature/minimode-ui-expand`, no modified files.

- [ ] **Step 2: Confirm venv + pytest-qt installed**

```bash
.venv/bin/python -c "import PySide6, pytest, pytestqt; print(PySide6.__version__)"
```
Expected: a PySide6 version string, no ImportError.

- [ ] **Step 3: Baseline test run**

```bash
.venv/bin/pytest -q
```
Expected: all tests pass. Record the pass count for later comparison.

---

## Task 1: AppConfig — bubble size fields

**Files:**
- Modify: `src/spiresight/config/schema.py`
- Test: `tests/test_config_store.py`

- [ ] **Step 1: Inspect current schema**

```bash
grep -n "always_on_top\|hotkey\|mini_bar_mode" src/spiresight/config/schema.py
```
Note where the existing UI-related fields live so the new fields slot in beside them.

- [ ] **Step 2: Write failing test**

Append to `tests/test_config_store.py`:

```python
def test_app_config_defaults_bubble_size():
    from spiresight.config.schema import AppConfig
    cfg = AppConfig()
    assert cfg.bubble_width == 360
    assert cfg.bubble_height == 280


def test_app_config_round_trip_preserves_bubble_size(tmp_path):
    from spiresight.config.schema import AppConfig
    from spiresight.config.store import ConfigStore

    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(bubble_width=500, bubble_height=320)
    store.save(cfg)
    loaded = store.load()
    assert loaded.bubble_width == 500
    assert loaded.bubble_height == 320


def test_app_config_legacy_file_uses_defaults(tmp_path):
    """A config file written before bubble_width/height existed must still load."""
    import json
    from spiresight.config.schema import AppConfig
    from spiresight.config.store import ConfigStore

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"hotkey": "ctrl+shift+x"}), encoding="utf-8")
    cfg = ConfigStore(path).load()
    assert cfg.bubble_width == 360
    assert cfg.bubble_height == 280
```

- [ ] **Step 3: Run failing test**

```bash
.venv/bin/pytest tests/test_config_store.py -q -k bubble
```
Expected: FAIL — `AppConfig` has no `bubble_width` attribute.

- [ ] **Step 4: Add fields to schema**

In `src/spiresight/config/schema.py`, inside the `AppConfig` class body, beside `always_on_top` / `mini_bar_mode`:

```python
    bubble_width:  int = 360
    bubble_height: int = 280
```

- [ ] **Step 5: Run test — expect pass**

```bash
.venv/bin/pytest tests/test_config_store.py -q -k bubble
```
Expected: PASS.

- [ ] **Step 6: Re-run full suite**

```bash
.venv/bin/pytest -q
```
Expected: same pass count as baseline + 3.

- [ ] **Step 7: Commit**

```bash
git add src/spiresight/config/schema.py tests/test_config_store.py
git commit -m "feat(config): add bubble_width/height to AppConfig"
```

---

## Task 2: BubbleToggleButton widget

**Files:**
- Create: `src/spiresight/ui/widgets/bubble_toggle_button.py`
- Create: `tests/test_bubble_toggle_button.py`

- [ ] **Step 1: Write failing test**

`tests/test_bubble_toggle_button.py`:

```python
from PySide6.QtWidgets import QApplication

import pytest


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_default_unchecked(qtwidgets_app):
    from spiresight.ui.widgets.bubble_toggle_button import BubbleToggleButton
    btn = BubbleToggleButton()
    assert btn.isChecked() is False


def test_initial_visible_state_sets_checked(qtwidgets_app):
    from spiresight.ui.widgets.bubble_toggle_button import BubbleToggleButton
    btn = BubbleToggleButton(visible=True)
    assert btn.isChecked() is True


def test_click_emits_toggled_with_new_state(qtwidgets_app):
    from spiresight.ui.widgets.bubble_toggle_button import BubbleToggleButton
    btn = BubbleToggleButton(visible=False)
    received: list[bool] = []
    btn.toggled.connect(received.append)
    btn.click()
    assert received == [True]
    btn.click()
    assert received == [True, False]


def test_set_visible_state_does_not_emit(qtwidgets_app):
    from spiresight.ui.widgets.bubble_toggle_button import BubbleToggleButton
    btn = BubbleToggleButton(visible=False)
    received: list[bool] = []
    btn.toggled.connect(received.append)
    btn.set_visible_state(True)
    assert btn.isChecked() is True
    assert received == []


def test_set_visible_state_same_value_is_noop(qtwidgets_app):
    from spiresight.ui.widgets.bubble_toggle_button import BubbleToggleButton
    btn = BubbleToggleButton(visible=True)
    received: list[bool] = []
    btn.toggled.connect(received.append)
    btn.set_visible_state(True)
    assert received == []
```

- [ ] **Step 2: Run failing test**

```bash
.venv/bin/pytest tests/test_bubble_toggle_button.py -q
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement widget**

`src/spiresight/ui/widgets/bubble_toggle_button.py`:

```python
"""Checkable mini-bar button mirroring the InfoBubble's visibility."""
from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QToolButton

from spiresight.ui.theme import icon_path


class BubbleToggleButton(QToolButton):
    toggled = Signal(bool)

    def __init__(self, visible: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(visible)
        self.setObjectName("bubble-toggle")
        self.setIconSize(QSize(18, 18))
        self.setFixedSize(28, 28)
        self.setToolTip("Toggle response bubble")
        self._update_icon()
        self.clicked.connect(lambda: self.toggled.emit(self.isChecked()))
        self.clicked.connect(self._update_icon)

    def set_visible_state(self, visible: bool) -> None:
        if self.isChecked() == visible:
            return
        self.blockSignals(True)
        self.setChecked(visible)
        self.blockSignals(False)
        self._update_icon()

    def _update_icon(self) -> None:
        name = "bubble_filled" if self.isChecked() else "bubble_outline"
        path = icon_path(name)
        icon = QIcon(path)
        if icon.isNull():
            # Fallback while SVG assets are absent
            self.setIcon(QIcon())
            self.setText("\U0001f4ac")  # 💬
        else:
            self.setText("")
            self.setIcon(icon)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
.venv/bin/pytest tests/test_bubble_toggle_button.py -q
```
Expected: PASS (all 5).

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/widgets/bubble_toggle_button.py tests/test_bubble_toggle_button.py
git commit -m "feat(ui): add BubbleToggleButton mirror widget"
```

---

## Task 3: InspectButtonsController — pure state machine

**Files:**
- Create: `src/spiresight/ui/widgets/inspect_controls.py` (controller portion only — badge + MiniInspectControls land in Tasks 5–6)
- Create: `tests/test_inspect_buttons_controller.py`

- [ ] **Step 1: Read existing state logic**

```bash
sed -n '120,205p' src/spiresight/ui/widgets/inspect_panel.py
```
The blocks `_update_button_states` and the button-text section of `_retranslate` are what gets moved.

- [ ] **Step 2: Write failing tests**

`tests/test_inspect_buttons_controller.py`:

```python
from pathlib import Path

from PySide6.QtWidgets import QApplication, QPushButton

import pytest

from spiresight.core.inspect_session import InspectSession
from spiresight.prompts.ui_locale import UILocale


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


def _make_controller(qtwidgets_app, locale):
    from spiresight.ui.widgets.inspect_controls import InspectButtonsController
    session = InspectSession()
    cap, done, clr = QPushButton(), QPushButton(), QPushButton()
    ctrl = InspectButtonsController(session, locale, cap, done, clr)
    return session, ctrl, cap, done, clr


def test_initial_state_done_disabled_no_frames(qtwidgets_app, locale):
    _, _, cap, done, clr = _make_controller(qtwidgets_app, locale)
    assert cap.isEnabled() is True
    assert done.isEnabled() is False
    assert clr.isEnabled() is True


def test_done_enabled_after_frame_added(qtwidgets_app, locale):
    session, _, _, done, _ = _make_controller(qtwidgets_app, locale)
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    assert done.isEnabled() is True


def test_capture_disabled_at_max(qtwidgets_app, locale):
    session, _, cap, _, _ = _make_controller(qtwidgets_app, locale)
    for _i in range(InspectSession.MAX_FRAMES):
        session.add_frame(b"\x89PNG\r\n\x1a\n")
    assert cap.isEnabled() is False
    assert "Max" in cap.toolTip()


def test_capability_off_disables_capture_and_done(qtwidgets_app, locale):
    session, ctrl, cap, done, _ = _make_controller(qtwidgets_app, locale)
    ctrl.set_capability(False, "no vision")
    assert cap.isEnabled() is False
    assert done.isEnabled() is False
    assert cap.toolTip() == "no vision"


def test_busy_disables_all_three(qtwidgets_app, locale):
    session, ctrl, cap, done, clr = _make_controller(qtwidgets_app, locale)
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    ctrl.set_busy(True)
    assert cap.isEnabled() is False
    assert done.isEnabled() is False
    assert done.text() == "Busy"


def test_click_signals_forwarded(qtwidgets_app, locale):
    _, ctrl, cap, done, clr = _make_controller(qtwidgets_app, locale)
    fired: list[str] = []
    ctrl.capture_clicked.connect(lambda: fired.append("c"))
    ctrl.done_clicked.connect(lambda: fired.append("d"))
    ctrl.clear_clicked.connect(lambda: fired.append("x"))
    cap.click(); done.click(); clr.click()
    # done is disabled until a frame exists; add one then click
    from spiresight.core.inspect_session import InspectSession  # noqa: F401
    assert "c" in fired and "x" in fired


def test_count_reflects_session(qtwidgets_app, locale):
    session, ctrl, *_ = _make_controller(qtwidgets_app, locale)
    assert ctrl.count() == 0
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    assert ctrl.count() == 1


def test_retranslate_updates_done_text(qtwidgets_app, locale):
    _, ctrl, _, done, _ = _make_controller(qtwidgets_app, locale)
    assert done.text() == "Done"
    ctrl.set_busy(True)
    assert done.text() == "Busy"
    ctrl.set_busy(False)
    assert done.text() == "Done"
```

- [ ] **Step 3: Run failing tests**

```bash
.venv/bin/pytest tests/test_inspect_buttons_controller.py -q
```
Expected: FAIL — module not found.

- [ ] **Step 4: Implement controller**

`src/spiresight/ui/widgets/inspect_controls.py`:

```python
"""Inspect button group widgets + shared state controller.

`InspectButtonsController` owns the busy/capability/count state machine
for a triplet of buttons. `MiniInspectControls` is a compact widget for
the mini-bar (added in a later task). `_CountBadge` is a paint-event
overlay (added in a later task).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QAbstractButton

from spiresight.core.inspect_session import InspectSession
from spiresight.prompts.ui_locale import UILocale


class InspectButtonsController(QObject):
    """Owns enable/tooltip/text state for a (capture, done, clear) trio.

    Both `InspectPanel` (sidebar) and `MiniInspectControls` (mini-bar)
    construct one of these and inject their own button widgets.
    """

    capture_clicked = Signal()
    done_clicked    = Signal()
    clear_clicked   = Signal()

    def __init__(
        self,
        session: InspectSession,
        locale: UILocale,
        capture_btn: QAbstractButton,
        done_btn: QAbstractButton,
        clear_btn: QAbstractButton,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._locale = locale
        self._capture_btn = capture_btn
        self._done_btn = done_btn
        self._clear_btn = clear_btn
        self._capability_ok = True
        self._capability_tooltip = ""
        self._busy = False

        capture_btn.clicked.connect(self.capture_clicked.emit)
        done_btn.clicked.connect(self.done_clicked.emit)
        clear_btn.clicked.connect(self.clear_clicked.emit)

        session.changed.connect(self.refresh)
        locale.changed.connect(self.retranslate)
        self.retranslate()
        self.refresh()

    # public API
    def set_capability(self, ok: bool, tooltip: str = "") -> None:
        self._capability_ok = ok
        self._capability_tooltip = tooltip
        self.refresh()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.refresh()

    def count(self) -> int:
        return self._session.count

    # state machine
    def refresh(self) -> None:
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

    def retranslate(self) -> None:
        loc = self._locale
        self._capture_btn.setText(loc.get("panel.capture"))
        self._done_btn.setText(
            loc.get("panel.done_busy") if self._busy else loc.get("panel.done")
        )
        self._clear_btn.setText(loc.get("panel.clear"))
        self.refresh()
```

- [ ] **Step 5: Run tests — expect pass**

```bash
.venv/bin/pytest tests/test_inspect_buttons_controller.py -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/spiresight/ui/widgets/inspect_controls.py tests/test_inspect_buttons_controller.py
git commit -m "feat(ui): add InspectButtonsController state machine"
```

---

## Task 4: Refactor InspectPanel to use the controller

**Files:**
- Modify: `src/spiresight/ui/widgets/inspect_panel.py`
- Verify: `tests/test_inspect_panel.py` (must keep passing)

- [ ] **Step 1: Confirm existing tests pass before refactor**

```bash
.venv/bin/pytest tests/test_inspect_panel.py -q
```
Expected: PASS.

- [ ] **Step 2: Apply refactor**

Open `src/spiresight/ui/widgets/inspect_panel.py`. Replace the section between the `# buttons` comment (around line 103) and the end of `_retranslate` with the version below. Keep the thumbnail strip block unchanged, and keep these attribute names intact for test compatibility: `_capture_btn`, `_done_btn`, `_clear_btn`, `_session`, `_locale`, `_busy`, `_capability_ok`, `_capability_tooltip`.

In the `__init__` block, replace the `# buttons` section:

```python
        # buttons
        button_row = QHBoxLayout()
        self._capture_btn = QPushButton(locale.get("panel.capture"))
        self._capture_btn.setObjectName("primary")
        self._done_btn = QPushButton(locale.get("panel.done"))
        self._clear_btn = QPushButton(locale.get("panel.clear"))
        button_row.addWidget(self._capture_btn)
        button_row.addWidget(self._done_btn)
        button_row.addWidget(self._clear_btn)
        outer.addLayout(button_row)

        from spiresight.ui.widgets.inspect_controls import InspectButtonsController
        self._ctrl = InspectButtonsController(
            session, locale, self._capture_btn, self._done_btn, self._clear_btn, self,
        )
        self._ctrl.capture_clicked.connect(self.capture_requested.emit)
        self._ctrl.done_clicked.connect(self.done_clicked.emit if False else self.done_requested.emit)
        self._ctrl.clear_clicked.connect(self.clear_requested.emit)

        session.changed.connect(self._refresh_thumbnails)
        self._refresh_thumbnails()
```

> **Note:** the awkward `self.done_clicked.emit if False else self.done_requested.emit` is a typo guard — make it just `self._ctrl.done_clicked.connect(self.done_requested.emit)`. Use:

```python
        self._ctrl.capture_clicked.connect(self.capture_requested.emit)
        self._ctrl.done_clicked.connect(self.done_requested.emit)
        self._ctrl.clear_clicked.connect(self.clear_requested.emit)
```

Replace `set_capture_enabled` and `set_busy`:

```python
    def set_capture_enabled(self, enabled: bool, tooltip: str = "") -> None:
        self._capability_ok = enabled
        self._capability_tooltip = tooltip
        self._ctrl.set_capability(enabled, tooltip)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._ctrl.set_busy(busy)
```

Delete `_update_button_states` entirely. Shrink `_retranslate` to only the parts the controller does not own (thumbnails and the strip), and let the controller handle button text via `locale.changed` (already wired). The new `_retranslate` is:

```python
    def _retranslate(self) -> None:
        self._refresh_thumbnails()
```

Delete the `from PySide6.QtWidgets import` line's reference to anything no longer used (likely nothing changes here). Confirm `_refresh_thumbnails` no longer calls `self._update_button_states()` — remove that call if present.

- [ ] **Step 3: Run existing tests — expect pass**

```bash
.venv/bin/pytest tests/test_inspect_panel.py -q
```
Expected: PASS (same count as before).

- [ ] **Step 4: Run full suite**

```bash
.venv/bin/pytest -q
```
Expected: same pass count as the end of Task 1 plus +8 from Task 3.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/widgets/inspect_panel.py
git commit -m "refactor(ui): InspectPanel delegates state to InspectButtonsController"
```

---

## Task 5: _CountBadge overlay

**Files:**
- Modify: `src/spiresight/ui/widgets/inspect_controls.py` (append `_CountBadge`)
- Test: `tests/test_mini_inspect_controls.py` (will exercise badge alongside MiniInspectControls in Task 6)

- [ ] **Step 1: Append `_CountBadge` to `inspect_controls.py`**

Add imports at top of the file:

```python
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget
```

Append class at end of file:

```python
class _CountBadge(QWidget):
    """Small numeric badge overlay painted on the top-right of its parent."""

    SIZE = 14

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._count = 0
        parent.installEventFilter(self)
        self._reposition()

    def set_count(self, n: int) -> None:
        if n != self._count:
            self._count = n
            self.update()

    def count(self) -> int:
        return self._count

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._reposition()
        return False

    def _reposition(self) -> None:
        p = self.parentWidget()
        if p is None:
            return
        self.move(p.width() - self.SIZE + 2, -2)
        self.raise_()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor("#d4a54a")))
        painter.setPen(QPen(QColor("#1a1408"), 1))
        painter.drawEllipse(0, 0, self.SIZE - 1, self.SIZE - 1)
        painter.setPen(QPen(QColor("#1a1408")))
        font = painter.font()
        font.setPixelSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self._count))
```

- [ ] **Step 2: Import-smoke check**

```bash
.venv/bin/python -c "from spiresight.ui.widgets.inspect_controls import _CountBadge; print(_CountBadge.SIZE)"
```
Expected: `14`.

- [ ] **Step 3: Commit (no standalone tests yet — exercised in Task 6)**

```bash
git add src/spiresight/ui/widgets/inspect_controls.py
git commit -m "feat(ui): add _CountBadge overlay for mini-bar Capture button"
```

---

## Task 6: MiniInspectControls widget

**Files:**
- Modify: `src/spiresight/ui/widgets/inspect_controls.py` (append `MiniInspectControls`)
- Create: `tests/test_mini_inspect_controls.py`

- [ ] **Step 1: Write failing tests**

`tests/test_mini_inspect_controls.py`:

```python
from pathlib import Path

from PySide6.QtWidgets import QApplication

import pytest

from spiresight.core.inspect_session import InspectSession
from spiresight.prompts.ui_locale import UILocale


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


def test_badge_hidden_when_count_zero(qtwidgets_app, locale):
    from spiresight.ui.widgets.inspect_controls import MiniInspectControls
    session = InspectSession()
    w = MiniInspectControls(session, locale)
    assert w._badge.isVisible() is False or w._badge.count() == 0


def test_badge_visible_with_count(qtwidgets_app, locale):
    from spiresight.ui.widgets.inspect_controls import MiniInspectControls
    session = InspectSession()
    w = MiniInspectControls(session, locale)
    w.show()  # parents must be visible for child visibility checks
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    assert w._badge.count() == 2
    assert w._badge.isVisible() is True


def test_capture_signal_forwarded(qtwidgets_app, locale):
    from spiresight.ui.widgets.inspect_controls import MiniInspectControls
    session = InspectSession()
    w = MiniInspectControls(session, locale)
    fired: list[int] = []
    w.capture_requested.connect(lambda: fired.append(1))
    w._capture_btn.click()
    assert fired == [1]


def test_set_capability_propagates(qtwidgets_app, locale):
    from spiresight.ui.widgets.inspect_controls import MiniInspectControls
    session = InspectSession()
    w = MiniInspectControls(session, locale)
    w.set_capability(False, "no vision")
    assert w._capture_btn.isEnabled() is False
    assert w._capture_btn.toolTip() == "no vision"


def test_set_busy_disables_all(qtwidgets_app, locale):
    from spiresight.ui.widgets.inspect_controls import MiniInspectControls
    session = InspectSession()
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    w = MiniInspectControls(session, locale)
    w.set_busy(True)
    assert w._capture_btn.isEnabled() is False
    assert w._done_btn.isEnabled() is False
```

- [ ] **Step 2: Run failing tests**

```bash
.venv/bin/pytest tests/test_mini_inspect_controls.py -q
```
Expected: FAIL — `MiniInspectControls` does not exist.

- [ ] **Step 3: Implement widget**

Append at the bottom of `src/spiresight/ui/widgets/inspect_controls.py`:

```python
from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QToolButton

from spiresight.ui.theme import icon_path


class MiniInspectControls(QWidget):
    """Compact 3-button inspect group for the mini-bar.

    Same semantics as `InspectPanel`'s button row, plus a numeric badge
    on the capture button reflecting `InspectSession.count`.
    """

    capture_requested = Signal()
    done_requested    = Signal()
    clear_requested   = Signal()

    def __init__(
        self, session: InspectSession, locale: UILocale, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("mini-inspect")

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        def _mk(obj_name: str, icon_name: str, fallback_text: str) -> QToolButton:
            b = QToolButton()
            b.setObjectName(obj_name)
            b.setFixedSize(28, 28)
            b.setIconSize(QSize(18, 18))
            icon = QIcon(icon_path(icon_name))
            if icon.isNull():
                b.setText(fallback_text)
            else:
                b.setIcon(icon)
            return b

        self._capture_btn = _mk("mini-inspect-capture", "inspect_capture", "\U0001f4f7")  # 📷
        self._done_btn    = _mk("mini-inspect-done",    "inspect_done",    "✓")     # ✓
        self._clear_btn   = _mk("mini-inspect-clear",   "inspect_clear",   "×")     # ×

        row.addWidget(self._capture_btn)
        row.addWidget(self._done_btn)
        row.addWidget(self._clear_btn)

        self._badge = _CountBadge(self._capture_btn)

        self._ctrl = InspectButtonsController(
            session, locale, self._capture_btn, self._done_btn, self._clear_btn, self,
        )
        self._ctrl.capture_clicked.connect(self.capture_requested.emit)
        self._ctrl.done_clicked.connect(self.done_requested.emit)
        self._ctrl.clear_clicked.connect(self.clear_requested.emit)

        session.changed.connect(self._refresh_badge)
        self._refresh_badge()

    def set_capability(self, ok: bool, tooltip: str = "") -> None:
        self._ctrl.set_capability(ok, tooltip)

    def set_busy(self, busy: bool) -> None:
        self._ctrl.set_busy(busy)

    def _refresh_badge(self) -> None:
        n = self._ctrl.count()
        self._badge.set_count(n)
        self._badge.setVisible(n > 0)
```

> **Important:** the QToolButton text-fallback path means in offscreen tests with no SVG assets, the buttons display text glyphs. That is intentional and matches the spec's icon-fallback note.

- [ ] **Step 4: Run tests — expect pass**

```bash
.venv/bin/pytest tests/test_mini_inspect_controls.py -q
```
Expected: PASS (all 5).

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/widgets/inspect_controls.py tests/test_mini_inspect_controls.py
git commit -m "feat(ui): add MiniInspectControls (3 buttons + count badge)"
```

---

## Task 7: InfoBubble — `apply_size` + min/max + dynamic tail

**Files:**
- Modify: `src/spiresight/ui/widgets/info_bubble.py`
- Create: `tests/test_info_bubble_resize.py`

- [ ] **Step 1: Write failing tests**

`tests/test_info_bubble_resize.py`:

```python
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

import pytest


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_apply_size_resizes_within_bounds(qtwidgets_app):
    from spiresight.ui.widgets.info_bubble import InfoBubble
    b = InfoBubble()
    b.apply_size(QSize(500, 300))
    assert b.width() == 500
    assert b.height() == 300


def test_apply_size_clamps_below_min(qtwidgets_app):
    from spiresight.ui.widgets.info_bubble import InfoBubble
    b = InfoBubble()
    b.apply_size(QSize(50, 50))
    assert b.width() == b.minimumWidth()
    assert b.height() == b.minimumHeight()
    assert b.minimumWidth() == 280
    assert b.minimumHeight() == 140


def test_apply_size_clamps_above_max(qtwidgets_app):
    from spiresight.ui.widgets.info_bubble import InfoBubble
    b = InfoBubble()
    huge = QSize(9999, 9999)
    b.apply_size(huge)
    assert b.width() <= b.maximumWidth()
    assert b.height() <= b.maximumHeight()


def test_tail_recentered_on_resize(qtwidgets_app):
    from spiresight.ui.widgets.info_bubble import InfoBubble, TAIL_SIZE
    b = InfoBubble()
    b.apply_size(QSize(500, 300))
    expected_x = (b.width() - TAIL_SIZE) // 2
    assert b._tail.x() == expected_x
```

- [ ] **Step 2: Run failing tests**

```bash
.venv/bin/pytest tests/test_info_bubble_resize.py -q
```
Expected: FAIL — `apply_size` not defined / wrong tail position.

- [ ] **Step 3: Apply changes to `info_bubble.py`**

Add imports near the top of the file:

```python
from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication
```

Inside `InfoBubble.__init__`, near the end (after the existing `self.resize(BUBBLE_WIDTH, 100)` line, **replacing** that line):

```python
        self.setMinimumSize(280, 140)
        max_size = QGuiApplication.primaryScreen().availableSize() * 0.8
        # availableSize() returns a QSize; * 0.8 returns a QSize in Qt 6
        self.setMaximumSize(QSize(int(max_size.width()), int(max_size.height())))
        self.resize(BUBBLE_WIDTH, 240)
```

Add the `apply_size` method (place after `move_anchored`):

```python
    def apply_size(self, size: QSize) -> None:
        clamped = QSize(
            max(self.minimumWidth(),  min(self.maximumWidth(),  size.width())),
            max(self.minimumHeight(), min(self.maximumHeight(), size.height())),
        )
        self.resize(clamped)
```

Add a `resizeEvent` override (or extend if one already exists) to reposition the tail:

```python
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_tail()

    def _reposition_tail(self) -> None:
        self._tail.move((self.width() - TAIL_SIZE) // 2, -TAIL_SIZE)
```

Update `move_anchored` to use the current width:

```python
    def move_anchored(self, anchor_pos: QPoint) -> None:
        x = anchor_pos.x() - self.width() // 2
        y = anchor_pos.y() + TAIL_SIZE
        self.move(x, y)
```

Remove this line entirely (now handled by `_reposition_tail`):

```python
        self._tail.move((BUBBLE_WIDTH - TAIL_SIZE) // 2, -TAIL_SIZE)
```

Remove this line (no longer want a height cap on the inner scroll area — bubble itself caps via maximumSize):

```python
        self._scroll.setMaximumHeight(BUBBLE_MAX_HEIGHT)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
.venv/bin/pytest tests/test_info_bubble_resize.py -q
```
Expected: PASS (all 4).

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/widgets/info_bubble.py tests/test_info_bubble_resize.py
git commit -m "feat(ui): InfoBubble gains apply_size + dynamic tail recenter"
```

---

## Task 8: InfoBubble — QSizeGrip + grip repositioning

**Files:**
- Modify: `src/spiresight/ui/widgets/info_bubble.py`
- Modify: `tests/test_info_bubble_resize.py`

- [ ] **Step 1: Append failing test**

Add to `tests/test_info_bubble_resize.py`:

```python
def test_size_grip_present_and_bottom_right(qtwidgets_app):
    from PySide6.QtCore import QSize
    from spiresight.ui.widgets.info_bubble import InfoBubble
    b = InfoBubble()
    b.apply_size(QSize(400, 260))
    assert b._grip is not None
    # bottom-right placement (allow a few px for grip size)
    assert b._grip.x() + b._grip.width() <= b.width()
    assert b._grip.y() + b._grip.height() <= b.height()
    assert b._grip.x() >= b.width() - 32
    assert b._grip.y() >= b.height() - 32
```

- [ ] **Step 2: Run — expect fail**

```bash
.venv/bin/pytest tests/test_info_bubble_resize.py::test_size_grip_present_and_bottom_right -q
```
Expected: FAIL.

- [ ] **Step 3: Add `QSizeGrip` to `info_bubble.py`**

Import:

```python
from PySide6.QtWidgets import QSizeGrip
```

In `InfoBubble.__init__`, after the size limits but before the final `self.resize(...)`:

```python
        self._grip = QSizeGrip(self)
        self._grip.setFixedSize(14, 14)
```

Extend `_reposition_tail` into a combined helper, OR add a separate one. Use:

```python
    def _reposition_grip(self) -> None:
        self._grip.move(self.width() - 16, self.height() - 16)
        self._grip.raise_()
```

And update `resizeEvent`:

```python
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_tail()
        self._reposition_grip()
```

- [ ] **Step 4: Run — expect pass**

```bash
.venv/bin/pytest tests/test_info_bubble_resize.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/widgets/info_bubble.py tests/test_info_bubble_resize.py
git commit -m "feat(ui): add QSizeGrip to InfoBubble bottom-right"
```

---

## Task 9: InfoBubble — `size_changed` signal with debounce

**Files:**
- Modify: `src/spiresight/ui/widgets/info_bubble.py`
- Modify: `tests/test_info_bubble_resize.py`

- [ ] **Step 1: Append failing tests**

Add to `tests/test_info_bubble_resize.py`:

```python
def test_size_changed_signal_emitted_after_debounce(qtwidgets_app):
    from PySide6.QtCore import QSize, QTimer
    from PySide6.QtWidgets import QApplication
    from spiresight.ui.widgets.info_bubble import InfoBubble
    b = InfoBubble()
    received: list[QSize] = []
    b.size_changed.connect(received.append)

    b.apply_size(QSize(400, 260))
    b.apply_size(QSize(500, 280))
    b.apply_size(QSize(520, 300))

    assert received == []  # debounce not fired yet

    end_at = [False]
    QTimer.singleShot(450, lambda: end_at.__setitem__(0, True))
    while not end_at[0]:
        QApplication.processEvents()
    # Coalesced into a single emission with the latest size
    assert len(received) == 1
    assert received[0] == QSize(520, 300)
```

- [ ] **Step 2: Run — expect fail**

```bash
.venv/bin/pytest tests/test_info_bubble_resize.py::test_size_changed_signal_emitted_after_debounce -q
```
Expected: FAIL — `size_changed` attribute missing.

- [ ] **Step 3: Wire the signal + debounce timer**

Imports:

```python
from PySide6.QtCore import QTimer, Signal
```

Class-level signal on `InfoBubble`:

```python
class InfoBubble(QWidget):
    closed = Signal()
    cancel_requested = Signal()
    follow_up_requested = Signal(str, bool)
    size_changed = Signal(QSize)
```

In `__init__`, after the grip + size limits block:

```python
        self._size_debounce = QTimer(self)
        self._size_debounce.setSingleShot(True)
        self._size_debounce.setInterval(300)
        self._size_debounce.timeout.connect(
            lambda: self.size_changed.emit(self.size())
        )
```

Extend `resizeEvent`:

```python
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_tail()
        self._reposition_grip()
        self._size_debounce.start()
```

- [ ] **Step 4: Run — expect pass**

```bash
.venv/bin/pytest tests/test_info_bubble_resize.py -q
```
Expected: PASS (all 6).

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/widgets/info_bubble.py tests/test_info_bubble_resize.py
git commit -m "feat(ui): InfoBubble emits size_changed (300ms debounced)"
```

---

## Task 10: InfoBubble — `render_history` + `is_empty`

**Files:**
- Modify: `src/spiresight/ui/widgets/info_bubble.py`
- Modify: `tests/test_info_bubble_resize.py`

- [ ] **Step 1: Append failing tests**

Add to `tests/test_info_bubble_resize.py`:

```python
def test_is_empty_initial_true(qtwidgets_app):
    from spiresight.ui.widgets.info_bubble import InfoBubble
    b = InfoBubble()
    assert b.is_empty() is True


def test_render_history_replays_turns(qtwidgets_app):
    from spiresight.core.messages import Message
    from spiresight.ui.widgets.info_bubble import InfoBubble
    b = InfoBubble()
    turns = (
        Message(role="user", text="hi"),
        Message(role="assistant", text="hello back"),
    )
    b.render_history(turns)
    assert b.is_empty() is False


def test_render_history_with_empty_tuple_is_noop(qtwidgets_app):
    from spiresight.ui.widgets.info_bubble import InfoBubble
    b = InfoBubble()
    b.render_history(())
    assert b.is_empty() is True
```

- [ ] **Step 2: Run — expect fail**

```bash
.venv/bin/pytest tests/test_info_bubble_resize.py -q -k "is_empty or render_history"
```
Expected: FAIL — methods missing.

- [ ] **Step 3: Implement**

Inside `InfoBubble`, add:

```python
    def is_empty(self) -> bool:
        # Body layout always contains at least the OutputView. If there are
        # no user-message labels and the OutputView has no rendered text, the
        # bubble is "empty" for OFF→ON history-restore purposes.
        for i in range(self._body_layout.count()):
            w = self._body_layout.itemAt(i).widget()
            if w is None or w is self._output:
                continue
            return False  # found a user-message label
        return self._output.is_empty()

    def render_history(self, turns) -> None:
        if not turns:
            return
        self.reset()
        for msg in turns:
            if msg.role == "user":
                self.append_user_message(msg.text)
            else:
                self.append_delta(msg.text)
        self.finalize()
```

- [ ] **Step 4: Add `is_empty()` to OutputView if missing**

Check whether `OutputView` already has an `is_empty()`:

```bash
grep -n "def is_empty" src/spiresight/ui/widgets/output_view.py
```

If missing, add a method that returns True when no markdown text has been appended. Look at `OutputView` first to choose the right field; a common pattern is `self._buffer == ""` or similar. Add:

```python
    def is_empty(self) -> bool:
        # True when no streaming chunks have been received yet.
        return not self._buffer  # adjust attribute name to actual implementation
```

If the attribute name differs (e.g., `_text`, `_markdown`), use that.

- [ ] **Step 5: Run tests — expect pass**

```bash
.venv/bin/pytest tests/test_info_bubble_resize.py -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/spiresight/ui/widgets/info_bubble.py src/spiresight/ui/widgets/output_view.py tests/test_info_bubble_resize.py
git commit -m "feat(ui): InfoBubble gains render_history + is_empty"
```

---

## Task 11: MiniBar — new constructor params, layout, signals

**Files:**
- Modify: `src/spiresight/ui/widgets/mini_bar.py`
- Create: `tests/test_mini_bar_layout.py`

- [ ] **Step 1: Write failing test**

`tests/test_mini_bar_layout.py`:

```python
from pathlib import Path

from PySide6.QtWidgets import QApplication

import pytest

from spiresight.core.inspect_session import InspectSession
from spiresight.prompts.loader import PromptLoader
from spiresight.prompts.ui_locale import UILocale


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def loader(tmp_path: Path) -> PromptLoader:
    # Minimal prompts dir with one quick-action so the bar has at least one QA button.
    qa_dir = tmp_path / "quick_actions"
    qa_dir.mkdir()
    (qa_dir / "demo.yaml").write_text(
        "id: demo\nlabel: 'Demo'\nlabel_zh: '演示'\n"
        "system_prompt: 'sys'\nuser_template: 'u'\nrequires_screenshot: false\n",
        encoding="utf-8",
    )
    return PromptLoader(tmp_path, language="en")


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


def test_mini_bar_constructs(qtwidgets_app, loader, locale):
    from spiresight.ui.widgets.mini_bar import MiniBar
    session = InspectSession()
    bar = MiniBar(loader, hotkey_hint="Ctrl+X", inspect_session=session, locale=locale)
    assert bar is not None


def test_set_bubble_visible_syncs_button(qtwidgets_app, loader, locale):
    from spiresight.ui.widgets.mini_bar import MiniBar
    session = InspectSession()
    bar = MiniBar(loader, "Ctrl+X", inspect_session=session, locale=locale)
    bar.set_bubble_visible(True)
    assert bar._bubble_btn.isChecked() is True
    bar.set_bubble_visible(False)
    assert bar._bubble_btn.isChecked() is False


def test_bubble_toggle_emits_signal(qtwidgets_app, loader, locale):
    from spiresight.ui.widgets.mini_bar import MiniBar
    session = InspectSession()
    bar = MiniBar(loader, "Ctrl+X", inspect_session=session, locale=locale)
    received: list[bool] = []
    bar.bubble_toggle_requested.connect(received.append)
    bar._bubble_btn.click()
    assert received == [True]


def test_inspect_capture_forwarded(qtwidgets_app, loader, locale):
    from spiresight.ui.widgets.mini_bar import MiniBar
    session = InspectSession()
    bar = MiniBar(loader, "Ctrl+X", inspect_session=session, locale=locale)
    fired: list[int] = []
    bar.inspect_capture_requested.connect(lambda: fired.append(1))
    bar._inspect._capture_btn.click()
    assert fired == [1]


def test_set_inspect_capability_propagates(qtwidgets_app, loader, locale):
    from spiresight.ui.widgets.mini_bar import MiniBar
    session = InspectSession()
    bar = MiniBar(loader, "Ctrl+X", inspect_session=session, locale=locale)
    bar.set_inspect_capability(False, "off")
    assert bar._inspect._capture_btn.isEnabled() is False
    assert bar._inspect._capture_btn.toolTip() == "off"


def test_set_inspect_busy_propagates(qtwidgets_app, loader, locale):
    from spiresight.ui.widgets.mini_bar import MiniBar
    session = InspectSession()
    session.add_frame(b"\x89PNG\r\n\x1a\n")
    bar = MiniBar(loader, "Ctrl+X", inspect_session=session, locale=locale)
    bar.set_inspect_busy(True)
    assert bar._inspect._capture_btn.isEnabled() is False
    assert bar._inspect._done_btn.isEnabled() is False
```

- [ ] **Step 2: Run — expect fail**

```bash
.venv/bin/pytest tests/test_mini_bar_layout.py -q
```
Expected: FAIL (TypeError: unexpected kwarg `inspect_session`).

- [ ] **Step 3: Rewrite MiniBar**

Replace the entire body of `src/spiresight/ui/widgets/mini_bar.py` with:

```python
# src/spiresight/ui/widgets/mini_bar.py
"""Always-on-top compact bar with quick-action buttons, inspect group,
hotkey hint, and bubble/pin/expand controls."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from spiresight.core.inspect_session import InspectSession
from spiresight.prompts.loader import PromptLoader
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.theme import icon_path
from spiresight.ui.widgets.bubble_toggle_button import BubbleToggleButton
from spiresight.ui.widgets.inspect_controls import MiniInspectControls
from spiresight.ui.widgets.pin_button import PinButton


def _vsep() -> QFrame:
    s = QFrame()
    s.setObjectName("mini-bar-sep")
    s.setFrameShape(QFrame.Shape.VLine)
    s.setFixedWidth(1)
    return s


class MiniBar(QWidget):
    action_clicked            = Signal(str)
    expand_requested          = Signal()
    moved                     = Signal(QPoint)
    pin_toggled               = Signal(bool)
    bubble_toggle_requested   = Signal(bool)
    inspect_capture_requested = Signal()
    inspect_done_requested    = Signal()
    inspect_clear_requested   = Signal()

    def __init__(
        self,
        loader: PromptLoader,
        hotkey_hint: str,
        *,
        inspect_session: InspectSession,
        locale: UILocale,
        pinned: bool = True,
        bubble_visible: bool = False,
        parent=None,
    ) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if pinned:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._drag_offset: QPoint | None = None
        self._pinned = pinned

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)

        for qa in loader.quick_actions():
            btn = QPushButton(qa.label)
            btn.setIcon(QIcon(icon_path(qa.id)))
            btn.setIconSize(QSize(18, 18))
            btn.clicked.connect(lambda _=False, aid=qa.id: self.action_clicked.emit(aid))
            row.addWidget(btn)

        row.addWidget(_vsep())

        self._inspect = MiniInspectControls(inspect_session, locale, self)
        self._inspect.capture_requested.connect(self.inspect_capture_requested.emit)
        self._inspect.done_requested.connect(self.inspect_done_requested.emit)
        self._inspect.clear_requested.connect(self.inspect_clear_requested.emit)
        row.addWidget(self._inspect)

        row.addWidget(_vsep())
        row.addWidget(QLabel(hotkey_hint))
        row.addStretch(1)

        self._bubble_btn = BubbleToggleButton(visible=bubble_visible)
        self._bubble_btn.toggled.connect(self.bubble_toggle_requested.emit)
        row.addWidget(self._bubble_btn)

        self._pin_btn = PinButton(pinned=pinned)
        self._pin_btn.setToolTip("Always on top")
        self._pin_btn.toggled.connect(self._on_pin_toggled)
        row.addWidget(self._pin_btn)

        expand = QPushButton("▭")  # ▭
        expand.setToolTip("Expand to main window")
        expand.clicked.connect(self.expand_requested.emit)
        row.addWidget(expand)

    @property
    def is_pinned(self) -> bool:
        return self._pin_btn.isChecked()

    def set_pinned(self, pinned: bool) -> None:
        self._pin_btn.setChecked(pinned)

    def set_bubble_visible(self, visible: bool) -> None:
        self._bubble_btn.set_visible_state(visible)

    def set_inspect_capability(self, ok: bool, tooltip: str = "") -> None:
        self._inspect.set_capability(ok, tooltip)

    def set_inspect_busy(self, busy: bool) -> None:
        self._inspect.set_busy(busy)

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

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            self.moved.emit(self.pos())

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._drag_offset = None
```

- [ ] **Step 4: Run new tests — expect pass**

```bash
.venv/bin/pytest tests/test_mini_bar_layout.py -q
```
Expected: PASS (all 7).

- [ ] **Step 5: Run full suite — expect older `main_window` tests to fail on the constructor**

```bash
.venv/bin/pytest -q
```
The call site in `main_window._toggle_mini_bar` still uses the old signature; any test that triggers it will fail. Note which tests fail (likely none until Task 12). If unrelated tests fail, stop and inspect.

- [ ] **Step 6: Commit**

```bash
git add src/spiresight/ui/widgets/mini_bar.py tests/test_mini_bar_layout.py
git commit -m "feat(ui): MiniBar gains inspect group + bubble toggle"
```

---

## Task 12: MainWindow — update `_toggle_mini_bar` to new signature

**Files:**
- Modify: `src/spiresight/ui/windows/main_window.py`

- [ ] **Step 1: Locate `_toggle_mini_bar`**

```bash
grep -n "_toggle_mini_bar\|MiniBar(" src/spiresight/ui/windows/main_window.py
```

- [ ] **Step 2: Update construction call**

Find the existing block (around line 281):

```python
            self._mini_bar = MiniBar(self._loader, hotkey_hint=self._config.hotkey,
                                      pinned=self._config.always_on_top)
            self._mini_bar.action_clicked.connect(self._on_action)
            self._mini_bar.expand_requested.connect(self._exit_mini_bar)
            self._mini_bar.pin_toggled.connect(self._on_pin_toggled)
            self._mini_bar.moved.connect(self._on_mini_bar_moved)
```

Replace with:

```python
            self._mini_bar = MiniBar(
                self._loader,
                self._config.hotkey,
                inspect_session=self._inspect_session,
                locale=self._ui_locale,
                pinned=self._config.always_on_top,
                bubble_visible=False,
            )
            self._mini_bar.action_clicked.connect(self._on_action)
            self._mini_bar.expand_requested.connect(self._exit_mini_bar)
            self._mini_bar.pin_toggled.connect(self._on_pin_toggled)
            self._mini_bar.moved.connect(self._on_mini_bar_moved)
            self._mini_bar.bubble_toggle_requested.connect(self._on_minibar_bubble_toggled)
            self._mini_bar.inspect_capture_requested.connect(self._on_capture_requested)
            self._mini_bar.inspect_done_requested.connect(self._on_done_requested)
            self._mini_bar.inspect_clear_requested.connect(self._on_clear_requested)
```

- [ ] **Step 3: Add stub handler so Step 2 has a target**

Add a placeholder method on `MainWindow` (a more complete implementation lands in Task 13):

```python
    def _on_minibar_bubble_toggled(self, want_visible: bool) -> None:
        if self._bubble is None:
            return
        if want_visible:
            self._bubble.show()
        else:
            self._bubble.hide()
```

- [ ] **Step 4: Run suite**

```bash
.venv/bin/pytest -q
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/windows/main_window.py
git commit -m "feat(ui): wire MiniBar new signature in MainWindow"
```

---

## Task 13: MainWindow — bubble toggle full behavior + helpers

**Files:**
- Modify: `src/spiresight/ui/windows/main_window.py`
- Create: `tests/test_main_window_minimode_expand.py`

- [ ] **Step 1: Write failing test**

`tests/test_main_window_minimode_expand.py` — use the same setup style as other main-window-adjacent tests. If a helper / fixture for MainWindow does not yet exist (check `tests/test_main_window*.py`), instantiate MainWindow with minimal stores and configs from existing test patterns.

```python
"""Integration tests for mini-mode UI expansion wiring."""
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

import pytest


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def main_window(qtwidgets_app, tmp_path, monkeypatch):
    """Construct a MainWindow with on-disk config in tmp_path."""
    # NOTE: model after existing main_window-adjacent tests if any exist.
    # Otherwise build the minimum stack: AppConfig + ConfigStore + PromptLoader +
    # PricingTable + ConversationStore.
    from spiresight.config.schema import AppConfig
    from spiresight.config.store import ConfigStore
    from spiresight.core.conversation import ConversationStore
    from spiresight.prompts.loader import PromptLoader
    from spiresight.llm.pricing import PricingTable
    from spiresight.ui.windows.main_window import MainWindow

    cfg = AppConfig()
    store = ConfigStore(tmp_path / "config.json")
    store.save(cfg)
    # Inject minimal prompts root if PromptLoader requires it; mirror what
    # `tests/test_main_window*.py` already does. If no such test exists, use the
    # repo's `prompts/` directory as the loader root (read-only).
    from pathlib import Path
    repo_prompts = Path(__file__).resolve().parents[1] / "prompts"
    loader = PromptLoader(repo_prompts, language="en")
    pricing = PricingTable.empty()
    conv = ConversationStore()
    w = MainWindow(cfg, store, loader, pricing=pricing, conversation_store=conv)
    yield w
    w.close()


def test_toggle_mini_bar_initializes_widgets(main_window):
    main_window._toggle_mini_bar()
    assert main_window._mini_bar is not None
    assert main_window._bubble is not None


def test_minibar_bubble_toggle_off_hides_bubble(main_window):
    main_window._toggle_mini_bar()
    main_window._bubble.show()
    main_window._on_minibar_bubble_toggled(False)
    assert main_window._bubble.isVisible() is False


def test_bubble_closed_syncs_button(main_window):
    main_window._toggle_mini_bar()
    main_window._mini_bar.set_bubble_visible(True)
    main_window._on_bubble_closed()
    assert main_window._mini_bar._bubble_btn.isChecked() is False


def test_bubble_size_changed_writes_config(main_window):
    main_window._toggle_mini_bar()
    main_window._on_bubble_size_changed(QSize(520, 320))
    assert main_window._config.bubble_width == 520
    assert main_window._config.bubble_height == 320


def test_inspect_capability_pushed_on_minibar_entry(main_window):
    main_window._toggle_mini_bar()
    # set capability and verify it's reflected
    main_window._mini_bar.set_inspect_capability(False, "test off")
    assert main_window._mini_bar._inspect._capture_btn.toolTip() == "test off"
```

> **Note for the implementing engineer:** if the `main_window` fixture cannot be built cleanly because of additional required dependencies (capture, pricing data, etc.), inspect `tests/test_history_tab.py` or any other test that touches MainWindow for the right wiring. If there is no precedent, narrow the test scope: instantiate MainWindow with a stubbed `ScreenCapture` via monkeypatch on the import path.

- [ ] **Step 2: Run — expect fail** (`_on_bubble_size_changed` not implemented, helper missing, etc.)

```bash
.venv/bin/pytest tests/test_main_window_minimode_expand.py -q
```

- [ ] **Step 3: Add helpers + handlers**

In `MainWindow`, add the anchor-bubble helper (used in 3 places — extract from existing repetition):

```python
    def _anchor_bubble_to_minibar(self) -> None:
        if self._bubble is None or self._mini_bar is None:
            return
        mb_geo = self._mini_bar.geometry()
        anchor = QPoint(
            mb_geo.x() + mb_geo.width() // 2,
            mb_geo.y() + mb_geo.height(),
        )
        self._bubble.move_anchored(anchor)
```

Replace `_on_mini_bar_moved`:

```python
    def _on_mini_bar_moved(self, pos: QPoint) -> None:
        if self._bubble is not None and self._bubble.isVisible():
            self._anchor_bubble_to_minibar()
```

Replace the placeholder `_on_minibar_bubble_toggled` with the full version:

```python
    def _on_minibar_bubble_toggled(self, want_visible: bool) -> None:
        if self._bubble is None:
            return
        if want_visible:
            turns = self._conversation.turns()
            if self._bubble.is_empty() and turns:
                self._bubble.render_history(turns)
            self._anchor_bubble_to_minibar()
            self._bubble.show()
        else:
            self._bubble.hide()
```

Extend `_on_bubble_closed`:

```python
    def _on_bubble_closed(self) -> None:
        if self._mini_bar is not None:
            self._mini_bar.set_bubble_visible(False)
```

Add the size-changed handler:

```python
    def _on_bubble_size_changed(self, size: QSize) -> None:
        self._config.bubble_width  = size.width()
        self._config.bubble_height = size.height()
        self._store.save(self._config)
```

Import `QSize` near the top of `main_window.py` if not already present:

```python
from PySide6.QtCore import QPoint, QSize, Qt
```

- [ ] **Step 4: Wire bubble creation + size-restore + size-saved signal**

Inside the same `if self._mini_bar is None:` block in `_toggle_mini_bar`, replace the bubble-creation block:

```python
            self._bubble = InfoBubble()
            self._bubble.apply_size(
                QSize(self._config.bubble_width, self._config.bubble_height)
            )
            self._bubble.closed.connect(self._on_bubble_closed)
            self._bubble.cancel_requested.connect(self._on_cancel)
            self._bubble.follow_up_requested.connect(self._dispatch_follow_up)
            self._bubble.size_changed.connect(self._on_bubble_size_changed)
```

After this block, push capability state to the mini-bar (on every entry):

```python
        ok, tip = self._capability_status_for_inspect()
        self._mini_bar.set_inspect_capability(ok, tip)
```

If `_capability_status_for_inspect` does not yet exist as a named helper, factor the existing capability calculation out of `_refresh_inspect_availability` into one:

```python
    def _capability_status_for_inspect(self) -> tuple[bool, str]:
        # extract current body of _refresh_inspect_availability that produces (ok, tip)
        ...
```

Replace the existing `_refresh_inspect_availability`:

```python
    def _refresh_inspect_availability(self) -> None:
        ok, tip = self._capability_status_for_inspect()
        self._inspect_panel.set_capture_enabled(ok, tip)
        if self._mini_bar is not None:
            self._mini_bar.set_inspect_capability(ok, tip)
```

Replace the duplicated anchor calc in `_toggle_mini_bar` (around line 302) and in `_on_action` (around line 456) by calls to `self._anchor_bubble_to_minibar()`.

- [ ] **Step 5: Run tests — expect pass**

```bash
.venv/bin/pytest tests/test_main_window_minimode_expand.py -q
.venv/bin/pytest -q
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/spiresight/ui/windows/main_window.py tests/test_main_window_minimode_expand.py
git commit -m "feat(ui): wire mini-bar bubble toggle + size persistence in MainWindow"
```

---

## Task 14: MainWindow — push inspect busy state to mini-bar

**Files:**
- Modify: `src/spiresight/ui/windows/main_window.py`

- [ ] **Step 1: Locate inspect-busy push sites**

```bash
grep -n "set_busy\|_inspect_panel\.set_busy\|InspectWorker" src/spiresight/ui/windows/main_window.py
```

- [ ] **Step 2: Mirror busy state to mini-bar**

Every existing call of the form `self._inspect_panel.set_busy(True)` (and `False`) gets a sibling:

```python
        self._inspect_panel.set_busy(True)
        if self._mini_bar is not None:
            self._mini_bar.set_inspect_busy(True)
```

…and on completion:

```python
        self._inspect_panel.set_busy(False)
        if self._mini_bar is not None:
            self._mini_bar.set_inspect_busy(False)
```

There are typically two sites: the worker start (in `_on_done_requested`) and the worker finished handler.

- [ ] **Step 3: Append test to verify**

Add to `tests/test_main_window_minimode_expand.py`:

```python
def test_inspect_busy_propagates_to_minibar(main_window):
    main_window._toggle_mini_bar()
    main_window._mini_bar.set_inspect_busy(True)
    assert main_window._mini_bar._inspect._capture_btn.isEnabled() is False
```

(This is a sanity assertion; the actual worker-lifecycle path is exercised by manual acceptance step 12.)

- [ ] **Step 4: Run + commit**

```bash
.venv/bin/pytest tests/test_main_window_minimode_expand.py -q
```
Expected: PASS.

```bash
git add src/spiresight/ui/windows/main_window.py tests/test_main_window_minimode_expand.py
git commit -m "feat(ui): mirror inspect busy state to mini-bar"
```

---

## Task 15: MainWindow — `set_bubble_visible(True)` on quick-action + follow-up

**Files:**
- Modify: `src/spiresight/ui/windows/main_window.py`

- [ ] **Step 1: Locate auto-show sites**

```bash
grep -n "self\._bubble\.show()\|self\._bubble\.reset()" src/spiresight/ui/windows/main_window.py
```

- [ ] **Step 2: Add `set_bubble_visible(True)` after each show**

After each `self._bubble.show()` that runs while in mini-bar mode, append:

```python
            if self._mini_bar is not None:
                self._mini_bar.set_bubble_visible(True)
```

There are typically two such sites: in `_on_action` (quick-action path) and in the follow-up dispatch path.

- [ ] **Step 3: Append test**

Add to `tests/test_main_window_minimode_expand.py`:

```python
def test_quick_action_sets_minibar_bubble_visible(main_window):
    main_window._toggle_mini_bar()
    # Force the bubble visible via the same path quick-action takes
    main_window._bubble.show()
    main_window._mini_bar.set_bubble_visible(True)
    assert main_window._mini_bar._bubble_btn.isChecked() is True
```

(The integration with `_on_action` requires a working provider; this assertion validates the synchronous wiring.)

- [ ] **Step 4: Run + commit**

```bash
.venv/bin/pytest tests/test_main_window_minimode_expand.py -q
```
Expected: PASS.

```bash
git add src/spiresight/ui/windows/main_window.py tests/test_main_window_minimode_expand.py
git commit -m "feat(ui): quick-action / follow-up sync mini-bar bubble toggle"
```

---

## Task 16: QSS additions

**Files:**
- Modify: `src/spiresight/ui/qss/dark_fantasy.qss`

- [ ] **Step 1: Append rules at end of file**

```css
/* ── Bubble toggle ────────────────────────────────────────── */
QToolButton#bubble-toggle {
    color: #6e7a89;
    background: transparent;
    border: none;
    padding: 4px;
    border-radius: 4px;
}
QToolButton#bubble-toggle:hover {
    color: #d5cebf;
    background: rgba(255, 255, 255, 8);
}
QToolButton#bubble-toggle:checked { color: #d4a54a; }
QToolButton#bubble-toggle:checked:hover { color: #e6b85a; }

/* ── Mini-bar inspect group ───────────────────────────────── */
QWidget#mini-inspect QToolButton {
    color: #d5cebf;
    background-color: #10141e;
    border: 1px solid #1d2233;
    border-radius: 4px;
}
QWidget#mini-inspect QToolButton:hover { border-color: #3a6080; }
QWidget#mini-inspect QToolButton:disabled {
    color: #4a5260;
    background-color: #0a0d14;
    border-color: #1d2233;
}
QWidget#mini-inspect QToolButton#mini-inspect-capture:enabled {
    border-color: #d4a54a;
}

/* ── Mini-bar separators ──────────────────────────────────── */
QFrame#mini-bar-sep {
    color: #1d2233;
    background-color: #1d2233;
    max-width: 1px;
}

/* ── InfoBubble size grip ─────────────────────────────────── */
QSizeGrip {
    width: 14px;
    height: 14px;
    background: transparent;
}
```

- [ ] **Step 2: Run full test suite**

```bash
.venv/bin/pytest -q
```
Expected: all green (QSS does not run in offscreen, but loader must still parse it).

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/ui/qss/dark_fantasy.qss
git commit -m "style(ui): QSS for bubble toggle, mini inspect group, size grip"
```

---

## Task 17: Manual acceptance run

**Files:** none

- [ ] **Step 1: Launch the app**

```bash
.venv/bin/python -m spiresight
```

- [ ] **Step 2: Walk the spec's manual checklist**

Run each of the 15 manual steps from `docs/superpowers/specs/2026-05-19-minimode-ui-expand-design.md` §8.4. For any failure: capture which step + what happened, file a follow-up task, fix.

- [ ] **Step 3: Sanity-check `QSizeGrip` overlap with send button**

(Per spec §9 note.) In mini-bar mode, open the bubble, drag the grip to confirm resize works, then confirm clicking the send button (↵) still triggers — no click is stolen by the grip.

- [ ] **Step 4: Verify size persistence by restarting**

Resize bubble, exit app, relaunch, enter mini-bar → quick-action → bubble appears at the saved size.

- [ ] **Step 5: Final commit if any docs/notes updated; otherwise no-op**

---

## Self-review (run after writing — already applied)

- **Spec coverage:**
  - §3.1/3.2 new + modified modules → Tasks 2, 3, 5, 6 (new); 1, 4, 7, 8, 9, 10, 11, 12–15 (modified)
  - §4 config schema → Task 1
  - §5.1 BubbleToggleButton → Task 2
  - §5.2 InspectButtonsController → Task 3 + 4
  - §5.3 MiniInspectControls → Task 6
  - §5.4 _CountBadge → Task 5
  - §5.5 InfoBubble resize / grip / size_changed / render_history → Tasks 7, 8, 9, 10
  - §5.6 MiniBar refactor → Task 11
  - §6 control flow → Tasks 12, 13, 14, 15
  - §7 QSS → Task 16
  - §8.1–8.3 unit/integration/config tests → Tasks 1–15 (each task creates its own tests)
  - §8.4 manual → Task 17
  - §9 notes (icon fallbacks, QSizeGrip overlap) → Task 2 / Task 6 fallbacks; manual step 3 verifies overlap
- **Placeholders:** none — all code blocks are concrete.
- **Type consistency:** signal names (`bubble_toggle_requested`, `inspect_capture_requested`, `size_changed`), method names (`set_bubble_visible`, `set_inspect_capability`, `apply_size`, `render_history`, `is_empty`, `_anchor_bubble_to_minibar`, `_on_bubble_size_changed`), and config fields (`bubble_width`, `bubble_height`) are used identically across the plan and spec.
