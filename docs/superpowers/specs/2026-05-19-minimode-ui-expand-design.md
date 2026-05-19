# Mini-mode UI Expansion — Design Document

**Status:** In review
**Date:** 2026-05-19
**Author:** HaoChen (with Claude)
**Branch:** `feature/minimode-ui-expand`

## 1. Overview

Mini-bar mode today exposes only quick-action buttons + pin + expand. Three gaps:

1. **No manual control over the InfoBubble** — once the user clicks × on the bubble, it can only reappear by firing a new quick-action.
2. **InfoBubble is fixed size** (360 × ~200) — long answers force scrolling in a tiny window.
3. **Inspect flow is invisible in mini-bar** — the user cannot capture / send / clear frames without expanding back to the main window, and the sidebar's frame-count signal is not available.

This spec extends the mini-bar with:

1. A **persistent BubbleToggleButton** on the mini-bar that mirrors bubble visibility, with accent-color when open / muted when closed.
2. **Bottom-right resize** on the InfoBubble via `QSizeGrip`, with width/height persisted in `AppConfig`.
3. A **MiniInspectControls** widget — three buttons matching the sidebar's InspectPanel (Capture / Done / Clear), with a numeric counter badge on Capture.

## 2. Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Toggle button is a **state mirror** — click flips visibility; quick-action / follow-up implicitly opens bubble and syncs button | Natural "show/hide" semantics; no surprises |
| 2 | Bubble visibility is **session-scope** (not persisted) | Each entry into mini-bar starts clean; user not paying for stale state across launches |
| 3 | Bubble width + height **persisted in AppConfig** | Matches existing `always_on_top` / `hotkey` persistence style |
| 4 | Use Qt-native `QSizeGrip`, **bottom-right only** | Minimal code, native cursor + behavior; left/top/free-positioning out of scope |
| 5 | MiniInspectControls = **3 buttons identical to sidebar**, no thumbnail strip | User explicit ask; minibar height stays compact |
| 6 | Capture button shows a **numeric badge** (overlay circle, accent bg) | Clear count signal; tooltip carries max-frames context |
| 7 | Share inspect button-state logic via **`InspectButtonsController`** (no UI) | Single source of truth for busy / capability / at-cap / count==0 state machine |
| 8 | Toggle OFF→ON re-renders conversation history into bubble **only if bubble content is empty** | Restores expected state when user never opened bubble in current mini-bar session |

## 3. Architecture

### 3.1 New modules

```
src/spiresight/ui/widgets/bubble_toggle_button.py
    BubbleToggleButton(QToolButton)

src/spiresight/ui/widgets/inspect_controls.py
    InspectButtonsController(QObject)   — pure state machine, owns the 3 buttons
    MiniInspectControls(QWidget)         — compact 3-button layout for mini-bar
    _CountBadge(QWidget)                 — paint-event numeric badge overlay
```

### 3.2 Modified modules

```
src/spiresight/ui/widgets/mini_bar.py
    - Construct InspectButtonsController via MiniInspectControls
    - Insert BubbleToggleButton between hotkey-hint and PinButton
    - New signals: bubble_toggle_requested(bool),
                   inspect_capture_requested(), inspect_done_requested(),
                   inspect_clear_requested()
    - New methods: set_bubble_visible(bool),
                   set_inspect_capability(bool, str), set_inspect_busy(bool)

src/spiresight/ui/widgets/info_bubble.py
    - Drop _scroll.setMaximumHeight; let scroll grow with widget
    - Add QSizeGrip at bottom-right (absolute-placed, repositioned in resizeEvent)
    - setMinimumSize(280, 140); setMaximumSize bounded by primary screen size
    - move_anchored() uses self.width() not BUBBLE_WIDTH constant
    - resizeEvent: reposition tail (centered), reposition grip,
                   start 300ms debounce timer → emit size_changed(QSize)
    - apply_size(QSize): clamp & resize on startup
    - render_history(turns): replays conversation into OutputView when toggling
                             ON with empty bubble + non-empty conversation
    - Signals: size_changed(QSize)

src/spiresight/ui/widgets/inspect_panel.py
    - Replace inline _update_button_states / button-text logic by an
      InspectButtonsController instance owning the 3 buttons.
    - Preserve existing public signals (capture_requested / done_requested /
      clear_requested) by forwarding controller signals.

src/spiresight/ui/windows/main_window.py
    - _toggle_mini_bar(): inject inspect_session + locale into MiniBar;
      wire bubble_toggle_requested + 3 inspect signals
    - New: _on_minibar_bubble_toggled(bool), _on_bubble_size_changed(QSize),
           _anchor_bubble_to_minibar() (extracted helper)
    - _refresh_inspect_availability(): push to both panel + mini_bar
    - _on_action / inspect-worker busy paths: forward state to mini_bar
    - InfoBubble created → apply_size(QSize(config.bubble_width, config.bubble_height))

src/spiresight/config/schema.py
    + bubble_width:  int = 360
    + bubble_height: int = 280

src/spiresight/ui/qss/dark_fantasy.qss
    + #bubble-toggle (default + :checked + :hover)
    + #mini-inspect QToolButton (default + :disabled + :hover)
    + #mini-bar-sep (vertical separator color)
    + QSizeGrip cursor / size
```

