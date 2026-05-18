# Providers + OpenAI-Compatible Relays Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt the official `openai` / `anthropic` / `google-genai` SDKs across all three providers, add a fourth `openai_compat` provider for third-party relays (OpenRouter, DeepSeek, Groq, Ollama, custom), add per-provider remote model refresh with `ProviderConfig.cached_models` persistence, and rewrite the Settings dialog around a `ProviderPane` widget.

**Architecture:** A new `ModelInfoDict` is added to `config/schema.py` to JSON-serialize cached model lists. The `LLMProvider` protocol grows a `fetch_remote_models()` method. Each provider's `__init__` constructs the corresponding SDK client (no network on construction); `stream()` translates internal Message objects to the SDK's content format and yields `StreamChunk` per SDK iterator boundary. `OpenAICompatProvider` subclasses `OpenAIProvider` to enforce `base_url` while reusing the streaming logic. A `ModelRefreshWorker` runs `provider.fetch_remote_models()` off the UI thread; on success, results are stored as `list[ModelInfoDict]` on `ProviderConfig` and persisted immediately via `ConfigStore.save()`.

**Tech Stack:** Python 3.11+, PySide6 (Qt for Python), pydantic v2, pytest + pytest-qt, openai SDK ≥1.50, anthropic SDK ≥0.40, google-genai SDK ≥1.0.

**Reference spec:** `docs/superpowers/specs/2026-05-18-providers-and-openai-compat-relays-design.md`

**Prerequisite spec:** `docs/superpowers/specs/2026-05-18-logs-request-context-and-timeout-design.md` (provides `ProviderOptions`, `RequestTimeoutError`, the `LogRow` plumbing, and the worker factory shape this plan extends). The plan for that spec must land before this one starts.

---

## Conventions

- **Use `.venv`.** Never `pip install` into system Python. If `.venv` does not exist: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`. All `pytest` / `mypy` / `ruff` commands assume `.venv/bin/...`.
- Run a single test: `.venv/bin/pytest tests/test_X.py::test_Y -v`
- Run the full suite: `.venv/bin/pytest -q`
- All new code lives under `src/spiresight/`; new tests under `tests/` (flat — matches existing pattern).
- Commit after each task once tests pass. Conventional-commit prefixes: `feat:`, `refactor:`, `test:`, `fix:`, `chore:`, `build:`.
- For Qt tests, use `pytest-qt`'s `qtbot` fixture. To wait for signals: `with qtbot.waitSignal(obj.signal_name, timeout=2000) as blocker: ...` then inspect `blocker.args`.
- For SDK-mocking tests, patch via `monkeypatch.setattr` on the module-level SDK symbol (e.g. `monkeypatch.setattr("spiresight.llm.providers.openai_provider.OpenAI", FakeOpenAI)`). Do NOT subclass `unittest.mock.MagicMock` for SDK error types — those need to be the real exception classes from the SDK because `except` clauses match by class.

---

## File Structure

**Create:**
- `src/spiresight/llm/capability_table.py` — `KNOWN_MODEL_CAPS`, `ASSUME_ALL_CAPS`, `infer_capabilities()`.
- `src/spiresight/llm/providers/openai_compat_provider.py` — `OpenAICompatProvider(OpenAIProvider)` + `RELAY_PRESETS`.
- `src/spiresight/ui/workers/model_refresh_worker.py` — `ModelRefreshWorker(QThread)`.
- `src/spiresight/ui/widgets/provider_pane.py` — `ProviderPane(QWidget)`.
- `tests/test_capability_table.py`
- `tests/test_provider_config_models.py`
- `tests/test_model_info_bridge.py`
- `tests/test_openai_compat_provider.py`
- `tests/test_anthropic_provider.py`
- `tests/test_gemini_provider.py`
- `tests/test_model_refresh_worker.py`
- `tests/test_provider_pane.py`
- `tests/test_settings_dialog_providers.py`

**Modify:**
- `pyproject.toml` — add `openai`, `anthropic`, `google-genai` deps.
- `src/spiresight/config/schema.py` — add `ModelInfoDict`, `cached_models` on `ProviderConfig`, narrow `active_provider` to Literal.
- `src/spiresight/llm/models.py` — add `ModelInfo.from_dict()` / `to_dict()` lazy-imported bridge.
- `src/spiresight/llm/errors.py` — add `MissingBaseURL`.
- `src/spiresight/llm/provider.py` — add `fetch_remote_models()` to the protocol.
- `src/spiresight/llm/registry.py` — register `"openai_compat"`.
- `src/spiresight/llm/providers/openai_provider.py` — rewrite around openai SDK; add `fetch_remote_models()`.
- `src/spiresight/llm/providers/anthropic_provider.py` — implement via anthropic SDK.
- `src/spiresight/llm/providers/gemini_provider.py` — implement via google-genai SDK.
- `src/spiresight/ui/windows/settings_dialog.py` — replace API Keys tab with nested Providers tab + ProviderPanes.
- `src/spiresight/ui/windows/main_window.py` — connect `models_refreshed` / `models_refresh_failed` signals.
- `tests/test_registry.py` — add `openai_compat` case.
- `tests/test_provider_stubs.py` — relax expectations (stubs are now real).

---

### Task 1: Bump dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add SDK deps to the `dependencies` list**

Edit `pyproject.toml`. Append to the `dependencies` array:

```toml
dependencies = [
  "PySide6>=6.6",
  "mss>=9.0",
  "pynput>=1.7",
  "httpx>=0.27",
  "markdown-it-py>=3.0",
  "pydantic>=2.6",
  "pydantic-settings>=2.2",
  "PyYAML>=6.0",
  "Pillow>=10.0",
  "Pygments>=2.17",
  "openai>=1.50.0",
  "anthropic>=0.40.0",
  "google-genai>=1.0.0",
]
```

Delete the long historical comment about httpx vs SDK (lines below the dependencies array) — the rationale no longer holds once we adopt the SDK. The comment block starts with `# NOTE: Spec §3 names...` and ends before `[project.optional-dependencies]`.

- [ ] **Step 2: Install into the venv**

```bash
.venv/bin/pip install -e ".[dev]"
```

Expected: pip resolves and installs `openai`, `anthropic`, `google-genai` plus transitive deps (`google-auth`, `websockets`, etc.). No `error` exit.

- [ ] **Step 3: Verify imports work**

```bash
.venv/bin/python -c "import openai, anthropic, google.genai; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Run the existing suite once to confirm no regression**

```bash
.venv/bin/pytest -q
```

Expected: all passing (no behavior changed yet, just deps added).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "build: add openai/anthropic/google-genai SDK dependencies"
```

---

### Task 2: `ModelInfoDict` + `cached_models` on `ProviderConfig`

**Files:**
- Modify: `src/spiresight/config/schema.py`
- Test: `tests/test_provider_config_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_provider_config_models.py`:

```python
import json

from spiresight.config.schema import AppConfig, ModelInfoDict, ProviderConfig


def test_model_info_dict_defaults():
    d = ModelInfoDict(id="gpt-4o", display_name="GPT-4o")
    assert d.capabilities == []
    assert d.context_window == 0


def test_provider_config_default_cached_models_empty():
    pc = ProviderConfig()
    assert pc.cached_models == []


def test_provider_config_with_cached_models_roundtrip():
    pc = ProviderConfig(
        api_key="sk-x",
        base_url="https://api.example.com/v1",
        cached_models=[
            ModelInfoDict(
                id="gpt-4o",
                display_name="GPT-4o",
                capabilities=["vision", "tool_use", "json_mode"],
                context_window=128_000,
            ),
        ],
    )
    encoded = pc.model_dump_json()
    decoded = ProviderConfig.model_validate_json(encoded)
    assert decoded == pc


def test_app_config_active_provider_literal_rejects_unknown():
    import pydantic
    with pydantic.ValidationError if False else __import__("pytest").raises(pydantic.ValidationError):
        AppConfig(active_provider="bogus")  # type: ignore[arg-type]


def test_app_config_active_provider_accepts_openai_compat():
    cfg = AppConfig(active_provider="openai_compat")
    assert cfg.active_provider == "openai_compat"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/bin/pytest tests/test_provider_config_models.py -v
```

Expected: FAIL with `ImportError: cannot import name 'ModelInfoDict'`.

- [ ] **Step 3: Add `ModelInfoDict` and update `ProviderConfig` + `AppConfig`**

Edit `src/spiresight/config/schema.py`. Replace the file with:

```python
"""Pydantic schemas for app and provider configuration.

NOTE(security): ProviderConfig.api_key holds the key in plaintext.
This is the deliberate MVP choice — migrate to OS keyring later.
See docs/superpowers/specs/2026-05-15-spiresight-mvp-design.md §11.1.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelInfoDict(BaseModel):
    """JSON-serializable mirror of llm.models.ModelInfo for ProviderConfig."""
    id: str
    display_name: str
    capabilities: list[Literal["vision", "tool_use", "json_mode", "thinking"]] = Field(
        default_factory=list
    )
    context_window: int = 0


class ProviderConfig(BaseModel):
    api_key: str = ""
    base_url: str | None = None
    cached_models: list[ModelInfoDict] = Field(default_factory=list)


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    active_provider: Literal["openai", "openai_compat", "anthropic", "gemini"] = "openai"
    active_model: str = "gpt-4o"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    language: Literal["en", "zh"] = "en"
    theme: str = "dark_fantasy"
    always_on_top: bool = True
    mini_bar_mode: bool = False
    hotkey: str = "<ctrl>+<shift>+s"
    last_used_prompt_id: str | None = None
    include_screenshot_default: bool = True
    request_timeout_seconds: int = 180
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_provider_config_models.py tests/test_config_store.py -v
```

Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/config/schema.py tests/test_provider_config_models.py
git commit -m "feat(config): add ModelInfoDict + cached_models, narrow active_provider Literal"
```

---

### Task 3: `ModelInfo.from_dict()` / `to_dict()` bridge

**Files:**
- Modify: `src/spiresight/llm/models.py`
- Test: `tests/test_model_info_bridge.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_model_info_bridge.py`:

```python
from spiresight.config.schema import ModelInfoDict
from spiresight.llm.capabilities import Capability
from spiresight.llm.models import ModelInfo


def test_to_dict_then_from_dict_roundtrip():
    info = ModelInfo(
        id="gpt-4o",
        display_name="GPT-4o",
        capabilities=frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE}),
        context_window=128_000,
    )
    d = info.to_dict()
    assert isinstance(d, ModelInfoDict)
    assert set(d.capabilities) == {"vision", "tool_use", "json_mode"}
    info2 = ModelInfo.from_dict(d)
    assert info2 == info


def test_from_dict_empty_capabilities():
    d = ModelInfoDict(id="x", display_name="X")
    info = ModelInfo.from_dict(d)
    assert info.capabilities == frozenset()
    assert info.context_window == 0
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/bin/pytest tests/test_model_info_bridge.py -v
```

Expected: FAIL with `AttributeError: ... has no attribute 'to_dict'`.

- [ ] **Step 3: Add the bridge methods**

Edit `src/spiresight/llm/models.py`:

```python
# src/spiresight/llm/models.py
from __future__ import annotations
from dataclasses import dataclass

