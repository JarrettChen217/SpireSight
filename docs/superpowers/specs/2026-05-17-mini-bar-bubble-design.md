# InfoBubble + Multi-turn Conversation — Design Document

**Status:** In review
**Date:** 2026-05-17
**Author:** HaoChen (with Claude)

## 1. Overview

Today, after selecting a quick-action in mini-bar mode, the user must return to normal mode to read the response. This spec defines:

1. **InfoBubble** — a styled floating bubble that displays streaming responses anchored below the mini-bar, with inline chat input for follow-up questions.
2. **Multi-turn conversation** — a `ConversationStore` that persists across mode switches, plus a semantic split: quick-action buttons start a fresh conversation (no context), while free-form text input continues the current one.
3. **Pin button consistency pass** — unify pin styling and fix mini-bar pin sync.

## 2. Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Bubble **anchored below mini-bar**, follows mini-bar on drag (tail pointer) | Semantic "output of mini-bar" visual; Option A from anchor mockup. |
| 2 | Bubble is **sticky** — stays open until × closed or new quick-action replaces content | User controls reading pace; no auto-dismiss timer. |
| 3 | Exit mini-bar → **conversation retained**, ChatTab picks it up | Continuity across modes; matches "global shared" preference. |
| 4 | **No independent bubble pin** — bubble always follows mini-bar | User said "oh bubble不独立pin." |
| 5 | Quick-action buttons → **fresh conversation** (`conversation.clear()`, inject preset prompt + RunState) | Preset prompts are standalone. |
| 6 | Free-form input (bubble or ComposePanel) → **follow-up** (no preset prompt, no RunState, carries history) | User's raw text only, guarded by a light system prompt. |
| 7 | Follow-up screenshot: **default reuse last**, 📷 toggle to recapture | Default saves tokens; toggle gives flexibility. |
| 8 | Two request types: `QuickActionRequest` + `FollowUpRequest` (sum types) | Matches codebase Pydantic/dataclass style; avoids mode-enum ambiguity. |

## 3. Architecture

### 3.1 New modules

```
core/messages.py         → Message dataclass
core/conversation.py     → ConversationStore(QObject)
ui/widgets/info_bubble.py → InfoBubble(QWidget)
ui/widgets/pin_button.py  → PinButton(QToolButton) — reusable pin control
prompts/guard.txt         → Guard system prompt for follow-up (no RunState context)
```

### 3.2 Modified modules

```
core/request.py           → QuickActionRequest + FollowUpRequest dataclasses
core/runner.py            → run_quick_action() + run_follow_up()
llm/provider.py           → stream() gains optional messages=list[Message]
ui/windows/main_window.py → wire bubble, conversation, new dispatch paths
ui/widgets/mini_bar.py    → PinButton, expose set_pinned() / pin_toggled signal
ui/tabs/chat_tab.py       → multi-turn rendering
ui/widgets/compose_panel.py → input → follow-up (not custom_text fill-in)
ui/qss/dark_fantasy.qss   → bubble + pin-button rules
config/schema.py          → no schema changes needed
```

## 4. Data Model

### 4.1 `Message`

```python
# core/messages.py
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    text: str
    image_png: bytes | None = None   # only meaningful for user messages
```

### 4.2 `ConversationStore`

```python
# core/conversation.py
from PySide6.QtCore import QObject, Signal

class ConversationStore(QObject):
    changed = Signal()

    def turns(self) -> tuple[Message, ...]: ...    # immutable snapshot
    def append(self, message: Message) -> None: ...
    def clear(self) -> None: ...
    def last_screenshot(self) -> bytes | None: ...  # most recent user image
```

Pure Python; no Qt dependency needed except `QObject + Signal` for UI binding. Assembled as a singleton in `app.py` and injected into MainWindow, InfoBubble, and InferenceWorker.

### 4.3 Request types

```python
# core/request.py — replaces existing InferenceRequest

@dataclass(frozen=True)
class QuickActionRequest:
    prompt_id: str
    custom_text: str
    include_screenshot: bool

@dataclass(frozen=True)
class FollowUpRequest:
    user_text: str
    include_screenshot: bool = False
    recapture: bool = False     # True when 📷 toggled on
```

## 5. Provider & Runner

### 5.1 Provider interface extension

```python
# llm/provider.py — stream() gains optional messages param
def stream(
    self, *,
    model: str,
    system: str,
    user_text: str = "",               # legacy single-turn path
    images: list[bytes] = (),
    messages: list[Message] | None = None,  # NEW multi-turn path
    cancel_event: threading.Event,
    json_mode: bool = False,
) -> Iterator[StreamChunk]: ...
```

When `messages` is not None: the provider serializes `system` + `messages` into the chat-completion format (OpenAI messages array / Gemini contents). Each `Message.image_png` becomes a content-part image. Providers that don't yet support multi-turn should raise a `MissingCapabilityError`.

When `messages` is None: delegate to existing single-turn logic (backward compatible).