### 3.3 Module-dependency sketch

```
main_window
  ├─ MiniBar
  │   ├─ MiniInspectControls
  │   │   └─ InspectButtonsController ──► InspectSession (shared)
  │   ├─ BubbleToggleButton
  │   └─ PinButton (existing)
  ├─ InfoBubble (gains size_changed)
  └─ InspectPanel
      └─ InspectButtonsController ──► InspectSession (shared)
```

The two `InspectButtonsController` instances both observe the same `InspectSession`, so frame-count and capability state propagate naturally.

## 4. Config schema

```python
# src/spiresight/config/schema.py
class AppConfig(BaseModel):
    ...
    bubble_width:  int = 360
    bubble_height: int = 280
```

- Two flat int fields, mirroring existing `hotkey` / `always_on_top` style; Pydantic loads old configs without these fields by using defaults.
- No position field — bubble is always anchored to mini-bar bottom-center.

## 5. Component details

### 5.1 `BubbleToggleButton` (~30 lines)

```python
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
        if self.isChecked() != visible:
            self.blockSignals(True)
            self.setChecked(visible)
            self.blockSignals(False)
            self._update_icon()

    def _update_icon(self) -> None:
        name = "bubble_filled" if self.isChecked() else "bubble_outline"
        self.setIcon(QIcon(icon_path(name)))
```

If `bubble_filled.svg` / `bubble_outline.svg` are not yet present in the assets, fall back to text `💬` until icons land. Color difference is carried entirely by QSS (`:checked` selector).

### 5.2 `InspectButtonsController` (~80 lines)

Pure state-machine helper, not a QWidget. Reused by both `InspectPanel` and `MiniInspectControls`.

```python
class InspectButtonsController(QObject):
    capture_clicked = Signal()
    done_clicked    = Signal()
    clear_clicked   = Signal()

    def __init__(
        self, session: InspectSession, locale: UILocale,
        capture_btn: QAbstractButton, done_btn: QAbstractButton, clear_btn: QAbstractButton,
        parent: QObject | None = None,
    ) -> None: ...

    def set_capability(self, ok: bool, tooltip: str = "") -> None: ...
    def set_busy(self, busy: bool) -> None: ...
    def count(self) -> int: ...
    def refresh(self) -> None: ...     # busy / capability / at-cap / count==0 logic
    def retranslate(self) -> None: ... # set button text from locale
```

`refresh()` is the existing logic moved from `InspectPanel._update_button_states()`. `retranslate()` is the existing button-text portion of `InspectPanel._retranslate()`.

Compatibility: `InspectPanel.__init__` keeps its three signals (`capture_requested` / `done_requested` / `clear_requested`) by forwarding the controller's `_clicked` signals, so external wiring in `main_window` does not change.

### 5.3 `MiniInspectControls` (~70 lines)

```python
class MiniInspectControls(QWidget):
    capture_requested = Signal()
    done_requested    = Signal()
    clear_requested   = Signal()

    def __init__(self, session, locale, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("mini-inspect")
        row = QHBoxLayout(self); row.setContentsMargins(0,0,0,0); row.setSpacing(4)

        self._capture_btn = QToolButton()
        self._capture_btn.setObjectName("mini-inspect-capture")
        self._capture_btn.setIcon(QIcon(icon_path("inspect_capture")))
        self._capture_btn.setFixedSize(28, 28)
        self._badge = _CountBadge(self._capture_btn)

        self._done_btn  = QToolButton()
        self._done_btn.setIcon(QIcon(icon_path("inspect_done")))
        self._done_btn.setFixedSize(28, 28)

        self._clear_btn = QToolButton()
        self._clear_btn.setIcon(QIcon(icon_path("inspect_clear")))
        self._clear_btn.setFixedSize(28, 28)

        for b in (self._capture_btn, self._done_btn, self._clear_btn):
            row.addWidget(b)

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
        self._badge.setVisible(n > 0)
        self._badge.set_count(n)
```