from .capabilities import Capability


@dataclass(frozen=True)
class ModelInfo:
    id: str
    display_name: str
    capabilities: frozenset[Capability]
    context_window: int

    def has(self, cap: Capability) -> bool:
        return cap in self.capabilities

    @classmethod
    def from_dict(cls, d) -> "ModelInfo":
        from spiresight.config.schema import ModelInfoDict   # lazy import
        if not isinstance(d, ModelInfoDict):
            raise TypeError(f"expected ModelInfoDict, got {type(d).__name__}")
        return cls(
            id=d.id,
            display_name=d.display_name,
            capabilities=frozenset(Capability(c) for c in d.capabilities),
            context_window=d.context_window,
        )

    def to_dict(self):
        from spiresight.config.schema import ModelInfoDict   # lazy import
        return ModelInfoDict(
            id=self.id,
            display_name=self.display_name,
            capabilities=[c.value for c in self.capabilities],
            context_window=self.context_window,
        )
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_model_info_bridge.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/llm/models.py tests/test_model_info_bridge.py
git commit -m "feat(llm): add ModelInfo ↔ ModelInfoDict bridge"
```

---

### Task 4: `MissingBaseURL` error

**Files:**
- Modify: `src/spiresight/llm/errors.py`
- Test: `tests/test_provider_contract.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_provider_contract.py`:

```python
def test_missing_base_url_error():
    from spiresight.llm.errors import LLMError, MissingBaseURL
    exc = MissingBaseURL("openai_compat")
    assert isinstance(exc, LLMError)
    assert exc.provider == "openai_compat"
    assert "openai_compat" in str(exc)
    assert "base_url" in str(exc)
```

- [ ] **Step 2: Run to verify FAIL**

```bash
.venv/bin/pytest tests/test_provider_contract.py::test_missing_base_url_error -v
```

Expected: FAIL on import.

- [ ] **Step 3: Add the error class**

Edit `src/spiresight/llm/errors.py`. Append after the `MissingAPIKey` class:

```python
class MissingBaseURL(LLMError):
    def __init__(self, provider: str) -> None:
        super().__init__(f"Provider '{provider}' requires base_url to be set in Settings")
        self.provider = provider
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_provider_contract.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/llm/errors.py tests/test_provider_contract.py
git commit -m "feat(llm): add MissingBaseURL error"
```

---

### Task 5: Capability inference table

**Files:**
- Create: `src/spiresight/llm/capability_table.py`
- Test: `tests/test_capability_table.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_capability_table.py`:

```python
from spiresight.llm.capabilities import Capability
from spiresight.llm.capability_table import (
    ASSUME_ALL_CAPS, KNOWN_MODEL_CAPS, infer_capabilities,
)


def test_known_model_table_only_valid_capabilities():
    valid = set(Capability)
    for mid, caps in KNOWN_MODEL_CAPS.items():
        assert caps.issubset(valid), f"{mid} has invalid capability"


def test_infer_capabilities_table_hit():
    caps, inferred = infer_capabilities("gpt-4o")
    assert Capability.VISION in caps
    assert inferred is False


def test_infer_capabilities_prefix_hit():
    caps, inferred = infer_capabilities("gpt-4o-2024-08-06")
    assert Capability.VISION in caps
    assert inferred is False


def test_infer_capabilities_miss_returns_assume_all():
    caps, inferred = infer_capabilities("totally-new-model-xyz")
    assert caps == ASSUME_ALL_CAPS
    assert inferred is True


def test_assume_all_caps_contains_every_capability():
    assert ASSUME_ALL_CAPS == frozenset(Capability)
```

- [ ] **Step 2: Run to verify FAIL**

```bash
.venv/bin/pytest tests/test_capability_table.py -v
```

Expected: FAIL on import.

- [ ] **Step 3: Implement the module**

Create `src/spiresight/llm/capability_table.py`:

```python
"""Static model-id → capability map used by provider fetch_remote_models()
to assign capability flags to refreshed model lists. Unknown IDs assume all
capabilities are supported and the caller sets `params.capabilities_inferred`
in the LogRow so the inference is auditable.
"""
from __future__ import annotations

from spiresight.llm.capabilities import Capability

_V, _T, _J, _TH = Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING

KNOWN_MODEL_CAPS: dict[str, frozenset[Capability]] = {
    # ---- OpenAI ----
    "gpt-5":            frozenset({_V, _T, _J, _TH}),
    "gpt-5.5":          frozenset({_V, _T, _J, _TH}),
    "gpt-5-mini":       frozenset({_V, _T, _J, _TH}),
    "gpt-4o":           frozenset({_V, _T, _J}),
    "gpt-4o-mini":      frozenset({_V, _T, _J}),
    "o4-mini":          frozenset({_V, _T, _TH}),
    "o3":               frozenset({_V, _T, _TH}),
    "gpt-3.5-turbo":    frozenset({_T, _J}),

    # ---- Anthropic ----
    "claude-opus-4-7-20251015":    frozenset({_V, _T, _J, _TH}),
    "claude-sonnet-4-6-20251001":  frozenset({_V, _T, _J, _TH}),
    "claude-haiku-4-5-20251001":   frozenset({_V, _T, _J}),

    # ---- Gemini ----
    "gemini-2.5-pro":         frozenset({_V, _T, _J, _TH}),
    "gemini-2.5-flash":       frozenset({_V, _T, _J, _TH}),
    "gemini-2.5-flash-lite":  frozenset({_V, _T, _J}),

    # ---- OpenRouter aliases ----
    "anthropic/claude-opus-4-7":       frozenset({_V, _T, _J, _TH}),
    "google/gemini-2.5-pro":           frozenset({_V, _T, _J, _TH}),
    "deepseek/deepseek-chat":          frozenset({_T, _J}),
    "deepseek/deepseek-reasoner":      frozenset({_T, _TH}),
    "meta-llama/llama-3.3-70b":        frozenset({_T}),

    # ---- DeepSeek direct ----
    "deepseek-chat":      frozenset({_T, _J}),
    "deepseek-reasoner":  frozenset({_T, _TH}),

    # ---- Groq ----
    "llama-3.3-70b-versatile":        frozenset({_T}),
    "llama-3.1-8b-instant":           frozenset({_T}),
    "mixtral-8x7b-32768":             frozenset({_T}),
}

ASSUME_ALL_CAPS: frozenset[Capability] = frozenset({_V, _T, _J, _TH})


def infer_capabilities(model_id: str) -> tuple[frozenset[Capability], bool]:
    """Return (caps, is_inferred). is_inferred=True when the table missed."""
    if model_id in KNOWN_MODEL_CAPS:
        return KNOWN_MODEL_CAPS[model_id], False
    for known, caps in KNOWN_MODEL_CAPS.items():
        if model_id == known or model_id.startswith(known + "-"):
            return caps, False
    return ASSUME_ALL_CAPS, True
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_capability_table.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/llm/capability_table.py tests/test_capability_table.py
git commit -m "feat(llm): add capability inference table"
```

---

### Task 6: `LLMProvider` protocol extension

**Files:**
- Modify: `src/spiresight/llm/provider.py`
- Test: `tests/test_provider_contract.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_provider_contract.py`:

```python
def test_provider_protocol_includes_fetch_remote_models():
    from spiresight.llm.provider import LLMProvider
    import inspect
    members = dict(inspect.getmembers(LLMProvider))
    assert "fetch_remote_models" in members
```

- [ ] **Step 2: Run to verify FAIL**

```bash
.venv/bin/pytest tests/test_provider_contract.py::test_provider_protocol_includes_fetch_remote_models -v
```

Expected: FAIL.

- [ ] **Step 3: Extend the protocol**

Edit `src/spiresight/llm/provider.py`. Inside the `LLMProvider` Protocol class, after `list_models`:

```python
    def fetch_remote_models(self) -> list[ModelInfo]:
        """Fetch models from the upstream API. May raise LLMError on failure."""
        ...
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_provider_contract.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/llm/provider.py tests/test_provider_contract.py
git commit -m "feat(llm): add fetch_remote_models to LLMProvider protocol"
```

---

### Task 7: Rewrite `OpenAIProvider` around the openai SDK

**Files:**
- Modify: `src/spiresight/llm/providers/openai_provider.py` (full rewrite)
- Test: `tests/test_openai_provider.py` (rewrite — existing httpx-based tests no longer apply)

- [ ] **Step 1: Read the existing tests file**

```bash
cat tests/test_openai_provider.py
```

Note: existing tests likely use `respx` to mock httpx. Those become obsolete. Salvage any test names that map to SDK behavior; otherwise prepare to replace the file.

- [ ] **Step 2: Write the new failing tests**

Replace `tests/test_openai_provider.py` with:

```python
from __future__ import annotations

import pytest

from spiresight.config.schema import ProviderConfig
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import (
    AuthError, MissingAPIKey, NetworkError, RateLimitError, RequestTimeoutError,
)
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.openai_provider import OpenAIProvider


class FakeChoice:
    def __init__(self, content="", finish_reason=None):
        self.delta = type("D", (), {"content": content})()
        self.finish_reason = finish_reason


class FakeEvent:
    def __init__(self, choices=None, usage=None):
        self.choices = choices or []
        self.usage = usage


class FakeUsage:
    def __init__(self, prompt, completion):
        self.prompt_tokens = prompt
        self.completion_tokens = completion


class FakeStream:
    """Context manager that yields a fixed sequence of FakeEvent."""
    def __init__(self, events):
        self._events = events
    def __enter__(self): return iter(self._events)
    def __exit__(self, *exc): return False


class FakeCompletions:
    def __init__(self, events=None, raises=None):
        self._events = events or []
        self._raises = raises
    def create(self, **kwargs):
        if self._raises is not None:
            raise self._raises
        return FakeStream(self._events)


class FakeModelsList:
    def __init__(self, data):
        self.data = data


class FakeModels:
    def __init__(self, data=None, raises=None):
        self._data = data or []
        self._raises = raises
    def list(self):
        if self._raises:
            raise self._raises
        return FakeModelsList(self._data)


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeOpenAI:
    def __init__(self, *, api_key, base_url, timeout, max_retries):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.chat = None       # filled by test
        self.models = None     # filled by test


def _make(monkeypatch, *, events=None, raises=None, models_data=None, models_raises=None):
    holder = {}
    def factory(**kwargs):
        client = FakeOpenAI(**kwargs)
        client.chat = FakeChat(FakeCompletions(events=events, raises=raises))
        client.models = FakeModels(data=models_data, raises=models_raises)
        holder["client"] = client
        return client
    monkeypatch.setattr("spiresight.llm.providers.openai_provider.OpenAI", factory)
    provider = OpenAIProvider(
        ProviderConfig(api_key="sk-x"),
        ProviderOptions(request_timeout_seconds=30),
    )
    return provider, holder