### 5.2 Runner split

```python
class InferenceRunner:
    def run_quick_action(
        self, request: QuickActionRequest, *, cancel_event: threading.Event
    ) -> Iterator[StreamChunk]:
        # Today's run() logic:
        #   system = quick_action.system_prompt + RunState prompt block
        #   user   = quick_action.user_template.format(custom_text=...)
        #   image  = screenshot if requires_screenshot
        #   NO messages param → single-turn path

    def run_follow_up(
        self, request: FollowUpRequest, history: tuple[Message, ...], *, cancel_event: threading.Event
    ) -> Iterator[StreamChunk]:
        # system  = GUARD_SYSTEM_PROMPT (no RunState appended)
        # image   = recapture? grab_primary() : history[-1].image_png (if any)
        # messages = history + [Message(role="user", text=..., image_png=...)]
        # calls provider.stream(..., messages=messages)
```

**Guard system prompt** (`prompts/guard.txt`):

> You are continuing a previous conversation. The user is asking a follow-up question without re-attaching the structured run state (cards, relics, potions). Rely on prior assistant messages for game-state context. If the user asks something that requires information you cannot infer from the conversation history, say so explicitly rather than guessing.

## 6. InfoBubble Widget

### 6.1 Visual spec

All colors from `theme.py::COLORS` (`bg #090c12`, `panel #0d1018`, `border #1d2233`, `text #d5cebf`, `accent #d4a54a`, `ember #d4743a`, `muted #6e7a89`, `crystal #3a6080`).

| Element | Style |
|---------|-------|
| Bubble frame | `panel` bg, `border` 1px, 8px radius, heavy drop-shadow |
| Title bar | accent 4%-alpha gradient top → transparent, `border` bottom |
| Title chip | `accent` color, uppercase, 10px, 600 weight, letter-spacing |
| Model name | `muted` color, monospace, 10px |
| × close | `muted` → hover `ember` |
| User message bubble | `#10141e` bg, left 2px `accent` border |
| Markdown bold | `accent` color |
| Markdown italic | `ember` color |
| Streaming cursor | `accent` bg, 500ms blink, subtle glow |
| Controls row | dark-rgba bg, `border` top, monospace cost text + `ok` green dot |
| Cancel button | transparent, `border` outline, `ember` text, hover `ember` border |
| Input field | `#10141e` bg, `border` border, `text` color, focus `crystal` |
| 📷 toggle | `muted` off → checked: accent 12%-alpha bg + `accent` border |
| Send button | `accent` bg → `#b88d3c` gradient, dark text, 600 weight |

### 6.2 Widget tree

```
InfoBubble(QWidget, objectName="info-bubble")
├─ QVBoxLayout
│   ├─ QWidget#bubble-title-bar
│   │   ├─ QLabel#bubble-chip         "出招建议"
│   │   ├─ QLabel#bubble-model        "gpt-4o-mini"
│   │   └─ QPushButton#bubble-close   "×"
│   ├─ QScrollArea (max-height 200px, 滚动)
│   │   └─ QWidget (content vertical layout)
│   │       ├─ QLabel#bubble-user-msg  (重复)
│   │       └─ OutputView             (复用, streaming markdown)
│   ├─ QWidget#bubble-controls
│   │   ├─ QLabel                     "● $0.0012 · 480 in / 220 out"
│   │   └─ QPushButton#bubble-cancel  "Cancel"
│   └─ QWidget#bubble-input-row
│       ├─ QToolButton#bubble-camera  "📷" (checkable)
│       ├─ QLineEdit#bubble-input     placeholder "追问…"
│       └─ QPushButton#bubble-send    "↵"
```

### 6.3 Public API

```python
class InfoBubble(QWidget):
    closed = Signal()
    cancel_requested = Signal()
    follow_up_requested = Signal(str, bool)   # (text, recapture)

    def reset(self) -> None: ...
    def append_user_message(self, text: str) -> None: ...
    def append_delta(self, text: str) -> None: ...
    def finalize(self) -> None: ...
    def set_streaming(self, active: bool) -> None: ...
    def set_cost(self, cost_usd: float | None, usage: TokenUsage | None) -> None: ...
    def set_title(self, action_label: str, model_id: str) -> None: ...
    def move_anchored(self, anchor_pos: QPoint) -> None: ...
```