### 5.4 `_CountBadge` (~40 lines)

Paint-event overlay; not styled via QSS.

```python
class _CountBadge(QWidget):
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
            self._count = n; self.update()

    def eventFilter(self, obj, e):  # reposition on parent resize
        if e.type() == QEvent.Type.Resize:
            self._reposition()
        return False

    def _reposition(self) -> None:
        p = self.parentWidget()
        if p is not None:
            self.move(p.width() - self.SIZE + 2, -2)

    def paintEvent(self, _e) -> None:
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor("#d4a54a")))
        p.setPen(QPen(QColor("#1a1408"), 1))
        p.drawEllipse(0, 0, self.SIZE - 1, self.SIZE - 1)
        p.setPen(QPen(QColor("#1a1408")))
        f = p.font(); f.setPixelSize(9); f.setBold(True); p.setFont(f)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self._count))
```

### 5.5 `InfoBubble` resize

Changes inside `info_bubble.py`:

```python
# __init__
self.setMinimumSize(280, 140)
self.setMaximumSize(QGuiApplication.primaryScreen().availableSize() * 0.8)
self._grip = QSizeGrip(self)    # absolute placed
self._size_debounce = QTimer(self); self._size_debounce.setSingleShot(True)
self._size_debounce.setInterval(300)
self._size_debounce.timeout.connect(
    lambda: self.size_changed.emit(self.size()))

# remove:
# self._scroll.setMaximumHeight(BUBBLE_MAX_HEIGHT)

# new signal
size_changed = Signal(QSize)

def apply_size(self, size: QSize) -> None:
    size = QSize(
        max(self.minimumWidth(),  min(self.maximumWidth(),  size.width())),
        max(self.minimumHeight(), min(self.maximumHeight(), size.height())),
    )
    self.resize(size)

def resizeEvent(self, e):
    super().resizeEvent(e)
    self._reposition_tail()
    self._reposition_grip()
    self._size_debounce.start()

def _reposition_tail(self):
    self._tail.move((self.width() - TAIL_SIZE) // 2, -TAIL_SIZE)

def _reposition_grip(self):
    self._grip.move(self.width() - 16, self.height() - 16)
    self._grip.raise_()

def move_anchored(self, anchor_pos: QPoint) -> None:
    x = anchor_pos.x() - self.width() // 2
    y = anchor_pos.y() + TAIL_SIZE
    self.move(x, y)

def render_history(self, turns: tuple[Message, ...]) -> None:
    """Replay conversation into OutputView when toggling bubble ON
    with empty content + non-empty conversation."""
    if not turns:
        return
    self.reset()
    for msg in turns:
        if msg.role == "user":
            self.append_user_message(msg.text)
        else:
            self.append_delta(msg.text)
    self.finalize()

def is_empty(self) -> bool:
    """True iff OutputView has no rendered content and no user-message labels."""
    ...
```

### 5.6 `MiniBar`

Constructor + layout updated:

```python
def __init__(
    self, loader: PromptLoader, hotkey_hint: str,
    inspect_session: InspectSession, locale: UILocale, *,
    pinned: bool = True, bubble_visible: bool = False, parent=None,
) -> None:
    ...
    row = QHBoxLayout(self)
    row.setContentsMargins(10, 6, 10, 6); row.setSpacing(6)

    for qa in loader.quick_actions():
        btn = QPushButton(qa.label); btn.setIcon(QIcon(icon_path(qa.id)))
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
    self._pin_btn.toggled.connect(self._on_pin_toggled)
    row.addWidget(self._pin_btn)

    expand = QPushButton("▭")
    expand.clicked.connect(self.expand_requested.emit)
    row.addWidget(expand)
```

New public API (already shown above) and signals:

```python
bubble_toggle_requested   = Signal(bool)
inspect_capture_requested = Signal()
inspect_done_requested    = Signal()
inspect_clear_requested   = Signal()
```

`_vsep()` returns a thin `QFrame` with `objectName="mini-bar-sep"`, `Shape.VLine`.

## 6. Control flow / wiring

### 6.1 Entering mini-bar mode

