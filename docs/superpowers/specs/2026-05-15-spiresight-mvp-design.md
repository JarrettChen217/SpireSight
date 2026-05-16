# SpireSight MVP — Design Document

**Status:** Approved for implementation planning
**Date:** 2026-05-15
**Author:** HaoChen (with Claude)

## 1. Overview

SpireSight is a standalone cross-platform desktop application (macOS development, Windows primary target) that acts as an AI-powered visual assistant for *Slay the Spire II*. The user invokes a quick-action prompt (or types a custom question), the app optionally captures the current screen, and sends the image plus text to an LLM Vision API. The streamed response is rendered as markdown in the app.

This document captures the MVP design. Implementation planning happens separately (see `writing-plans` output).

## 2. MVP Scope and Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | One concrete LLM provider in MVP (**OpenAI**), abstraction scaffolded for Anthropic and Gemini | Avoid premature abstraction. Validate the protocol against one real implementation before generalizing. |
| 2 | **Capability flag system** on model metadata (`VISION`, `TOOL_USE`, `JSON_MODE`, `THINKING`) | Single source of truth for what each model can do. UI badges and runtime pre-flight checks read the same data. |
| 3 | Show all models always; **block at send time** if selected model lacks a required capability (modal: switch model / send text-only / cancel) | Transparent without footguns. |
| 4 | **Plaintext `config.json`** for API keys in MVP | Explicitly deferred. See Future Improvements §11.1. |
| 5 | **Streaming** responses (token-by-token) | Better perceived latency for long strategic answers. |
| 6 | **Always-on-top window with mini-bar collapse mode AND global hotkey** | User can stay in-game; hotkey fires last-used prompt for one-shot access. |
| 7 | **Rendered markdown** output via Qt `QTextBrowser.setMarkdown()` | Lists, bold, and code blocks render readably. |
| 8 | **Standalone packaged app** — no embedded web server, no browser dependency | Ships as `.app` (macOS) / `.exe` (Windows) via PyInstaller. |

## 3. Stack