def test_constructs_with_default_base_url(monkeypatch):
    p, holder = _make(monkeypatch)
    assert holder["client"].base_url == "https://api.openai.com/v1"


def test_stream_yields_text_then_usage(monkeypatch):
    events = [
        FakeEvent(choices=[FakeChoice(content="hello ")]),
        FakeEvent(choices=[FakeChoice(content="world", finish_reason="stop")]),
        FakeEvent(usage=FakeUsage(prompt=10, completion=5)),
    ]
    p, _ = _make(monkeypatch, events=events)
    chunks = list(p.stream(model="gpt-4o", system="s", user_text="hi"))
    texts = [c.text_delta for c in chunks if c.text_delta]
    assert "".join(texts) == "hello world"
    usage_chunks = [c for c in chunks if c.usage is not None]
    assert len(usage_chunks) == 1
    assert usage_chunks[0].usage.input_tokens == 10


def test_stream_raises_missing_api_key():
    p = OpenAIProvider(ProviderConfig(api_key=""), ProviderOptions())
    with pytest.raises(MissingAPIKey):
        list(p.stream(model="gpt-4o", system="s", user_text="hi"))


def test_stream_wraps_api_timeout(monkeypatch):
    import openai
    exc = openai.APITimeoutError(request=None)
    p, _ = _make(monkeypatch, raises=exc)
    with pytest.raises(RequestTimeoutError):
        list(p.stream(model="gpt-4o", system="s", user_text="hi"))


def test_stream_wraps_401(monkeypatch):
    import openai
    import httpx
    resp = httpx.Response(401, request=httpx.Request("POST", "https://x"))
    body = {"error": {"message": "unauthorized"}}
    p, _ = _make(monkeypatch, raises=openai.APIStatusError("unauthorized", response=resp, body=body))
    with pytest.raises(AuthError):
        list(p.stream(model="gpt-4o", system="s", user_text="hi"))


def test_stream_wraps_429(monkeypatch):
    import openai
    import httpx
    resp = httpx.Response(429, request=httpx.Request("POST", "https://x"),
                          headers={"retry-after": "30"})
    body = {"error": {"message": "rate limited"}}
    p, _ = _make(monkeypatch, raises=openai.RateLimitError("rate limited", response=resp, body=body))
    with pytest.raises(RateLimitError):
        list(p.stream(model="gpt-4o", system="s", user_text="hi"))


def test_fetch_remote_models_returns_known_capabilities(monkeypatch):
    class FakeModelEntry:
        def __init__(self, mid): self.id = mid
    p, _ = _make(monkeypatch, models_data=[FakeModelEntry("gpt-4o"), FakeModelEntry("totally-unknown-xyz")])
    models = p.fetch_remote_models()
    assert {m.id for m in models} == {"gpt-4o", "totally-unknown-xyz"}
    gpt4o = next(m for m in models if m.id == "gpt-4o")
    assert Capability.VISION in gpt4o.capabilities


def test_list_models_prefers_cached(monkeypatch):
    from spiresight.config.schema import ModelInfoDict
    cfg = ProviderConfig(
        api_key="sk-x",
        cached_models=[ModelInfoDict(id="cached-model", display_name="C", capabilities=["json_mode"])],
    )
    monkeypatch.setattr(
        "spiresight.llm.providers.openai_provider.OpenAI",
        lambda **kw: type("F", (), {"chat": None, "models": None})(),
    )
    p = OpenAIProvider(cfg, ProviderOptions())
    models = p.list_models()
    assert len(models) == 1
    assert models[0].id == "cached-model"
```

- [ ] **Step 3: Run to verify FAIL**

```bash
.venv/bin/pytest tests/test_openai_provider.py -v
```

Expected: FAIL on first import / construction.

- [ ] **Step 4: Rewrite the provider**

Replace `src/spiresight/llm/providers/openai_provider.py` with:

```python
"""OpenAI Chat Completions streaming provider, via the official openai SDK.

Cancellation works at the SDK iterator boundary: between each yielded event
we check cancel_event.is_set(). The SDK's chunking is granular enough for
Qt's UX needs (the user's "cancel" click typically arrives between SSE
chunks anyway). max_retries=0 keeps error semantics predictable.
"""
from __future__ import annotations

import base64
import threading
from collections.abc import Iterator
from typing import Final

from openai import OpenAI, APIConnectionError, APIStatusError, APITimeoutError, RateLimitError as OpenAIRateLimitError

from spiresight.config.schema import ProviderConfig
from spiresight.core.usage import TokenUsage
from spiresight.llm.capabilities import Capability
from spiresight.llm.capability_table import infer_capabilities
from spiresight.llm.errors import (
    AuthError, MissingAPIKey, MissingBaseURL, NetworkError, RateLimitError, RequestTimeoutError,
)
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import ProviderOptions, StreamChunk


_BUILTIN_DEFAULTS: Final[list[ModelInfo]] = [
    ModelInfo("gpt-5.5", "GPT-5.5",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING}),
              context_window=128_000),
    ModelInfo("gpt-5", "GPT-5",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING}),
              context_window=128_000),
    ModelInfo("gpt-5-mini", "GPT-5 mini",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING}),
              context_window=128_000),
    ModelInfo("o4-mini", "o4-mini",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.THINKING}),
              context_window=200_000),
    ModelInfo("o3", "o3",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.THINKING}),
              context_window=200_000),
    ModelInfo("gpt-4o", "GPT-4o",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE}),
              context_window=128_000),
    ModelInfo("gpt-4o-mini", "GPT-4o mini",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE}),
              context_window=128_000),
    ModelInfo("gpt-3.5-turbo", "GPT-3.5 Turbo",
              frozenset({Capability.TOOL_USE, Capability.JSON_MODE}),
              context_window=16_000),
]