```
MainWindow._toggle_mini_bar():
  if self._mini_bar is None:
      mb = MiniBar(loader, config.hotkey, inspect_session, locale,
                   pinned=config.always_on_top, bubble_visible=False)
      mb.action_clicked.connect(self._on_action)
      mb.expand_requested.connect(self._exit_mini_bar)
      mb.pin_toggled.connect(self._on_pin_toggled)
      mb.moved.connect(self._on_mini_bar_moved)
      mb.bubble_toggle_requested.connect(self._on_minibar_bubble_toggled)
      mb.inspect_capture_requested.connect(self._on_capture_requested)
      mb.inspect_done_requested.connect(self._on_done_requested)
      mb.inspect_clear_requested.connect(self._on_clear_requested)
      self._mini_bar = mb

      self._bubble = InfoBubble()
      self._bubble.apply_size(QSize(config.bubble_width, config.bubble_height))
      self._bubble.closed.connect(self._on_bubble_closed)
      self._bubble.cancel_requested.connect(self._on_cancel)
      self._bubble.follow_up_requested.connect(self._dispatch_follow_up)
      self._bubble.size_changed.connect(self._on_bubble_size_changed)

  # Push capability state on every entry (provider may have changed)
  ok, tip = self._capability_status_for_inspect()
  self._mini_bar.set_inspect_capability(ok, tip)
  ...
```

### 6.2 Bubble toggle (state mirror)

```python
def _on_minibar_bubble_toggled(self, want_visible: bool) -> None:
    if self._bubble is None: return
    if want_visible:
        if self._bubble.is_empty() and self._conversation.turns():
            self._bubble.render_history(self._conversation.turns())
        self._anchor_bubble_to_minibar()
        self._bubble.show()
    else:
        self._bubble.hide()

def _on_bubble_closed(self) -> None:
    if self._mini_bar is not None:
        self._mini_bar.set_bubble_visible(False)
```

Quick-action / follow-up paths additionally call:

```python
if is_mini and self._bubble is not None:
    ...
    self._bubble.show()
    self._mini_bar.set_bubble_visible(True)   # ← new
```

### 6.3 Inspect — minibar + sidebar synced

Existing `_on_capture_requested / _on_done_requested / _on_clear_requested` handlers are reused. `InspectSession.changed` is observed by both controllers → frame count + button-enabled state stay in sync.

`_refresh_inspect_availability()` extended:

```python
def _refresh_inspect_availability(self) -> None:
    ok, tip = self._capability_status_for_inspect()
    self._inspect_panel.set_capture_enabled(ok, tip)
    if self._mini_bar is not None:
        self._mini_bar.set_inspect_capability(ok, tip)
```

`InspectWorker` busy lifecycle pushes to both:

```python
self._inspect_panel.set_busy(True)
if self._mini_bar is not None:
    self._mini_bar.set_inspect_busy(True)
```

### 6.4 Bubble resize persistence

```python
def _on_bubble_size_changed(self, size: QSize) -> None:
    self._config.bubble_width  = size.width()
    self._config.bubble_height = size.height()
    self._store.save(self._config)
```

Debounced 300 ms inside `InfoBubble`, so a drag emits one save.

### 6.5 Anchoring with variable width

`move_anchored` uses `self.width()` instead of the `BUBBLE_WIDTH` constant. Tail is repositioned to `(width - TAIL_SIZE) // 2` in `resizeEvent`.

### 6.6 Visibility state table

| Trigger | Bubble | Mini-bar toggle |
|---------|--------|-----------------|
| Enter mini-bar + history present | shown | checked |
| Enter mini-bar + no history | hidden | unchecked |
| Quick-action (mini-bar) | reset + show | checked |
| Follow-up send (from bubble) | already shown | already checked |
| Toggle ON→OFF | hide | unchecked |
| Toggle OFF→ON (bubble empty + history non-empty) | render_history + show | checked |
| Toggle OFF→ON (bubble has content) | show | checked |
| Bubble × close | hide | unchecked |
| Exit mini-bar | hide | (button destroyed with mini-bar visibility) |

## 7. QSS additions

Append to `src/spiresight/ui/qss/dark_fantasy.qss`:

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
    background: rgba(255,255,255,8);
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

`_CountBadge` is hand-painted (`paintEvent`), not styled via QSS.

## 8. Test plan

### 8.1 Unit / component