| Concern | Choice | Notes |
|---|---|---|
| GUI | **PySide6** | LGPL (commercial-friendly), same API as PyQt6, native markdown rendering, QSS theming. |
| Screenshot | **`mss`** | Pure Python, fast, cross-platform. |
| Global hotkey | **`pynput`** | macOS requires Accessibility permission — first-launch flow planned. |
| LLM SDK (MVP) | Official **`openai`** Python SDK | Streaming and multimodal support. |
| Config | **`pydantic-settings`** + JSON file | Typed validation, defaults. |
| Prompt files | **YAML** via **`PyYAML`** | Multiline strings, comments, i18n-friendly. |
| Concurrency | **`QThread` workers** with Qt signals | Avoids asyncio/Qt loop integration; UI stays responsive. |
| HTTP mocks (tests) | **`respx`** | For provider integration tests. |
| Packaging | **PyInstaller** | macOS `.app` and Windows `.exe`. |
| Logging | stdlib `logging` + rotating file handler | Logs at `~/Library/Logs/SpireSight/app.log` (mac) / `%LOCALAPPDATA%\SpireSight\logs\` (Win). |

### Rejected alternatives

- **CustomTkinter** — limited theming, weaker markdown/streaming support, weaker always-on-top + tray story on macOS.
- **PyQt6** — GPL forces app to GPL unless commercial license is purchased.
- **Embedded web server + browser shell** — explicitly out of scope per user requirement.

## 4. Directory Structure

```
SpireSight/
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
├── docs/superpowers/specs/
├── src/spiresight/
│   ├── __init__.py
│   ├── __main__.py                # python -m spiresight entry point
│   ├── app.py                     # QApplication bootstrap, dependency wiring
│   ├── config/
│   │   ├── paths.py               # OS-correct config dir resolution
│   │   ├── schema.py              # Pydantic models
│   │   └── store.py               # load/save config.json, atomic writes
│   ├── prompts/
│   │   ├── schema.py
│   │   └── loader.py              # YAML discovery + parsing + cache
│   ├── llm/
│   │   ├── capabilities.py        # Capability enum
│   │   ├── models.py              # ModelInfo dataclass
│   │   ├── provider.py            # LLMProvider Protocol, StreamChunk
│   │   ├── registry.py            # name -> factory mapping
│   │   ├── errors.py
│   │   └── providers/
│   │       ├── openai_provider.py
│   │       ├── anthropic_provider.py  # stub
│   │       └── gemini_provider.py     # stub
│   ├── capture/
│   │   └── screen.py              # ScreenCapture -> PNG bytes
│   ├── hotkey/
│   │   └── manager.py             # HotkeyManager (pynput) -> Qt signal
│   ├── core/
│   │   ├── request.py             # InferenceRequest dataclass
│   │   └── runner.py              # InferenceRunner: validation + orchestration
│   ├── ui/
│   │   ├── theme.py               # QSS loader, color tokens
│   │   ├── widgets/
│   │   │   ├── prompt_panel.py
│   │   │   ├── provider_picker.py # capability badges
│   │   │   ├── output_view.py     # streaming markdown
│   │   │   └── mini_bar.py
│   │   ├── windows/
│   │   │   ├── main_window.py
│   │   │   ├── settings_dialog.py
│   │   │   └── permission_dialog.py
│   │   └── workers/
│   │       └── inference_worker.py # QThread wrapping InferenceRunner
│   └── resources/
│       ├── qss/dark_fantasy.qss
│       ├── icons/*.svg
│       └── backgrounds/*.png      # injection points for game assets
├── prompts/                       # User-editable, decoupled
│   ├── system_prompts.yaml
│   └── locales/
│       ├── en/quick_actions.yaml
│       └── zh/quick_actions.yaml
└── tests/
    ├── test_config_store.py
    ├── test_prompt_loader.py
    ├── test_capability_check.py
    ├── test_openai_provider.py
    └── test_inference_runner.py
```

## 5. Module Boundary Rules

These boundaries are enforced by import discipline and validated by tests where applicable.

1. `ui/` is the **only** package that imports `PySide6`. All other packages run headless and are testable without a display.
2. `core/` orchestrates: it imports `config/`, `prompts/`, `llm/`, `capture/`. It does **not** import `ui/`.
3. `llm/providers/<name>_provider.py` depends only on `llm/capabilities.py`, `llm/models.py`, `llm/provider.py`, `llm/errors.py`. Adding a fourth provider is a new file plus a registry line — no other edits.
4. `config/` and `prompts/` are pure data layers. They know nothing about LLMs or UI.

## 6. Request Lifecycle

```
User clicks "Card Selection Guide" (or fires hotkey)
        |
   ui/main_window  ->  InferenceRequest(prompt_id, custom_text, include_screenshot)
        |
   ui/workers/inference_worker (QThread)
        |
   core/runner.InferenceRunner.run(request)
        |
        +- prompts.loader.get(prompt_id)        -> SystemPrompt + user_template
        +- capture.screen.grab() if needed      -> PNG bytes
        +- llm.registry.get(active_provider)    -> LLMProvider instance
        +- capability check vs ModelInfo         -> raise MissingCapabilityError if mismatch
        +- provider.stream(messages, cancel_event) -> yields StreamChunk
        |
   worker emits Qt signal per chunk
        |
   ui/output_view buffers + setMarkdown() on flush cadence
```

## 7. Schemas and Contracts

### 7.1 Config (`config/schema.py`)

```python
class ProviderConfig(BaseModel):
    api_key: str = ""        # MVP: plaintext. See Future Improvements §11.1.
    base_url: str | None = None

class AppConfig(BaseSettings):
    active_provider: str = "openai"
    active_model: str = "gpt-4o"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    language: Literal["en", "zh"] = "en"
    theme: str = "dark_fantasy"
    always_on_top: bool = True
    mini_bar_mode: bool = False
    hotkey: str = "<ctrl>+<shift>+s"   # pynput format
    last_used_prompt_id: str | None = None
```

- File location: `~/Library/Application Support/SpireSight/config.json` (macOS) and `%APPDATA%\SpireSight\config.json` (Windows). Resolved by `config/paths.py`.
- Atomic writes: write to `config.json.tmp` then `os.replace()` to avoid corruption on crash.
- `store.py` carries a `# TODO(security)` comment pointing at §11.1.

### 7.2 Prompts (`prompts/schema.py`)

```python
class SystemPrompt(BaseModel):
    id: str
    description: str
    content: str

class QuickAction(BaseModel):
    id: str                   # stable identifier
    label: str                # button text
    icon: str | None = None
    system_prompt_id: str     # references SystemPrompt.id
    user_template: str        # str.format with {custom_text}
    requires_screenshot: bool = True
    required_capabilities: list[Capability] = [Capability.VISION]
```

**Example `prompts/system_prompts.yaml`:**
```yaml
- id: sts_expert
  description: General Slay the Spire II expert persona
  content: |
    You are an expert Slay the Spire II strategist. You analyze game
    screenshots and provide concise, actionable advice. When uncertain,
    say so. Prioritize: immediate threats, long-run deck health,
    energy/economy curves.
```

**Example `prompts/locales/en/quick_actions.yaml`:**
```yaml
- id: card_selection
  label: "Card Selection Guide"
  icon: icons/card.svg
  system_prompt_id: sts_expert
  user_template: "Help me choose between the offered cards. {custom_text}"
  requires_screenshot: true
  required_capabilities: [VISION]
```

Localized files live under `locales/<lang>/`. Adding a language is a new directory plus its YAML files — no code change.

### 7.3 LLM contract (`llm/`)

```python
# capabilities.py
class Capability(StrEnum):
    VISION = "vision"
    TOOL_USE = "tool_use"
    JSON_MODE = "json_mode"
    THINKING = "thinking"

# models.py
@dataclass(frozen=True)
class ModelInfo:
    id: str                    # SDK identifier, e.g. "gpt-4o"
    display_name: str
    capabilities: frozenset[Capability]
    context_window: int

# provider.py
@dataclass
class StreamChunk:
    text_delta: str
    finish_reason: str | None = None

class LLMProvider(Protocol):
    name: str

    def list_models(self) -> list[ModelInfo]: ...

    def stream(
        self,
        *,
        model: str,
        system: str,
        user_text: str,
        image_png: bytes | None,
        cancel_event: threading.Event,
    ) -> Iterator[StreamChunk]: ...
```

The protocol is intentionally narrow: a single `stream` method. Each provider adapts internally to its SDK. `image_png` is `bytes` to keep callers out of temp-file management. `cancel_event` lets the UI's Cancel button stop a stream cleanly.

### 7.4 Provider registry (`llm/registry.py`)

```python
_PROVIDERS: dict[str, Callable[[ProviderConfig], LLMProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,   # stub, raises NotImplementedError
    "gemini": GeminiProvider,         # stub, raises NotImplementedError
}

def get(name: str, config: ProviderConfig) -> LLMProvider:
    return _PROVIDERS[name](config)
```

### 7.5 Capability pre-flight (`core/runner.py`)

```python
def _check_capabilities(model: ModelInfo, required: set[Capability]) -> None:
    missing = required - model.capabilities
    if missing:
        raise MissingCapabilityError(model=model.id, missing=missing)
```

The UI catches `MissingCapabilityError` and shows a modal with the choices: switch model / send text-only / cancel.

### 7.6 Adding a new provider

1. Create `llm/providers/<name>_provider.py` implementing `LLMProvider`.
2. Register the factory in `llm/registry.py::_PROVIDERS`.
3. Optionally add provider-specific icon under `resources/icons/`.
4. No other file changes required.

## 8. UI Structure

### 8.1 Windows and dialogs

- **MainWindow** — title bar; left sidebar (provider dropdown, model dropdown with capability badges, quick-action buttons); right pane (optional custom-text input, controls row with "Include screenshot" checkbox and Send button, streaming markdown output).
- **MiniBar** — borderless, always-on-top, draggable, fits a row of quick-action buttons plus hotkey hint plus expand button. Toggled from MainWindow header or hotkey.
- **SettingsDialog** — API keys per provider, hotkey rebind (captures keystroke combo), language switch, theme reload (live re-applies QSS for asset iteration without restart).
- **PermissionDialog (macOS only)** — first-launch flow when hotkey registration fails: explains Accessibility permission, "Open System Settings" button, retry.
- **Capability warning modal** — when send is blocked by missing capability: shows the offending model, the missing capability set, and the three action buttons.

### 8.2 Theming

A single QSS file at `resources/qss/dark_fantasy.qss` defines all colors. Asset paths reference Qt resource paths (`:/backgrounds/...`) loaded through a compiled `.qrc` so PyInstaller bundles them.

Asset injection points (drop-in friendly for later art):
- `resources/backgrounds/` — parchment, spire textures applied via QSS `background-image`
- `resources/icons/` — per-action SVGs replace generic placeholders in quick-action buttons
- `resources/qss/dark_fantasy.qss` — single palette source

A `--reload-qss` dev flag re-reads the QSS file on focus for iteration.

### 8.3 Streaming render

The worker thread emits a Qt signal per `StreamChunk`. The output view appends to a string buffer and re-runs `setMarkdown()` on a debounced cadence (every ~50ms or every 32 chunks, whichever comes first). On finish, one final `setMarkdown()` with the full buffer. If profiling shows re-render stutter, switch to incremental `QTextCursor.insertText()` for the body and re-render only on block boundaries.

## 9. Error Handling

The worker thread **never crashes the UI**. All exceptions are caught, packaged as a `WorkerError` signal, and rendered by the main thread.

| Error class | Source | UI behavior |
|---|---|---|
| `MissingAPIKey` | runner pre-flight | Modal: "Add your API key in Settings", button opens Settings |
| `MissingCapabilityError` | runner pre-flight | Capability warning modal (switch / text-only / cancel) |
| `AuthError` (HTTP 401) | provider | Modal: "Invalid API key for <provider>" |
| `RateLimitError` (HTTP 429) | provider | Status bar: "Rate limited — retrying in Xs"; auto-retry with backoff |
| `NetworkError` / timeout | provider | Status bar red: "Network error — check connection" |
| `ScreenCaptureError` | capture | Toast + offer to send text-only |
| `HotkeyRegistrationFailed` | hotkey | macOS: PermissionDialog. Otherwise: "Hotkey conflict — change in Settings" |
| `NotImplementedError` | Anthropic/Gemini stub providers | UI shows them disabled with tooltip "Coming soon" |
| Unhandled exception | inference_worker | Logged to file; status bar: "Unexpected error — see logs" |

## 10. Testing Strategy

| Test file | Covers |
|---|---|
| `test_config_store.py` | Round-trip save/load, defaults, atomic-write resilience (interrupt mid-write, verify no corruption) |
| `test_prompt_loader.py` | YAML parsing, missing-reference detection (quick action pointing to nonexistent system prompt), locale fallback |
| `test_capability_check.py` | Required vs available capability set logic; `MissingCapabilityError` carries the missing set |
| `test_openai_provider.py` | `respx`-mocked HTTP; verifies streaming chunk parsing, multimodal payload shape, `cancel_event` honored |
| `test_inference_runner.py` | End-to-end with a fake `LLMProvider` that yields scripted chunks; verifies system+user+image plumbing |

**Deliberately out of scope for MVP:** UI tests with `pytest-qt`. The strict UI/core boundary keeps `ui/` as a thin shell over tested pure-Python; UI is verified manually.

`pytest -q` runs in under 2 seconds and requires no display.

## 11. Future Improvements

These are intentionally **deferred from MVP**. The MVP design leaves clean seams so each can be added without a rewrite.

### 11.1 Security: migrate API keys to OS keyring

**Current MVP behavior:** API keys stored in plaintext at `~/Library/Application Support/SpireSight/config.json` (macOS) / `%APPDATA%\SpireSight\config.json` (Windows). This is acceptable for a single-user gaming utility but is not best practice.

**Future:** Replace `ProviderConfig.api_key: str` with a thin `KeyStore` abstraction backed by the `keyring` library (macOS Keychain, Windows Credential Manager). `config.json` retains non-secret settings only. Migration: on first launch after upgrade, read existing plaintext key, write to keyring, blank the JSON field.

**Seam:** All API-key reads in MVP go through `ProviderConfig.api_key`. Replacing the property with a keyring-backed lookup is a one-file change.

### 11.2 Implement Anthropic and Gemini providers

Stubs raising `NotImplementedError` are in `llm/providers/`. Implementations slot in with no other code changes.

### 11.3 Region-of-interest screenshot

Currently full primary screen. Future: per-quick-action saved region rectangles.

### 11.4 Multi-monitor selection

Pick which monitor to capture; remember per-quick-action.

### 11.5 Conversation history / session memory

Currently each query is one-shot (no history sent). Future: opt-in conversation continuity.

### 11.6 Custom user-defined quick actions in Settings UI

Currently YAML-only. Future: an editor in Settings that writes YAML.

### 11.7 Token usage and cost display

Per-request usage shown in status bar.

### 11.8 Fine-tuning data pipeline

YAML prompt format already lines up with a future training-data layout; the loader can be repurposed.

### 11.9 Auto-update channel

Sparkle on macOS, Squirrel/WinSparkle on Windows.

### 11.10 Toast overlay when window is hidden

Currently MiniBar fills this role.

## 12. Risks and Open Concerns

| Risk | Mitigation |
|---|---|
| macOS Accessibility permission UX for global hotkey | First-launch detection + dedicated `PermissionDialog` with deep link to System Settings |
| Streaming + markdown re-render performance | Measured early (`time.perf_counter` around `setMarkdown`); fallback path is incremental `QTextCursor.insertText` |
| PyInstaller + PySide6 on macOS arm64 bundle size and signing | Out of scope for MVP; tracked separately for release |
| OpenAI vision pricing on long sessions | Cost display deferred (§11.7); user is aware of the cost dimension |
| Cross-platform path resolution | Centralized in `config/paths.py`; tested |

## 13. Out of Scope (Explicit Non-Goals for MVP)

- Implementing Anthropic or Gemini providers (stubs only)
- OS keyring integration
- Region-of-interest or multi-monitor screenshots
- Conversation history
- In-app quick-action editor
- Cost / token-usage display
- Auto-update infrastructure
- UI automation tests
- Code signing and notarization

## 14. Next Step

After user approval of this document, hand off to the `writing-plans` skill to produce a step-by-step implementation plan.