class OpenAIProvider:
    name = "openai"
    _DEFAULT_BASE: str | None = "https://api.openai.com/v1"
    _BUILTIN_DEFAULTS: list[ModelInfo] = _BUILTIN_DEFAULTS

    def __init__(self, config: ProviderConfig, options: ProviderOptions) -> None:
        self._config = config
        self._options = options
        base = config.base_url or self._DEFAULT_BASE
        if base is None:
            raise MissingBaseURL(self.name)
        self._client = OpenAI(
            api_key=config.api_key or "missing",
            base_url=base,
            timeout=float(options.request_timeout_seconds),
            max_retries=0,
        )

    def list_models(self) -> list[ModelInfo]:
        if self._config.cached_models:
            return [ModelInfo.from_dict(m) for m in self._config.cached_models]
        return list(self._BUILTIN_DEFAULTS)

    def fetch_remote_models(self) -> list[ModelInfo]:
        try:
            resp = self._client.models.list()
        except APITimeoutError as exc:
            raise RequestTimeoutError(
                f"Refresh timed out after {self._options.request_timeout_seconds}s"
            ) from exc
        except APIStatusError as exc:
            if exc.status_code == 401:
                raise AuthError("Invalid OpenAI API key") from exc
            raise NetworkError(f"HTTP {exc.status_code}: {exc}") from exc
        except APIConnectionError as exc:
            raise NetworkError(str(exc)) from exc

        out: list[ModelInfo] = []
        for m in resp.data:
            caps, _inferred = infer_capabilities(m.id)
            out.append(ModelInfo(
                id=m.id, display_name=m.id,
                capabilities=caps, context_window=0,
            ))
        return out

    def stream(
        self,
        *,
        model: str,
        system: str,
        user_text: str = "",
        images: list[bytes] = (),  # type: ignore[assignment]
        cancel_event: threading.Event = None,  # type: ignore[assignment]
        json_mode: bool = False,
        messages: list | None = None,
    ) -> Iterator[StreamChunk]:
        if not self._config.api_key:
            raise MissingAPIKey(self.name)
        cancel_event = cancel_event or threading.Event()

        api_messages = (
            self._build_messages(system, messages)
            if messages is not None
            else [
                {"role": "system", "content": system},
                {"role": "user", "content": self._build_user_content(user_text, images)},
            ]
        )
        kwargs: dict[str, object] = {
            "model": model,
            "messages": api_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            with self._client.chat.completions.create(**kwargs) as stream:
                for event in stream:
                    if cancel_event.is_set():
                        return
                    if getattr(event, "usage", None):
                        yield StreamChunk(
                            text_delta="",
                            finish_reason=None,
                            usage=TokenUsage(
                                input_tokens=int(event.usage.prompt_tokens or 0),
                                output_tokens=int(event.usage.completion_tokens or 0),
                            ),
                        )
                    choices = event.choices or []
                    if not choices:
                        continue
                    delta = choices[0].delta
                    finish = choices[0].finish_reason
                    text = (delta.content or "") if delta else ""
                    if text or finish:
                        yield StreamChunk(text_delta=text, finish_reason=finish, usage=None)
        except APITimeoutError as exc:
            raise RequestTimeoutError(
                f"Request exceeded {self._options.request_timeout_seconds}s timeout"
            ) from exc
        except OpenAIRateLimitError as exc:
            retry = exc.response.headers.get("retry-after") if getattr(exc, "response", None) else None
            raise RateLimitError(float(retry) if retry else None) from exc
        except APIStatusError as exc:
            if exc.status_code == 401:
                raise AuthError("Invalid OpenAI API key") from exc
            if exc.status_code == 429:
                raise RateLimitError() from exc
            raise NetworkError(f"HTTP {exc.status_code}: {exc}") from exc
        except APIConnectionError as exc:
            raise NetworkError(str(exc)) from exc

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

    @staticmethod
    def _build_messages(system: str, messages: list) -> list[dict]:
        """Build OpenAI-format messages array from conversation history."""
        result: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m.image_png is not None and m.role == "user":
                b64 = base64.b64encode(m.image_png).decode()
                result.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": m.text},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                })
            else:
                result.append({"role": m.role, "content": m.text})
        return result
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_openai_provider.py tests/test_openai_timeout.py -v
```

Expected: all pass. If `tests/test_openai_timeout.py` (from spec #1) tested the httpx path, port it: it should now patch the SDK and use `openai.APITimeoutError` instead of `httpx.ReadTimeout`. Update inline if needed; the assertions about wrapping into `RequestTimeoutError` survive.

- [ ] **Step 6: Commit**

```bash
git add src/spiresight/llm/providers/openai_provider.py tests/test_openai_provider.py tests/test_openai_timeout.py
git commit -m "refactor(openai): rewrite provider around openai SDK + add fetch_remote_models"
```

---

### Task 8: `OpenAICompatProvider` + RELAY_PRESETS

**Files:**
- Create: `src/spiresight/llm/providers/openai_compat_provider.py`
- Test: `tests/test_openai_compat_provider.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_openai_compat_provider.py`:

```python
import pytest

from spiresight.config.schema import ProviderConfig
from spiresight.llm.errors import MissingBaseURL
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.openai_compat_provider import (
    OpenAICompatProvider, RELAY_PRESETS,
)


def test_relay_presets_includes_openrouter_and_deepseek():
    assert "OpenRouter" in RELAY_PRESETS
    assert "DeepSeek" in RELAY_PRESETS
    assert "Groq" in RELAY_PRESETS
    assert "Ollama local" in RELAY_PRESETS
    assert RELAY_PRESETS["OpenRouter"].endswith("/v1")


def test_constructs_without_base_url_raises(monkeypatch):
    monkeypatch.setattr(
        "spiresight.llm.providers.openai_provider.OpenAI",
        lambda **kw: object(),
    )
    with pytest.raises(MissingBaseURL):
        OpenAICompatProvider(ProviderConfig(api_key="sk-x"), ProviderOptions())


def test_constructs_with_base_url(monkeypatch):
    monkeypatch.setattr(
        "spiresight.llm.providers.openai_provider.OpenAI",
        lambda **kw: object(),
    )
    p = OpenAICompatProvider(
        ProviderConfig(api_key="sk-x", base_url="http://localhost:11434/v1"),
        ProviderOptions(),
    )
    assert p.name == "openai_compat"


def test_builtin_defaults_empty(monkeypatch):
    monkeypatch.setattr(
        "spiresight.llm.providers.openai_provider.OpenAI",
        lambda **kw: object(),
    )
    p = OpenAICompatProvider(
        ProviderConfig(api_key="sk-x", base_url="http://x/v1"),
        ProviderOptions(),
    )
    assert p._BUILTIN_DEFAULTS == []
    assert p.list_models() == []
```

- [ ] **Step 2: Run to verify FAIL**

```bash
.venv/bin/pytest tests/test_openai_compat_provider.py -v
```

Expected: FAIL on import.

- [ ] **Step 3: Implement the provider**

Create `src/spiresight/llm/providers/openai_compat_provider.py`:

```python
"""OpenAI-compatible relay provider.

Subclasses OpenAIProvider — same wire protocol, same SDK, just a different
base_url and no built-in model list. Designed for OpenRouter, DeepSeek,
Groq, Ollama, or arbitrary custom endpoints.
"""
from __future__ import annotations

from typing import Final

from spiresight.llm.models import ModelInfo
from spiresight.llm.providers.openai_provider import OpenAIProvider


RELAY_PRESETS: Final[dict[str, str]] = {
    "OpenRouter":   "https://openrouter.ai/api/v1",
    "DeepSeek":     "https://api.deepseek.com/v1",
    "Groq":         "https://api.groq.com/openai/v1",
    "Ollama local": "http://localhost:11434/v1",
}


class OpenAICompatProvider(OpenAIProvider):
    """OpenAI Chat Completions API against a third-party relay.

    Inherits stream() and fetch_remote_models() unchanged. Differences:
      - name is "openai_compat"
      - base_url is required (no fallback to api.openai.com)
      - _BUILTIN_DEFAULTS is empty: model selection comes entirely from the
        cached_models populated by the user's Settings Refresh action.
    """
    name = "openai_compat"
    _DEFAULT_BASE: str | None = None
    _BUILTIN_DEFAULTS: list[ModelInfo] = []
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_openai_compat_provider.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/llm/providers/openai_compat_provider.py tests/test_openai_compat_provider.py
git commit -m "feat(llm): add OpenAICompatProvider + RELAY_PRESETS"
```

---

### Task 9: Implement `AnthropicProvider`

**Files:**
- Modify: `src/spiresight/llm/providers/anthropic_provider.py` (full rewrite)
- Test: `tests/test_anthropic_provider.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_anthropic_provider.py`:

```python
from __future__ import annotations

import pytest

from spiresight.config.schema import ProviderConfig
from spiresight.core.messages import Message
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import AuthError, MissingAPIKey, RequestTimeoutError
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.anthropic_provider import AnthropicProvider


class FakeDelta:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


class FakeEvent:
    def __init__(self, type_, delta=None):
        self.type = type_
        self.delta = delta


class FakeMessageSnapshot:
    def __init__(self, in_tok, out_tok):
        self.usage = type("U", (), {"input_tokens": in_tok, "output_tokens": out_tok})()


class FakeStream:
    def __init__(self, events, snapshot=None):
        self._events = events
        self.current_message_snapshot = snapshot
    def __enter__(self): return iter(self._events)
    def __exit__(self, *exc): return False


class FakeMessages:
    def __init__(self, events=None, raises=None, snapshot=None):
        self._events = events or []
        self._raises = raises
        self._snapshot = snapshot
        self.kwargs_seen: dict | None = None
    def stream(self, **kwargs):
        self.kwargs_seen = kwargs
        if self._raises is not None:
            raise self._raises
        f = FakeStream(self._events, snapshot=self._snapshot)
        # Anthropic SDK lets you read snapshot via the context obj — emulate.
        f.current_message_snapshot = self._snapshot
        return f


class FakeModelsList:
    def __init__(self, data):
        self.data = data


class FakeModelsAPI:
    def __init__(self, data=None, raises=None):
        self._data = data or []
        self._raises = raises
    def list(self, limit=100):
        if self._raises:
            raise self._raises
        return FakeModelsList(self._data)


class FakeAnthropic:
    def __init__(self, *, api_key, base_url, timeout, max_retries):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.messages = None
        self.models = None


def _make(monkeypatch, *, events=None, raises=None, snapshot=None,
          models_data=None, models_raises=None):
    holder = {}
    def factory(**kwargs):
        client = FakeAnthropic(**kwargs)
        client.messages = FakeMessages(events=events, raises=raises, snapshot=snapshot)
        client.models = FakeModelsAPI(data=models_data, raises=models_raises)
        holder["client"] = client
        return client
    monkeypatch.setattr("spiresight.llm.providers.anthropic_provider.Anthropic", factory)
    p = AnthropicProvider(ProviderConfig(api_key="key"), ProviderOptions(request_timeout_seconds=20))
    return p, holder


def test_stream_yields_text_then_usage_on_stop(monkeypatch):
    events = [
        FakeEvent("content_block_delta", delta=FakeDelta("text_delta", text="hello ")),
        FakeEvent("content_block_delta", delta=FakeDelta("text_delta", text="world")),
        FakeEvent("message_stop"),
    ]
    snap = FakeMessageSnapshot(in_tok=12, out_tok=4)
    p, _ = _make(monkeypatch, events=events, snapshot=snap)
    chunks = list(p.stream(model="claude-x", system="SYS", user_text="hi"))
    texts = "".join(c.text_delta for c in chunks if c.text_delta)
    assert texts == "hello world"
    usage = next(c for c in chunks if c.usage is not None)
    assert usage.usage.input_tokens == 12
    assert usage.usage.output_tokens == 4


def test_stream_passes_system_as_top_level_kwarg(monkeypatch):
    p, holder = _make(monkeypatch, events=[FakeEvent("message_stop")], snapshot=FakeMessageSnapshot(0, 0))
    list(p.stream(model="claude-x", system="MY-SYS", user_text="hi"))
    seen = holder["client"].messages.kwargs_seen
    assert seen["system"] == "MY-SYS"
    assert all(m.get("role") != "system" for m in seen["messages"])


def test_stream_missing_api_key_raises():
    p = AnthropicProvider(ProviderConfig(api_key=""), ProviderOptions())
    with pytest.raises(MissingAPIKey):
        list(p.stream(model="claude-x", system="s", user_text="hi"))


def test_stream_wraps_api_timeout(monkeypatch):
    import anthropic
    p, _ = _make(monkeypatch, raises=anthropic.APITimeoutError(request=None))
    with pytest.raises(RequestTimeoutError):
        list(p.stream(model="claude-x", system="s", user_text="hi"))


def test_stream_wraps_401(monkeypatch):
    import anthropic
    import httpx
    resp = httpx.Response(401, request=httpx.Request("POST", "https://x"))
    p, _ = _make(monkeypatch, raises=anthropic.APIStatusError("nope", response=resp, body={}))
    with pytest.raises(AuthError):
        list(p.stream(model="claude-x", system="s", user_text="hi"))


def test_build_messages_image_format(monkeypatch):
    p, holder = _make(monkeypatch, events=[FakeEvent("message_stop")], snapshot=FakeMessageSnapshot(0, 0))
    list(p.stream(
        model="claude-x", system="s",
        messages=[Message(role="user", text="look", image_png=b"\x89PNG_FAKE")],
    ))
    seen = holder["client"].messages.kwargs_seen
    msg = seen["messages"][0]
    assert msg["role"] == "user"
    assert isinstance(msg["content"], list)
    assert msg["content"][0] == {"type": "text", "text": "look"}
    assert msg["content"][1]["type"] == "image"
    assert msg["content"][1]["source"]["media_type"] == "image/png"


def test_fetch_remote_models_assigns_known_caps(monkeypatch):
    class FakeM:
        def __init__(self, mid, display=None):
            self.id = mid
            self.display_name = display or mid
    p, _ = _make(monkeypatch, models_data=[FakeM("claude-opus-4-7-20251015")])
    models = p.fetch_remote_models()
    assert models[0].capabilities >= frozenset({Capability.VISION, Capability.JSON_MODE})
```

- [ ] **Step 2: Run to verify FAIL**

```bash
.venv/bin/pytest tests/test_anthropic_provider.py -v
```

Expected: FAIL — current provider is a stub.

- [ ] **Step 3: Implement the provider**

Replace `src/spiresight/llm/providers/anthropic_provider.py` with:

```python
"""Anthropic streaming provider via the official anthropic SDK."""
from __future__ import annotations

import base64
import threading
from collections.abc import Iterator
from typing import Final

from anthropic import (
    Anthropic, APIConnectionError, APIStatusError, APITimeoutError, RateLimitError as AnthropicRateLimitError,
)

from spiresight.config.schema import ProviderConfig
from spiresight.core.usage import TokenUsage
from spiresight.llm.capabilities import Capability
from spiresight.llm.capability_table import infer_capabilities
from spiresight.llm.errors import (
    AuthError, MissingAPIKey, NetworkError, RateLimitError, RequestTimeoutError,
)
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import ProviderOptions, StreamChunk


_BUILTIN_DEFAULTS: Final[list[ModelInfo]] = [
    ModelInfo("claude-opus-4-7-20251015", "Claude Opus 4.7",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING}),
              context_window=200_000),
    ModelInfo("claude-sonnet-4-6-20251001", "Claude Sonnet 4.6",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING}),
              context_window=200_000),
    ModelInfo("claude-haiku-4-5-20251001", "Claude Haiku 4.5",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE}),
              context_window=200_000),
]