```
tests/ui/test_bubble_toggle_button.py
  - Initial unchecked → icon = bubble_outline
  - click → toggled(True), icon = bubble_filled
  - set_visible_state(True) does NOT emit toggled
  - set_visible_state(same as current) is a no-op

tests/ui/test_inspect_buttons_controller.py
  - busy=True → all three buttons disabled; done text = "Inspecting…"
  - capability_ok=False → capture+done disabled, tooltip = supplied text
  - session.count==0 → done disabled, "no_frames" tooltip
  - session.count==MAX → capture disabled, "max_frames" tooltip
  - session.changed → refresh() called
  - locale.changed → retranslate() called, button text updates
  - 3 click signals forwarded correctly

tests/ui/test_mini_inspect_controls.py
  - count=0 → badge hidden
  - count=2 → badge visible, paints "2"
  - capability_ok=False → capture tooltip propagates from controller

tests/ui/test_info_bubble_resize.py
  - apply_size((500, 300)) → resized to 500×300
  - apply_size(huge) → clamped to maximumSize
  - apply_size(tiny) → clamped to minimumSize(280, 140)
  - resizeEvent → tail repositioned to centered x
  - resizeEvent → size_changed emitted once after 300 ms debounce
                  even under multiple rapid resize events

tests/ui/test_mini_bar_layout.py
  - MiniBar receives inspect_session; signals forwarded
  - set_bubble_visible(True) → BubbleToggleButton.isChecked() == True
  - set_inspect_capability(False, "tip") → capture tooltip == "tip"
```

### 8.2 Integration

`tests/ui/test_main_window_minimode_expand.py` (new):

- Entering mini-bar pushes capability state to mini_bar once.
- `bubble_toggle_requested(True)` shows bubble; if bubble empty + conversation non-empty, `render_history` is invoked.
- `bubble_toggle_requested(False)` hides bubble.
- `bubble.closed` syncs mini_bar.set_bubble_visible(False).
- Quick-action in mini-bar calls mini_bar.set_bubble_visible(True).
- `bubble.size_changed(QSize(500, 300))` writes config + saves store.
- `inspect_session.add_frame(...)` → mini_bar capture badge count == 1.
- InspectWorker.start → mini_bar.set_inspect_busy(True); finish → False.

### 8.3 Config

`tests/config/test_schema.py`:

- `AppConfig()` defaults → `bubble_width == 360`, `bubble_height == 280`.
- Round-trip preserves both fields.
- Legacy config (without bubble fields) loads cleanly using defaults.

### 8.4 Manual acceptance

1. Normal → mini-bar: bubble hidden; toggle button muted (unchecked).
2. Mini-bar, click quick-action: bubble appears, anchored; toggle turns accent (checked).
3. During stream, click toggle OFF: bubble hides, stream keeps going; click ON: bubble reappears showing accumulated content.
4. Click bubble × : toggle button returns to muted immediately.
5. Drag mini-bar: bubble follows; toggle button state unchanged.
6. Drag bubble bottom-right grip: width + height change, tail stays centered; release → ~300 ms later config saves (verify by restart).
7. Resize to extreme small: clamped to minimum, no error.
8. Mini-bar Capture: frame added; badge "1", then "2", "3".
9. count == MAX_FRAMES: capture disabled; hover tooltip shows max.
10. count == 0: done disabled.
11. Clear: badge vanishes; sidebar InspectPanel cleared in sync.
12. During InspectWorker busy: mini-bar three buttons all disabled.
13. Switch to non-vision provider: mini-bar capture / done disabled + tooltip explains.
14. Mini-bar → main → mini-bar: size, inspect count, bubble content preserved; toggle state reflects bubble visibility.
15. Locale switch (zh / en): mini-bar tooltips retranslate (buttons are icon-only).

## 9. Notes / open items

- Icon assets needed: `bubble_filled.svg`, `bubble_outline.svg`, `inspect_capture.svg`, `inspect_done.svg`, `inspect_clear.svg`. Fall back to text glyphs (`💬` / `📷` / `✓` / `×`) during development until SVGs land.
- `_anchor_bubble_to_minibar()` is a helper extracted from current duplicated `mb_geo + QPoint(...)` calc in `_toggle_mini_bar`, `_on_mini_bar_moved`, and `_on_action` (mini path).
- Bubble visibility is intentionally session-scope: no `bubble_visible_in_minimode` config field.
- `MAX_FRAMES` is read from `InspectSession.MAX_FRAMES`; the badge shows only current count (no `/MAX`), tooltip on Capture carries the cap.
- `QSizeGrip` is absolute-placed at `(width-16, height-16)` and overlaps the bottom-right corner of the input row's send button by a few pixels. Qt restricts the resize cursor to the grip's 14×14 footprint and `raise_()` keeps it on top; verify during manual step 6 that send-button clicks are still hittable.

## 10. Out of scope

- Free repositioning of the bubble (still anchored to mini-bar bottom).
- Resize from other edges / corners.
- Thumbnail strip in mini-bar.
- Mini-bar self-resize.
- Auto-dismiss timer on bubble.
- Multiple parallel conversations.