Anchoring: `move_anchored(pos)` positions the bubble so its tail pointer aligns to `pos` (the mini-bar's center-bottom). Implemented via a small overlay `QWidget` with custom `paintEvent` drawing a rotated triangle.

### 6.4 Streaming cursor

`QTimer` 500ms toggle. Animated via CSS class on the final span:

```css
#stream-cursor { color: #d4a54a; animation: blink 0.9s step-end infinite; }
```

Turned off via removing the element when `finalize()` is called.

## 7. Control Flow

### 7.1 Quick-action dispatch (mini-bar and normal)

```
QuickAction btn clicked → MainWindow._dispatch_quick_action(prompt_id, custom_text, screenshot)
  ├─ self._conversation.clear()
  ├─ req = QuickActionRequest(prompt_id, custom_text, include_screenshot)
  ├─ runner.run_quick_action(req) → stream
  │    ├─ each chunk → mini mode? bubble.append_delta() : chat_tab.append_delta()
  │    └─ finished → conversation.append(user_msg) + conversation.append(assistant_msg)
  └─ usage recorded → bubble.set_cost() + tracker.call_completed_ok()
```

### 7.2 Follow-up dispatch (bubble input or ComposePanel)

```
Input Enter → MainWindow._dispatch_follow_up(text, recapture)
  ├─ req = FollowUpRequest(user_text=text, recapture=recapture)
  ├─ history = self._conversation.turns()
  ├─ runner.run_follow_up(req, history) → stream
  │    ├─ each chunk → bubble.append_delta() (or chat_tab)
  │    └─ finished → conversation.append(user_msg) + conversation.append(assistant_msg)
  └─ usage recorded → bubble.set_cost()
```

### 7.3 Mode transitions

| Transition | Conversation | Bubble |
|------------|-------------|--------|
| Normal → Mini | Preserved | Opens showing history if any; else hidden |
| Mini → Normal | Preserved | Bubble.close(). ChatTab renders full history |
| App close | Cleared | — |

### 7.4 Bubble lifecycle

| Event | Behavior |
|-------|----------|
| Quick-action clicked (mini mode) | `conversation.clear()` → `bubble.reset()` → title updated → streaming |
| Follow-up input Enter | `bubble.append_user_message()` → `bubble.set_streaming(True)` → stream |
| × clicked | `bubble.close()` (conversation kept in store for main window) |
| Cancel clicked (during stream) | `worker.cancel()` → `bubble.set_streaming(False)` |
| Streaming finishes | `bubble.finalize()` → cursor removed, Cancel hidden, cost shown |
| New quick-action replaces current | Old worker cancelled, bubble.reset(), new stream starts |

## 8. Mini-bar Pin Style Pass + Moved Signal

### 8.1 MiniBar signals

Bubble needs to follow when mini-bar is dragged. Add:

```python
class MiniBar(QWidget):
    moved = Signal(QPoint)        # emitted in moveEvent, global pos
    pin_toggled = Signal(bool)   # emitted when pin state changes
    def set_pinned(self, pinned: bool) -> None: ...  # public setter
```

### 8.2 PinButton widget (style consistency)

```python
# ui/widgets/pin_button.py
class PinButton(QToolButton):
    toggled = Signal(bool)

    def __init__(self, pinned: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(pinned)
        self.setIconSize(QSize(18, 18))
        self.setObjectName("pin-button")
        self._update_icon()
        self.clicked.connect(lambda: self.toggled.emit(self.isChecked()))
        self.clicked.connect(self._update_icon)

    def _update_icon(self):
        name = "pin_filled" if self.isChecked() else "pin_outline"
        self.setIcon(QIcon(icon_path(name)))
```

QSS:

```css
QToolButton#pin-button {
    color: #6e7a89;
    border: none;
    padding: 4px;
}
QToolButton#pin-button:checked {
    color: #d4a54a;
}
```

Used in: mini-bar, main window corner row, and anywhere else that needs always-on-top toggle.

## 9. QSS Additions

All rules go into `dark_fantasy.qss`:

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
```

## 10. Test Plan

### 10.1 Unit / integration

- `ConversationStore`: append, clear, turns(), last_screenshot()
- `InferenceRunner.run_quick_action()`: assembles correct system + user from prompt
- `InferenceRunner.run_follow_up()`: assembles correct messages list + guard prompt
- Provider `stream(messages=...)` — OpenAI and Gemini paths
- `Message` serialization round-trip
- `InfoBubble` widget layout smoke (QTest)

### 10.2 Manual

1. Mini-bar mode: click quick-action, confirm bubble appears below mini-bar with tail
2. Drag mini-bar, confirm bubble follows
3. Streaming cursor blinks during response, disappears after finalize
4. Cost row updates after stream completes
5. Cancel button interrupts stream (bubble stays open)
6. × closes bubble; switch to normal mode → ChatTab shows conversation
7. Input "追问..." sends follow-up; user bubble appears, new stream appends below
8. 📷 toggle: off → reuses last screenshot; on → recaptures
9. Quick-action button pressed during existing conversation: content clears, fresh start
10. PinButton: toggle in mini-bar → mini-bar stays-on-top changes immediately; main window corner pin syncs
11. ComposePanel input Enter → follow-up (not quick-action injection)
12. Empty history + follow-up → guard prompt kicks in; LLM says it lacks context

## 11. Future Improvements (out of scope)

- Multi-line input (Shift+Enter) — single-line only for now
- Conversation persistence across app restarts
- Bubble text selection / copy
- Bubble resize / expand to full ChatTab inline
- Auto-scroll animation on chunk append