class AnthropicProvider:
    name = "anthropic"
    _BUILTIN_DEFAULTS: list[ModelInfo] = _BUILTIN_DEFAULTS

    def __init__(self, config: ProviderConfig, options: ProviderOptions) -> None:
        self._config = config
        self._options = options
        self._client = Anthropic(
            api_key=config.api_key or "missing",
            base_url=config.base_url,
            timeout=float(options.request_timeout_seconds),
            max_retries=0,
        )

    def list_models(self) -> list[ModelInfo]:
        if self._config.cached_models:
            return [ModelInfo.from_dict(m) for m in self._config.cached_models]
        return list(self._BUILTIN_DEFAULTS)

    def fetch_remote_models(self) -> list[ModelInfo]:
        try:
            resp = self._client.models.list(limit=100)
        except APITimeoutError as exc:
            raise RequestTimeoutError("Anthropic models.list timed out") from exc
        except APIStatusError as exc:
            if exc.status_code == 401:
                raise AuthError("Invalid Anthropic API key") from exc
            raise NetworkError(f"HTTP {exc.status_code}: {exc}") from exc
        except APIConnectionError as exc:
            raise NetworkError(str(exc)) from exc

        out: list[ModelInfo] = []
        for m in resp.data:
            caps, _ = infer_capabilities(m.id)
            out.append(ModelInfo(
                id=m.id,
                display_name=getattr(m, "display_name", m.id) or m.id,
                capabilities=caps,
                context_window=200_000,
            ))
        return out

    def stream(
        self,
        *,
        model: str,
        system: str,
        user_text: str = "",
        images: list[bytes] = (),  # type: ignore[assignment]
        cancel_event: threading.Event | None = None,
        json_mode: bool = False,
        messages: list | None = None,
    ) -> Iterator[StreamChunk]:
        del json_mode  # Anthropic has no native JSON mode; rely on system prompt
        if not self._config.api_key:
            raise MissingAPIKey(self.name)
        cancel_event = cancel_event or threading.Event()

        api_messages = self._build_messages(messages, user_text, images)
        kwargs: dict[str, object] = {
            "model": model,
            "max_tokens": 8192,
            "system": system,
            "messages": api_messages,
        }

        try:
            with self._client.messages.stream(**kwargs) as stream:
                snapshot_holder = getattr(stream, "current_message_snapshot", None)
                for event in stream:
                    if cancel_event.is_set():
                        return
                    if event.type == "content_block_delta" and getattr(event.delta, "type", "") == "text_delta":
                        yield StreamChunk(text_delta=event.delta.text, finish_reason=None, usage=None)
                    elif event.type == "message_stop":
                        snap = snapshot_holder or getattr(stream, "current_message_snapshot", None)
                        usage = None
                        if snap is not None and getattr(snap, "usage", None) is not None:
                            usage = TokenUsage(
                                input_tokens=int(snap.usage.input_tokens or 0),
                                output_tokens=int(snap.usage.output_tokens or 0),
                            )
                        yield StreamChunk(text_delta="", finish_reason="stop", usage=usage)
        except APITimeoutError as exc:
            raise RequestTimeoutError(
                f"Request exceeded {self._options.request_timeout_seconds}s timeout"
            ) from exc
        except AnthropicRateLimitError as exc:
            raise RateLimitError() from exc
        except APIStatusError as exc:
            if exc.status_code == 401:
                raise AuthError("Invalid Anthropic API key") from exc
            if exc.status_code == 429:
                raise RateLimitError() from exc
            raise NetworkError(f"HTTP {exc.status_code}: {exc}") from exc
        except APIConnectionError as exc:
            raise NetworkError(str(exc)) from exc

    @staticmethod
    def _build_messages(messages, user_text, images) -> list[dict]:
        if messages is not None:
            out: list[dict] = []
            for m in messages:
                if m.image_png is not None and m.role == "user":
                    b64 = base64.b64encode(m.image_png).decode()
                    out.append({"role": "user", "content": [
                        {"type": "text", "text": m.text},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                    ]})
                else:
                    out.append({"role": m.role, "content": m.text})
            return out
        if not images:
            return [{"role": "user", "content": user_text}]
        parts: list[dict] = [{"type": "text", "text": user_text}]
        for png in images:
            b64 = base64.b64encode(png).decode()
            parts.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}})
        return [{"role": "user", "content": parts}]
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_anthropic_provider.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/llm/providers/anthropic_provider.py tests/test_anthropic_provider.py
git commit -m "feat(anthropic): implement provider via anthropic SDK"
```

---

### Task 10: Implement `GeminiProvider`

**Files:**
- Modify: `src/spiresight/llm/providers/gemini_provider.py` (full rewrite)
- Test: `tests/test_gemini_provider.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_gemini_provider.py`:

```python
from __future__ import annotations

import pytest

from spiresight.config.schema import ProviderConfig
from spiresight.core.messages import Message
from spiresight.llm.errors import AuthError, MissingAPIKey
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.gemini_provider import GeminiProvider


class FakeUsageMeta:
    def __init__(self, prompt, candidates):
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates


class FakeChunk:
    def __init__(self, text="", usage=None):
        self.text = text
        self.usage_metadata = usage


class FakeModelsAPI:
    def __init__(self, *, stream_chunks=None, stream_raises=None,
                 list_data=None, list_raises=None):
        self._chunks = stream_chunks or []
        self._stream_raises = stream_raises
        self._list_data = list_data or []
        self._list_raises = list_raises
        self.stream_kwargs: dict | None = None
    def generate_content_stream(self, **kwargs):
        self.stream_kwargs = kwargs
        if self._stream_raises is not None:
            raise self._stream_raises
        return iter(self._chunks)
    def list(self):
        if self._list_raises:
            raise self._list_raises
        return iter(self._list_data)


class FakeClient:
    def __init__(self, *, api_key, http_options=None):
        self.api_key = api_key
        self.http_options = http_options
        self.models = None


def _make(monkeypatch, **api_kwargs):
    holder = {}
    def factory(api_key=None, http_options=None):
        c = FakeClient(api_key=api_key, http_options=http_options)
        c.models = FakeModelsAPI(**api_kwargs)
        holder["client"] = c
        return c
    monkeypatch.setattr("spiresight.llm.providers.gemini_provider.genai", type("G", (), {"Client": factory}))
    p = GeminiProvider(ProviderConfig(api_key="g-key"), ProviderOptions())
    return p, holder


def test_stream_collects_text_and_usage(monkeypatch):
    chunks = [
        FakeChunk(text="A"),
        FakeChunk(text="B"),
        FakeChunk(usage=FakeUsageMeta(prompt=7, candidates=2)),
    ]
    p, _ = _make(monkeypatch, stream_chunks=chunks)
    out = list(p.stream(model="gemini-2.5-pro", system="SYS", user_text="hi"))
    text = "".join(c.text_delta for c in out)
    assert text == "AB"
    usage = next(c for c in out if c.usage is not None)
    assert usage.usage.input_tokens == 7
    assert usage.usage.output_tokens == 2


def test_assistant_role_maps_to_model(monkeypatch):
    p, holder = _make(monkeypatch, stream_chunks=[])
    list(p.stream(
        model="gemini-2.5-flash", system="s",
        messages=[
            Message(role="user", text="hi", image_png=None),
            Message(role="assistant", text="hello", image_png=None),
        ],
    ))
    contents = holder["client"].models.stream_kwargs["contents"]
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"


def test_json_mode_sets_response_mime_type(monkeypatch):
    p, holder = _make(monkeypatch, stream_chunks=[])
    list(p.stream(model="gemini-2.5-flash", system="s", user_text="hi", json_mode=True))
    cfg = holder["client"].models.stream_kwargs["config"]
    assert cfg.response_mime_type == "application/json"


def test_system_instruction_set_in_config(monkeypatch):
    p, holder = _make(monkeypatch, stream_chunks=[])
    list(p.stream(model="gemini-2.5-flash", system="MY-SYS", user_text="hi"))
    cfg = holder["client"].models.stream_kwargs["config"]
    assert cfg.system_instruction == "MY-SYS"


def test_missing_api_key_raises():
    p = GeminiProvider(ProviderConfig(api_key=""), ProviderOptions())
    with pytest.raises(MissingAPIKey):
        list(p.stream(model="gemini-2.5-pro", system="s", user_text="hi"))


def test_fetch_remote_models_filters_embed_and_aqa(monkeypatch):
    class FakeM:
        def __init__(self, name, display=None, ctx=0):
            self.name = name
            self.display_name = display
            self.input_token_limit = ctx
    listed = [
        FakeM("models/gemini-2.5-pro", display="Gemini 2.5 Pro", ctx=2_000_000),
        FakeM("models/text-embedding-004"),
        FakeM("models/aqa"),
    ]
    p, _ = _make(monkeypatch, list_data=listed)
    models = p.fetch_remote_models()
    ids = {m.id for m in models}
    assert "gemini-2.5-pro" in ids
    assert "text-embedding-004" not in ids
    assert "aqa" not in ids
```

- [ ] **Step 2: Run to verify FAIL**

```bash
.venv/bin/pytest tests/test_gemini_provider.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement the provider**

Replace `src/spiresight/llm/providers/gemini_provider.py` with:

```python
"""Google Gemini streaming provider via the google-genai SDK."""
from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Final

from google import genai
from google.genai import types as genai_types
from google.genai import errors as genai_errors

from spiresight.config.schema import ProviderConfig
from spiresight.core.usage import TokenUsage
from spiresight.llm.capabilities import Capability
from spiresight.llm.capability_table import infer_capabilities
from spiresight.llm.errors import (
    AuthError, MissingAPIKey, NetworkError, RateLimitError, RequestTimeoutError,
)
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import ProviderOptions, StreamChunk


_BUILTIN_DEFAULTS: Final[list[ModelInfo]] = [
    ModelInfo("gemini-2.5-pro", "Gemini 2.5 Pro",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING}),
              context_window=2_000_000),
    ModelInfo("gemini-2.5-flash", "Gemini 2.5 Flash",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING}),
              context_window=1_000_000),
    ModelInfo("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE}),
              context_window=1_000_000),
]


class GeminiProvider:
    name = "gemini"
    _BUILTIN_DEFAULTS: list[ModelInfo] = _BUILTIN_DEFAULTS

    def __init__(self, config: ProviderConfig, options: ProviderOptions) -> None:
        self._config = config
        self._options = options
        http_options = (
            genai_types.HttpOptions(base_url=config.base_url) if config.base_url else None
        )
        self._client = genai.Client(
            api_key=config.api_key or "missing",
            http_options=http_options,
        )

    def list_models(self) -> list[ModelInfo]:
        if self._config.cached_models:
            return [ModelInfo.from_dict(m) for m in self._config.cached_models]
        return list(self._BUILTIN_DEFAULTS)

    def fetch_remote_models(self) -> list[ModelInfo]:
        try:
            paged = self._client.models.list()
        except genai_errors.APIError as exc:
            raise self._wrap(exc) from exc

        out: list[ModelInfo] = []
        for m in paged:
            raw = getattr(m, "name", "")
            mid = raw.removeprefix("models/") if raw else raw
            if not mid:
                continue
            if "embed" in mid or "aqa" in mid:
                continue
            caps, _ = infer_capabilities(mid)
            out.append(ModelInfo(
                id=mid,
                display_name=getattr(m, "display_name", None) or mid,
                capabilities=caps,
                context_window=int(getattr(m, "input_token_limit", 0) or 0),
            ))
        return out

    def stream(
        self,
        *,
        model: str,
        system: str,
        user_text: str = "",
        images: list[bytes] = (),  # type: ignore[assignment]
        cancel_event: threading.Event | None = None,
        json_mode: bool = False,
        messages: list | None = None,
    ) -> Iterator[StreamChunk]:
        if not self._config.api_key:
            raise MissingAPIKey(self.name)
        cancel_event = cancel_event or threading.Event()

        contents = self._build_contents(messages, user_text, images)
        cfg = genai_types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json" if json_mode else None,
        )

        try:
            stream = self._client.models.generate_content_stream(
                model=model, contents=contents, config=cfg,
            )
            for chunk in stream:
                if cancel_event.is_set():
                    return
                text = chunk.text or ""
                usage = chunk.usage_metadata
                usage_obj = None
                if usage is not None and (usage.prompt_token_count or usage.candidates_token_count):
                    usage_obj = TokenUsage(
                        input_tokens=int(usage.prompt_token_count or 0),
                        output_tokens=int(usage.candidates_token_count or 0),
                    )
                if text or usage_obj is not None:
                    yield StreamChunk(text_delta=text, finish_reason=None, usage=usage_obj)
        except genai_errors.APIError as exc:
            raise self._wrap(exc) from exc

    @staticmethod
    def _wrap(exc: "genai_errors.APIError") -> Exception:
        status = getattr(exc, "code", None)
        if status in (401, 403):
            return AuthError(str(exc))
        if status == 429:
            return RateLimitError()
        if "DEADLINE_EXCEEDED" in str(exc):
            return RequestTimeoutError(str(exc))
        return NetworkError(str(exc))

    @staticmethod
    def _build_contents(messages, user_text, images) -> list:
        if messages is not None:
            out: list[dict] = []
            for m in messages:
                role = "model" if m.role == "assistant" else "user"
                parts: list = [{"text": m.text}]
                if m.image_png is not None and m.role == "user":
                    parts.append(genai_types.Part.from_bytes(data=m.image_png, mime_type="image/png"))
                out.append({"role": role, "parts": parts})
            return out
        parts: list = [{"text": user_text}]
        for png in images:
            parts.append(genai_types.Part.from_bytes(data=png, mime_type="image/png"))
        return [{"role": "user", "parts": parts}]
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_gemini_provider.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/llm/providers/gemini_provider.py tests/test_gemini_provider.py
git commit -m "feat(gemini): implement provider via google-genai SDK"
```

---

### Task 11: Register `openai_compat` in the registry

**Files:**
- Modify: `src/spiresight/llm/registry.py`
- Test: `tests/test_registry.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry.py`:

```python
def test_registry_names_includes_openai_compat():
    from spiresight.llm import registry
    assert "openai_compat" in registry.names()


def test_make_provider_openai_compat(monkeypatch):
    from spiresight.config.schema import ProviderConfig
    from spiresight.llm.provider import ProviderOptions
    from spiresight.llm import registry
    monkeypatch.setattr(
        "spiresight.llm.providers.openai_provider.OpenAI",
        lambda **kw: object(),
    )
    p = registry.make_provider(
        "openai_compat",
        ProviderConfig(api_key="k", base_url="http://x/v1"),
        ProviderOptions(),
    )
    assert p.name == "openai_compat"
```

- [ ] **Step 2: Run to verify FAIL**

```bash
.venv/bin/pytest tests/test_registry.py -v
```

Expected: FAIL — `KeyError: openai_compat`.

- [ ] **Step 3: Update the registry**

Edit `src/spiresight/llm/registry.py`:

```python
from __future__ import annotations

from spiresight.config.schema import ProviderConfig
from spiresight.llm.provider import LLMProvider, ProviderOptions
from spiresight.llm.providers.openai_provider import OpenAIProvider
from spiresight.llm.providers.openai_compat_provider import OpenAICompatProvider
from spiresight.llm.providers.anthropic_provider import AnthropicProvider
from spiresight.llm.providers.gemini_provider import GeminiProvider


def names() -> list[str]:
    return ["openai", "openai_compat", "anthropic", "gemini"]


def make_provider(
    name: str,
    config: ProviderConfig,
    options: ProviderOptions | None = None,
) -> LLMProvider:
    options = options or ProviderOptions()
    if name == "openai":        return OpenAIProvider(config, options)
    if name == "openai_compat": return OpenAICompatProvider(config, options)
    if name == "anthropic":     return AnthropicProvider(config, options)
    if name == "gemini":        return GeminiProvider(config, options)
    raise KeyError(f"Unknown provider: {name}")


def get(name: str, config: ProviderConfig) -> LLMProvider:
    return make_provider(name, config)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_registry.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/llm/registry.py tests/test_registry.py
git commit -m "feat(registry): register openai_compat provider"
```

---

### Task 12: `ModelRefreshWorker`

**Files:**
- Create: `src/spiresight/ui/workers/model_refresh_worker.py`
- Test: `tests/test_model_refresh_worker.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_model_refresh_worker.py`:

```python
from unittest.mock import MagicMock

from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import AuthError
from spiresight.llm.models import ModelInfo
from spiresight.ui.workers.model_refresh_worker import ModelRefreshWorker


def test_succeeded_signal_emits_models(qtbot):
    fake_provider = MagicMock()
    fake_models = [ModelInfo("a", "A", frozenset({Capability.VISION}), 1_000)]
    fake_provider.fetch_remote_models.return_value = fake_models

    w = ModelRefreshWorker("openai", fake_provider)
    with qtbot.waitSignal(w.succeeded, timeout=2000) as blocker:
        w.run()
    name, models = blocker.args
    assert name == "openai"
    assert models == fake_models


def test_failed_signal_emits_exception(qtbot):
    fake_provider = MagicMock()
    err = AuthError("invalid key")
    fake_provider.fetch_remote_models.side_effect = err

    w = ModelRefreshWorker("anthropic", fake_provider)
    with qtbot.waitSignal(w.failed, timeout=2000) as blocker:
        w.run()
    name, exc = blocker.args
    assert name == "anthropic"
    assert exc is err
```

- [ ] **Step 2: Run to verify FAIL**

```bash
.venv/bin/pytest tests/test_model_refresh_worker.py -v
```

Expected: FAIL on import.

- [ ] **Step 3: Implement the worker**

Create `src/spiresight/ui/workers/model_refresh_worker.py`:

```python
"""Fetches a provider's remote model list off the UI thread."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from spiresight.llm.provider import LLMProvider


class ModelRefreshWorker(QThread):
    """Fetches `provider.fetch_remote_models()` and emits the result.

    Always emits exactly one of `succeeded` or `failed`. UI consumers
    should also connect to `finished` for "set busy back to false".
    """

    succeeded = Signal(str, list)      # provider_name, list[ModelInfo]
    failed = Signal(str, object)        # provider_name, Exception

    def __init__(self, provider_name: str, provider: LLMProvider, parent=None) -> None:
        super().__init__(parent)
        self._name = provider_name
        self._provider = provider

    def run(self) -> None:
        try:
            models = self._provider.fetch_remote_models()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self._name, exc)
            return
        self.succeeded.emit(self._name, models)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_model_refresh_worker.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/workers/model_refresh_worker.py tests/test_model_refresh_worker.py
git commit -m "feat(workers): add ModelRefreshWorker"
```

---

### Task 13: `ProviderPane` widget

**Files:**
- Create: `src/spiresight/ui/widgets/provider_pane.py`
- Test: `tests/test_provider_pane.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_provider_pane.py`:

```python
from unittest.mock import MagicMock

from spiresight.config.schema import ProviderConfig
from spiresight.ui.widgets.provider_pane import ProviderPane


def test_pane_returns_api_key_and_base_url(qtbot):
    cb = MagicMock()
    pane = ProviderPane(
        "openai_compat",
        ProviderConfig(api_key="k1", base_url="http://x/v1"),
        require_base_url=True,
        base_url_presets={"X": "http://x/v1"},
        on_refresh=cb,
    )
    qtbot.addWidget(pane)
    assert pane.api_key_value() == "k1"
    assert pane.base_url_value() == "http://x/v1"


def test_pane_hides_base_url_when_not_required(qtbot):
    cb = MagicMock()
    pane = ProviderPane(
        "openai",
        ProviderConfig(api_key="k"),
        require_base_url=False,
        base_url_presets=None,
        on_refresh=cb,
    )
    qtbot.addWidget(pane)
    pane.show()
    assert pane._base_url_edit.isVisible() is False


def test_pane_preset_fills_base_url(qtbot):
    cb = MagicMock()
    pane = ProviderPane(
        "openai_compat",
        ProviderConfig(api_key="k"),
        require_base_url=True,
        base_url_presets={"OpenRouter": "https://openrouter.ai/api/v1"},
        on_refresh=cb,
    )
    qtbot.addWidget(pane)
    # Select preset via index 0
    pane._preset_combo.setCurrentIndex(0)
    pane._preset_combo.activated.emit(0)
    assert pane.base_url_value() == "https://openrouter.ai/api/v1"


def test_pane_refresh_button_invokes_callback(qtbot):
    cb = MagicMock()
    pane = ProviderPane(
        "openai",
        ProviderConfig(api_key="k"),
        require_base_url=False,
        base_url_presets=None,
        on_refresh=cb,
    )
    qtbot.addWidget(pane)
    pane._refresh_btn.click()
    cb.assert_called_once_with("openai")


def test_pane_set_busy_disables_refresh(qtbot):
    cb = MagicMock()
    pane = ProviderPane(
        "openai",
        ProviderConfig(api_key="k"),
        require_base_url=False,
        base_url_presets=None,
        on_refresh=cb,
    )
    qtbot.addWidget(pane)
    pane.set_busy(True)
    assert pane._refresh_btn.isEnabled() is False
    pane.set_busy(False)
    assert pane._refresh_btn.isEnabled() is True


def test_pane_set_model_count_updates_label(qtbot):
    cb = MagicMock()
    pane = ProviderPane(
        "openai",
        ProviderConfig(api_key="k"),
        require_base_url=False,
        base_url_presets=None,
        on_refresh=cb,
    )
    qtbot.addWidget(pane)
    pane.set_model_count(7)
    assert "7" in pane._count_label.text()
```

- [ ] **Step 2: Run to verify FAIL**

```bash
.venv/bin/pytest tests/test_provider_pane.py -v
```

Expected: FAIL on import.

- [ ] **Step 3: Implement the widget**

Create `src/spiresight/ui/widgets/provider_pane.py`:

```python
"""Per-provider configuration pane: api_key + (optional) base_url + Refresh."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from spiresight.config.schema import ProviderConfig


class ProviderPane(QWidget):
    """One provider's config: api_key + (optional base_url) + refresh + model count."""

    def __init__(
        self,
        provider_name: str,
        config: ProviderConfig,
        *,
        require_base_url: bool,
        base_url_presets: dict[str, str] | None,
        on_refresh: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider_name = provider_name
        self._on_refresh = on_refresh
        self._show_base_url = require_base_url or bool(config.base_url) or bool(base_url_presets)

        outer = QVBoxLayout(self)
        form = QFormLayout()

        self._api_key_edit = QLineEdit(config.api_key)
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText(f"{provider_name} API key")
        form.addRow("API key", self._api_key_edit)

        self._preset_combo = QComboBox()
        self._base_url_edit = QLineEdit(config.base_url or "")
        self._base_url_edit.setPlaceholderText("https://api.example.com/v1")
        if base_url_presets:
            self._preset_combo.addItem("Custom…", userData="")
            for label, url in base_url_presets.items():
                self._preset_combo.addItem(label, userData=url)
            self._preset_combo.activated.connect(self._on_preset_selected)
            form.addRow("Preset", self._preset_combo)
        form.addRow("Base URL", self._base_url_edit)
        self._preset_combo.setVisible(self._show_base_url and bool(base_url_presets))
        self._base_url_edit.setVisible(self._show_base_url)
        # Hide the form-row labels for hidden controls by hiding their buddies.
        for control in (self._preset_combo, self._base_url_edit):
            label = form.labelForField(control)
            if label is not None:
                label.setVisible(control.isVisible())

        bottom = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh models")
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        self._count_label = QLabel(self._count_text(len(config.cached_models)))
        bottom.addWidget(self._refresh_btn)
        bottom.addWidget(self._count_label, stretch=1)

        outer.addLayout(form)
        outer.addLayout(bottom)
        outer.addStretch(1)

    # ---- public API ----

    def api_key_value(self) -> str:
        return self._api_key_edit.text().strip()

    def base_url_value(self) -> str:
        return self._base_url_edit.text().strip()

    def set_busy(self, busy: bool) -> None:
        self._refresh_btn.setEnabled(not busy)
        self._refresh_btn.setText("Refreshing…" if busy else "Refresh models")

    def set_model_count(self, n: int) -> None:
        self._count_label.setText(self._count_text(n))

    # ---- internal ----

    @staticmethod
    def _count_text(n: int) -> str:
        if n == 0:
            return "using built-in defaults"
        return f"{n} models cached"

    def _on_preset_selected(self, index: int) -> None:
        url = self._preset_combo.itemData(index)
        if url:
            self._base_url_edit.setText(url)

    def _on_refresh_clicked(self) -> None:
        self._on_refresh(self._provider_name)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_provider_pane.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/widgets/provider_pane.py tests/test_provider_pane.py
git commit -m "feat(ui): add ProviderPane widget"
```

---

### Task 14: Rewrite `SettingsDialog` around `ProviderPane`

**Files:**
- Modify: `src/spiresight/ui/windows/settings_dialog.py` (rewrite)
- Test: `tests/test_settings_dialog_providers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_dialog_providers.py`:

```python
from unittest.mock import MagicMock

from spiresight.config.schema import AppConfig, ModelInfoDict, ProviderConfig
from spiresight.config.store import ConfigStore
from spiresight.llm.capabilities import Capability
from spiresight.llm.models import ModelInfo


def _config(tmp_path):
    return AppConfig(
        providers={
            "openai": ProviderConfig(api_key=""),
            "openai_compat": ProviderConfig(api_key="", base_url=""),
            "anthropic": ProviderConfig(api_key=""),
            "gemini": ProviderConfig(api_key=""),
        }
    )


def test_dialog_creates_pane_per_provider(qtbot, tmp_path):
    from spiresight.ui.windows.settings_dialog import SettingsDialog
    cfg = _config(tmp_path)
    store = MagicMock(spec=ConfigStore)
    dlg = SettingsDialog(cfg, store)
    qtbot.addWidget(dlg)
    assert set(dlg._panes.keys()) == {"openai", "openai_compat", "anthropic", "gemini"}


def test_refresh_succeeded_persists_models(qtbot, tmp_path, monkeypatch):
    from spiresight.ui.windows.settings_dialog import SettingsDialog
    cfg = _config(tmp_path)
    store = MagicMock(spec=ConfigStore)
    dlg = SettingsDialog(cfg, store)
    qtbot.addWidget(dlg)
    fake_models = [
        ModelInfo("m1", "M1", frozenset({Capability.VISION, Capability.JSON_MODE}), 100),
    ]
    dlg._on_refresh_succeeded("openai", fake_models)
    cached = cfg.providers["openai"].cached_models
    assert len(cached) == 1
    assert cached[0].id == "m1"
    assert "json_mode" in cached[0].capabilities
    store.save.assert_called_once_with(cfg)


def test_refresh_failed_emits_signal(qtbot, tmp_path):
    from spiresight.ui.windows.settings_dialog import SettingsDialog
    cfg = _config(tmp_path)
    store = MagicMock(spec=ConfigStore)
    dlg = SettingsDialog(cfg, store)
    qtbot.addWidget(dlg)
    with qtbot.waitSignal(dlg.models_refresh_failed, timeout=2000) as blocker:
        dlg._on_refresh_failed("openai", RuntimeError("bad"))
    assert blocker.args[0] == "openai"


def test_apply_writes_api_keys_and_base_urls(qtbot, tmp_path):
    from spiresight.ui.windows.settings_dialog import SettingsDialog
    cfg = _config(tmp_path)
    store = MagicMock(spec=ConfigStore)
    dlg = SettingsDialog(cfg, store)
    qtbot.addWidget(dlg)
    dlg._panes["openai"]._api_key_edit.setText("sk-new")
    dlg._panes["openai_compat"]._api_key_edit.setText("relay-key")
    dlg._panes["openai_compat"]._base_url_edit.setText("http://localhost:11434/v1")
    dlg._apply_and_accept()
    assert cfg.providers["openai"].api_key == "sk-new"
    assert cfg.providers["openai_compat"].api_key == "relay-key"
    assert cfg.providers["openai_compat"].base_url == "http://localhost:11434/v1"
```

- [ ] **Step 2: Run to verify FAIL**

```bash
.venv/bin/pytest tests/test_settings_dialog_providers.py -v
```

Expected: FAIL — current SettingsDialog has no `_panes`.

- [ ] **Step 3: Rewrite the dialog**

Replace `src/spiresight/ui/windows/settings_dialog.py` with:

```python
# src/spiresight/ui/windows/settings_dialog.py
"""Settings dialog: per-provider config + general preferences."""
from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QLineEdit, QMessageBox, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.config.store import ConfigStore
from spiresight.llm import registry
from spiresight.llm.errors import MissingAPIKey, MissingBaseURL
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.openai_compat_provider import RELAY_PRESETS
from spiresight.ui.widgets.provider_pane import ProviderPane
from spiresight.ui.workers.model_refresh_worker import ModelRefreshWorker

_log = logging.getLogger(__name__)


def _presets_for(name: str) -> dict[str, str] | None:
    if name == "openai_compat":
        return RELAY_PRESETS
    return None


def _require_base_url(name: str) -> bool:
    return name == "openai_compat"


class SettingsDialog(QDialog):
    models_refreshed = Signal(str)              # provider_name
    models_refresh_failed = Signal(str, object) # provider_name, Exception

    def __init__(self, config: AppConfig, store: ConfigStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SpireSight — Settings")
        self._config = config
        self._store = store
        self._panes: dict[str, ProviderPane] = {}
        self._workers: dict[str, ModelRefreshWorker] = {}

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_providers_tab(), "Providers")
        tabs.addTab(self._build_general_tab(), "General")
        root.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._apply_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ---- Providers tab ----

    def _build_providers_tab(self) -> QWidget:
        nested = QTabWidget()
        for name in registry.names():
            cfg = self._config.providers.get(name, ProviderConfig())
            pane = ProviderPane(
                name, cfg,
                require_base_url=_require_base_url(name),
                base_url_presets=_presets_for(name),
                on_refresh=self.refresh_provider,
            )
            self._panes[name] = pane
            nested.addTab(pane, name)
        return nested

    def refresh_provider(self, name: str) -> None:
        pane = self._panes[name]
        pane.set_busy(True)
        cur = self._config.providers.get(name, ProviderConfig())
        cfg_now = ProviderConfig(
            api_key=pane.api_key_value(),
            base_url=pane.base_url_value() or None,
            cached_models=cur.cached_models,
        )
        options = ProviderOptions(request_timeout_seconds=self._config.request_timeout_seconds)
        try:
            provider = registry.make_provider(name, cfg_now, options)
        except (MissingBaseURL, MissingAPIKey) as exc:
            QMessageBox.warning(self, "Refresh", str(exc))
            pane.set_busy(False)
            return

        worker = ModelRefreshWorker(name, provider, parent=self)
        worker.succeeded.connect(self._on_refresh_succeeded)
        worker.failed.connect(self._on_refresh_failed)
        worker.finished.connect(lambda n=name: self._panes[n].set_busy(False))
        worker.start()
        self._workers[name] = worker

    def _on_refresh_succeeded(self, name: str, models: list) -> None:
        cur = self._config.providers.get(name, ProviderConfig())
        new_cfg = ProviderConfig(
            api_key=cur.api_key,
            base_url=cur.base_url,
            cached_models=[m.to_dict() for m in models],
        )
        self._config.providers[name] = new_cfg
        self._store.save(self._config)
        self._panes[name].set_model_count(len(models))
        self.models_refreshed.emit(name)

    def _on_refresh_failed(self, name: str, exc: Exception) -> None:
        QMessageBox.warning(self, "Refresh failed", f"{name}: {exc}")
        self.models_refresh_failed.emit(name, exc)

    # ---- General tab (unchanged from spec #1) ----

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self._lang = QComboBox()
        self._lang.addItem("English", userData="en")
        self._lang.addItem("中文", userData="zh")
        idx = self._lang.findData(self._config.language)
        self._lang.setCurrentIndex(max(0, idx))

        self._hotkey = QLineEdit(self._config.hotkey)
        self._hotkey.setPlaceholderText("<ctrl>+<shift>+s")

        self._on_top = QCheckBox()
        self._on_top.setChecked(self._config.always_on_top)

        self._timeout = QSpinBox()
        self._timeout.setRange(30, 600)
        self._timeout.setSingleStep(30)
        self._timeout.setValue(self._config.request_timeout_seconds)

        form.addRow("Language", self._lang)
        form.addRow("Hotkey", self._hotkey)
        form.addRow("Always on top", self._on_top)
        form.addRow("Request timeout (seconds)", self._timeout)
        return page

    # ---- accept / persistence ----

    def _apply_and_accept(self) -> None:
        for name, pane in self._panes.items():
            cur = self._config.providers.get(name, ProviderConfig())
            self._config.providers[name] = ProviderConfig(
                api_key=pane.api_key_value(),
                base_url=pane.base_url_value() or None,
                cached_models=cur.cached_models,
            )
        self._config.language = self._lang.currentData()
        self._config.hotkey = self._hotkey.text().strip() or self._config.hotkey
        self._config.always_on_top = self._on_top.isChecked()
        self._config.request_timeout_seconds = self._timeout.value()
        self.accept()
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_settings_dialog_providers.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/windows/settings_dialog.py tests/test_settings_dialog_providers.py
git commit -m "refactor(ui): rewrite SettingsDialog around ProviderPane"
```

---

### Task 15: Wire `models_refreshed` / `models_refresh_failed` in `MainWindow`

**Files:**
- Modify: `src/spiresight/ui/windows/main_window.py`

- [ ] **Step 1: Find the existing Settings invocation**

```bash
grep -n "SettingsDialog" src/spiresight/ui/windows/main_window.py
```

Note the call site that constructs and exec()s the dialog.

- [ ] **Step 2: Update MainWindow to receive `ConfigStore` if it doesn't already**

Check whether `MainWindow.__init__` accepts the `ConfigStore`. Per `spiresight/__main__.py` it should — confirm with:

```bash
grep -n "MainWindow(" src/spiresight/__main__.py
```

If `store` is already constructed and passed, good. If not, this is a one-line addition to the entrypoint; otherwise leave as-is.

- [ ] **Step 3: Update the dialog construction and connect signals**

Locate the existing `SettingsDialog(self._config, parent=self)` or similar. Replace with:

```python
dialog = SettingsDialog(self._config, self._store, parent=self)
dialog.models_refreshed.connect(self._on_provider_models_refreshed)
dialog.models_refresh_failed.connect(self._on_provider_models_refresh_failed)
dialog.exec()
```

Add the two slot methods on `MainWindow`:

```python
def _on_provider_models_refreshed(self, name: str) -> None:
    self._logs_tab.log(f"Refreshed {name} models: {len(self._config.providers[name].cached_models)} cached")
    if name == self._config.active_provider:
        self._provider_picker.reload(self._config)   # if the picker has this; otherwise rebuild via the existing reload path

def _on_provider_models_refresh_failed(self, name: str, exc: Exception) -> None:
    self._logs_tab.log(f"Refresh {name} failed: {exc}")
```

If `ProviderPicker` has no `reload(config)`, add one as a small adjacent change: `reload(cfg)` repopulates its model combobox from `registry.make_provider(cfg.active_provider, cfg.providers[cfg.active_provider]).list_models()`.

- [ ] **Step 4: Smoke test by launching the app**

```bash
.venv/bin/python -m spiresight
```

Manually verify Settings opens, Refresh on the OpenAI tab triggers a network call, and the LogsTab gets a confirmation line.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/ui/windows/main_window.py
git commit -m "feat(ui): wire SettingsDialog refresh signals to LogsTab and ProviderPicker"
```

---

### Task 16: Drop obsolete provider-stub tests

**Files:**
- Modify: `tests/test_provider_stubs.py`

- [ ] **Step 1: Inspect what the stub tests assert**

```bash
cat tests/test_provider_stubs.py
```

These likely assert that `AnthropicProvider.stream(...)` raises `NotImplementedError` or that `list_models()` returns `[]`. Those expectations are no longer correct.

- [ ] **Step 2: Replace with the new contract**

Replace the file with:

```python
"""Smoke tests that all three stub providers expose the real ProviderProtocol surface.

The behavior tests live in test_anthropic_provider.py / test_gemini_provider.py /
test_openai_provider.py.
"""
from __future__ import annotations

from spiresight.config.schema import ProviderConfig
from spiresight.llm.provider import LLMProvider, ProviderOptions
from spiresight.llm.providers.anthropic_provider import AnthropicProvider
from spiresight.llm.providers.gemini_provider import GeminiProvider


def test_anthropic_satisfies_protocol(monkeypatch):
    monkeypatch.setattr(
        "spiresight.llm.providers.anthropic_provider.Anthropic",
        lambda **kw: object(),
    )
    p = AnthropicProvider(ProviderConfig(api_key="k"), ProviderOptions())
    assert isinstance(p, LLMProvider)
    assert hasattr(p, "fetch_remote_models")


def test_gemini_satisfies_protocol(monkeypatch):
    class FakeGenAI:
        def Client(self, **kwargs):
            return object()
    monkeypatch.setattr("spiresight.llm.providers.gemini_provider.genai", FakeGenAI())
    p = GeminiProvider(ProviderConfig(api_key="k"), ProviderOptions())
    assert isinstance(p, LLMProvider)
    assert hasattr(p, "fetch_remote_models")


def test_anthropic_has_builtin_defaults(monkeypatch):
    monkeypatch.setattr(
        "spiresight.llm.providers.anthropic_provider.Anthropic",
        lambda **kw: object(),
    )
    p = AnthropicProvider(ProviderConfig(api_key="k"), ProviderOptions())
    models = p.list_models()
    assert len(models) > 0
    assert any("claude" in m.id for m in models)


def test_gemini_has_builtin_defaults(monkeypatch):
    class FakeGenAI:
        def Client(self, **kwargs):
            return object()
    monkeypatch.setattr("spiresight.llm.providers.gemini_provider.genai", FakeGenAI())
    p = GeminiProvider(ProviderConfig(api_key="k"), ProviderOptions())
    models = p.list_models()
    assert len(models) > 0
    assert any("gemini" in m.id for m in models)
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/test_provider_stubs.py -v
```

Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/test_provider_stubs.py
git commit -m "test: rewrite provider stub tests for live Anthropic / Gemini impls"
```

---

### Task 17: Capability check propagation in runner

**Files:**
- Modify: `tests/test_inference_runner.py` (extend) — runner code itself unchanged.

The runner already calls `model.has(Capability.X)` via `MissingCapabilityError`. With the new capability table, refreshed models carry plausible flag sets. Two new assertions verify the path end-to-end.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inference_runner.py`:

```python
def test_inspect_rejects_model_without_json_mode(monkeypatch):
    """A model whose KNOWN_MODEL_CAPS entry lacks JSON_MODE must raise."""
    from spiresight.config.schema import AppConfig, ModelInfoDict, ProviderConfig
    from spiresight.core.runner import InferenceRunner
    from spiresight.llm.errors import MissingCapabilityError
    from spiresight.llm.models import ModelInfo
    from spiresight.llm.capabilities import Capability
    from unittest.mock import MagicMock
    import threading

    cfg = AppConfig(
        active_provider="openai_compat",
        active_model="llama-3.3-70b-versatile",
        request_timeout_seconds=60,
    )
    cfg.providers = {"openai_compat": ProviderConfig(
        api_key="k", base_url="http://x/v1",
        cached_models=[ModelInfoDict(
            id="llama-3.3-70b-versatile", display_name="L",
            capabilities=["tool_use"], context_window=8192,
        )],
    )}

    fake_provider = MagicMock()
    fake_provider.name = "openai_compat"
    fake_provider.list_models.return_value = [
        ModelInfo("llama-3.3-70b-versatile", "L", frozenset({Capability.TOOL_USE}), 8192)
    ]

    loader = MagicMock()
    loader.get_system_prompt.return_value = MagicMock(content="INSPECT-SYS")

    runner = InferenceRunner(
        config=cfg, prompt_loader=loader,
        provider_factory=lambda *a, **kw: fake_provider,
        screen_capture=MagicMock(), run_state_store=None,
    )
    with __import__("pytest").raises(MissingCapabilityError):
        runner.inspect(images=[b"\x89PNG"], cancel_event=threading.Event())
```

- [ ] **Step 2: Run to verify FAIL or PASS**

```bash
.venv/bin/pytest tests/test_inference_runner.py::test_inspect_rejects_model_without_json_mode -v
```

If the runner already enforces this (it does, per spec #1 §5 capability check), this should PASS immediately. If it fails because the snapshot path doesn't run capability checks, add the check inside `inspect()` (it's already present per the spec #1 plan Task 6 — verify).

- [ ] **Step 3: Commit**

```bash
git add tests/test_inference_runner.py
git commit -m "test: assert runner inspect() rejects models lacking JSON_MODE"
```

---

### Task 18: Full-suite sweep + manual verification

- [ ] **Step 1: Run all tests**

```bash
.venv/bin/pytest -q
```

Expected: all passing. Investigate any regression — most likely candidates are tests that constructed the old `OpenAIProvider(config)` with a single arg or used `respx` against httpx. Update each to pass `ProviderOptions` and to monkeypatch the SDK symbol.

- [ ] **Step 2: Run mypy**

```bash
.venv/bin/mypy src/spiresight
```

Expected: clean. Likely issues:
- `ModelInfo.from_dict` returns Self but mypy might not infer; add an explicit type annotation if needed.
- `OpenAICompatProvider._DEFAULT_BASE = None` overrides `str | None` — annotate explicitly.

- [ ] **Step 3: Run ruff**

```bash
.venv/bin/ruff check src/ tests/
```

Expected: clean.

- [ ] **Step 4: Manual verification — OpenRouter**

Launch app. Settings → Providers → OpenAI-Compat. Select OpenRouter preset → paste OpenRouter key → Refresh. Model count updates to a non-zero number; LogsTab logs the refresh. OK. Switch ProviderPicker to `openai_compat`; the model dropdown shows OpenRouter models. Run a Quick Action against one (e.g. `meta-llama/llama-3.3-70b`). Confirm streaming text in the Chat tab and a `[sent]` → `[ok]` LogRow.

- [ ] **Step 5: Manual verification — Anthropic**

Settings → Providers → Anthropic → paste real Anthropic key → Refresh → switch to anthropic → Quick Action with screenshot. Verify vision works. Expand the LogRow: `system` field is non-empty; the first message's role is `user`, not `system`.

- [ ] **Step 6: Manual verification — Gemini**

Settings → Providers → Gemini → real Gemini key → Refresh → switch to gemini → run Inspect. Confirm JSON output parses into `RunState`.

- [ ] **Step 7: Manual verification — error paths**

Settings → OpenAI-Compat → set base_url to `http://localhost:99999/v1` → Refresh. Expect QMessageBox + LogsTab error line. `cached_models` for openai_compat unchanged. Cancel the dialog; reopen — values you didn't refresh are unchanged.

- [ ] **Step 8: Manual verification — packaging smoke**

If PyInstaller is configured for this project:

```bash
.venv/bin/python -m PyInstaller packaging/spiresight.spec --noconfirm
```

Run the produced binary; open Settings; ensure no missing-module errors related to `openai`, `anthropic`, `google.genai`, `google.auth`, `websockets`.

If PyInstaller is not configured here, skip this step.

- [ ] **Step 9: Commit any fixups**

```bash
git add -A
git commit -m "test: backfill expectations for OpenAI SDK migration"
```

(Skip this if no fixups were needed.)

---

## Out-of-scope reminders (do not implement here)

- Persisting multiple openai-compat slots side by side.
- Runtime capability probing.
- API-key encryption / OS keyring.
- Anthropic / Gemini `tools=[...]` requests.
- Anthropic extended-thinking budget or OpenAI `reasoning_effort`.
- ProviderPicker UX changes beyond `reload(cfg)`.
- Cross-device config sync.

These belong to the upcoming model-profile spec or future work.
