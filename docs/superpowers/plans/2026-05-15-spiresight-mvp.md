# SpireSight MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a packaged cross-platform desktop app (macOS + Windows) that screenshots Slay the Spire II, sends image+prompt to OpenAI's vision-capable models, and streams a markdown-rendered response, with provider abstraction for future Anthropic/Gemini support.

**Architecture:** Layered pure-Python core (config, prompts, llm abstraction, capture, runner) under a thin PySide6 UI shell. `QThread` workers wrap the runner so streaming chunks flow to the UI via Qt signals. Provider abstraction (`LLMProvider` Protocol + `Capability` enum) lets new providers be added by dropping one file and one registry line.

**Tech Stack:** Python 3.11+, PySide6, `mss`, `pynput`, `openai` SDK, `pydantic` + `pydantic-settings`, `PyYAML`, `pytest` + `respx`, `PyInstaller`.

**Spec:** `docs/superpowers/specs/2026-05-15-spiresight-mvp-design.md`

---

## Conventions

- Python 3.11+ syntax (`X | None`, `StrEnum`, `Self`).
- `src/` layout. Imports use `from spiresight.<pkg> import …`.
- All non-UI tests run with `pytest -q` in under 2s without a display.
- Commits use conventional-commit prefixes (`feat:`, `test:`, `chore:`, `docs:`, `fix:`).
- Each task ends with a commit step.
- "Expected: FAIL" / "Expected: PASS" lines describe the relevant pytest summary line.

---

## Phase A — Foundation

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/spiresight/__init__.py`
- Create: `src/spiresight/__main__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `.env.example`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "spiresight"
version = "0.1.0"
description = "AI visual assistant for Slay the Spire II"
requires-python = ">=3.11"
dependencies = [
  "PySide6>=6.6",
  "mss>=9.0",
  "pynput>=1.7",
  "httpx>=0.27",
  "pydantic>=2.6",
  "pydantic-settings>=2.2",
  "PyYAML>=6.0",
  "Pillow>=10.0",
]
# NOTE: Spec §3 names the `openai` SDK as the MVP LLM library. The
# implementation in src/spiresight/llm/providers/openai_provider.py
# instead talks to the OpenAI API via httpx directly. This gives us
# fine-grained cancellation between SSE chunks (the SDK's streaming
# iterator isn't friendly to mid-stream aborts from another thread).
# The external behavior — endpoint, payload, error mapping — matches
# what the SDK would produce. Swap-in is a one-file change if priorities
# shift.

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "respx>=0.20",
  "httpx>=0.27",
]

[project.scripts]
spiresight = "spiresight.__main__:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
spiresight = ["resources/qss/*.qss", "resources/icons/*.svg", "resources/backgrounds/*.png"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Create empty package files**

```python
# src/spiresight/__init__.py
__version__ = "0.1.0"
```

```python
# src/spiresight/__main__.py
def main() -> int:
    from spiresight.app import run
    return run()

if __name__ == "__main__":
    raise SystemExit(main())
```

```python
# tests/__init__.py
```

```python
# tests/conftest.py
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
```

- [ ] **Step 3: Create `.env.example`**

```
# Optional: override config dir for development
SPIRESIGHT_CONFIG_DIR=
# Optional: pre-seed an OpenAI key (otherwise enter in Settings)
OPENAI_API_KEY=
```

- [ ] **Step 4: Verify install works**

Run: `pip install -e ".[dev]"`
Expected: installation succeeds; `python -c "import spiresight; print(spiresight.__version__)"` prints `0.1.0`.

- [ ] **Step 5: Verify pytest runs**

Run: `pytest -q`
Expected: `no tests ran` summary, exit code 5 is acceptable; treat any other failure as a real problem.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/spiresight tests .env.example
git commit -m "chore: scaffold spiresight package and dev tooling"
```

---

### Task 2: Cross-platform config paths

**Files:**
- Create: `src/spiresight/config/__init__.py`
- Create: `src/spiresight/config/paths.py`
- Test: `tests/test_config_paths.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_paths.py
from pathlib import Path
import sys
import pytest
from spiresight.config import paths


def test_config_dir_uses_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SPIRESIGHT_CONFIG_DIR", str(tmp_path))
    assert paths.config_dir() == tmp_path
    assert paths.config_file() == tmp_path / "config.json"


def test_config_dir_macos(monkeypatch):
    monkeypatch.delenv("SPIRESIGHT_CONFIG_DIR", raising=False)
    monkeypatch.setattr(paths, "_platform", lambda: "darwin")
    monkeypatch.setenv("HOME", "/Users/test")
    assert paths.config_dir() == Path("/Users/test/Library/Application Support/SpireSight")


def test_config_dir_windows(monkeypatch):
    monkeypatch.delenv("SPIRESIGHT_CONFIG_DIR", raising=False)
    monkeypatch.setattr(paths, "_platform", lambda: "win32")
    monkeypatch.setenv("APPDATA", "C:/Users/test/AppData/Roaming")
    assert paths.config_dir() == Path("C:/Users/test/AppData/Roaming/SpireSight")


def test_config_dir_linux(monkeypatch):
    monkeypatch.delenv("SPIRESIGHT_CONFIG_DIR", raising=False)
    monkeypatch.setattr(paths, "_platform", lambda: "linux")
    monkeypatch.setenv("HOME", "/home/test")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert paths.config_dir() == Path("/home/test/.config/SpireSight")


def test_log_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SPIRESIGHT_CONFIG_DIR", str(tmp_path))
    assert paths.log_dir() == tmp_path / "logs"
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_config_paths.py -v`
Expected: FAIL (ImportError on `spiresight.config.paths`).

- [ ] **Step 3: Implement paths module**

```python
# src/spiresight/config/__init__.py
```

```python
# src/spiresight/config/paths.py
"""Cross-platform config and log directory resolution.

Resolution order:
  1. SPIRESIGHT_CONFIG_DIR env var (dev override)
  2. macOS:   ~/Library/Application Support/SpireSight
  3. Windows: %APPDATA%/SpireSight
  4. Linux:   $XDG_CONFIG_HOME/SpireSight or ~/.config/SpireSight
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "SpireSight"


def _platform() -> str:
    return sys.platform


def config_dir() -> Path:
    override = os.environ.get("SPIRESIGHT_CONFIG_DIR")
    if override:
        return Path(override)
    plat = _platform()
    if plat == "darwin":
        return Path(os.environ["HOME"]) / "Library" / "Application Support" / APP_NAME
    if plat == "win32":
        return Path(os.environ["APPDATA"]) / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path(os.environ["HOME"]) / ".config"
    return base / APP_NAME


def config_file() -> Path:
    return config_dir() / "config.json"


def log_dir() -> Path:
    return config_dir() / "logs"


def ensure_dirs() -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    log_dir().mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/test_config_paths.py -v`
Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/config tests/test_config_paths.py
git commit -m "feat(config): cross-platform config and log directory resolution"
```

---

### Task 3: Config schema + atomic store

**Files:**
- Create: `src/spiresight/config/schema.py`
- Create: `src/spiresight/config/store.py`
- Test: `tests/test_config_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_store.py
import json
from pathlib import Path
import pytest
from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.config.store import ConfigStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIRESIGHT_CONFIG_DIR", str(tmp_path))
    return ConfigStore()


def test_load_returns_defaults_when_no_file(store):
    cfg = store.load()
    assert cfg.active_provider == "openai"
    assert cfg.active_model == "gpt-4o"
    assert cfg.language == "en"
    assert cfg.always_on_top is True
    assert cfg.providers == {}


def test_save_then_load_roundtrip(store):
    cfg = AppConfig(active_provider="openai", active_model="gpt-4o-mini")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-test")
    store.save(cfg)
    loaded = store.load()
    assert loaded.active_model == "gpt-4o-mini"
    assert loaded.providers["openai"].api_key == "sk-test"


def test_save_writes_atomically(store, tmp_path):
    cfg = AppConfig()
    store.save(cfg)
    # tmp file must not be left behind
    assert not (tmp_path / "config.json.tmp").exists()
    assert (tmp_path / "config.json").exists()


def test_load_recovers_from_corrupt_file(store, tmp_path):
    (tmp_path / "config.json").write_text("{not json")
    cfg = store.load()
    # corrupt file → defaults returned
    assert cfg.active_provider == "openai"


def test_load_falls_back_when_validation_fails(store, tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"language": "fr"}))
    # "fr" is not in Literal["en", "zh"]; loader returns defaults.
    cfg = store.load()
    assert cfg.language == "en"
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_config_store.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement schema**

```python
# src/spiresight/config/schema.py
"""Pydantic schemas for app and provider configuration.

NOTE(security): ProviderConfig.api_key holds the key in plaintext.
This is the deliberate MVP choice — migrate to OS keyring later.
See docs/superpowers/specs/2026-05-15-spiresight-mvp-design.md §11.1.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(BaseModel):
    api_key: str = ""
    base_url: str | None = None


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    active_provider: str = "openai"
    active_model: str = "gpt-4o"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    language: Literal["en", "zh"] = "en"
    theme: str = "dark_fantasy"
    always_on_top: bool = True
    mini_bar_mode: bool = False
    hotkey: str = "<ctrl>+<shift>+s"
    last_used_prompt_id: str | None = None
```

- [ ] **Step 4: Implement store**

```python
# src/spiresight/config/store.py
"""Atomic JSON-backed config store.

NOTE(security): keys are plaintext in MVP. See schema.py docstring.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import ValidationError

from . import paths
from .schema import AppConfig

log = logging.getLogger(__name__)


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or paths.config_file()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AppConfig:
        if not self._path.exists():
            return AppConfig()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("config.json is corrupt; using defaults")
            return AppConfig()
        try:
            return AppConfig(**raw)
        except ValidationError as exc:
            log.warning("config.json failed validation (%s); using defaults", exc)
            return AppConfig()

    def save(self, cfg: AppConfig) -> None:
        paths.ensure_dirs()
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self._path)
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest tests/test_config_store.py -v`
Expected: PASS, 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/spiresight/config tests/test_config_store.py
git commit -m "feat(config): pydantic schema and atomic JSON store"
```

---

## Phase B — LLM Abstraction

### Task 4: Capability enum and ModelInfo

**Files:**
- Create: `src/spiresight/llm/__init__.py`
- Create: `src/spiresight/llm/capabilities.py`
- Create: `src/spiresight/llm/models.py`
- Test: `tests/test_capabilities.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_capabilities.py
from spiresight.llm.capabilities import Capability
from spiresight.llm.models import ModelInfo


def test_capability_string_values():
    assert Capability.VISION == "vision"
    assert Capability.TOOL_USE == "tool_use"
    assert Capability.JSON_MODE == "json_mode"
    assert Capability.THINKING == "thinking"


def test_modelinfo_is_hashable_and_frozen():
    m = ModelInfo(
        id="gpt-4o",
        display_name="GPT-4o",
        capabilities=frozenset({Capability.VISION, Capability.TOOL_USE}),
        context_window=128_000,
    )
    assert hash(m)
    assert Capability.VISION in m.capabilities


def test_modelinfo_has_capability_helper():
    m = ModelInfo(
        id="gpt-3.5",
        display_name="GPT-3.5",
        capabilities=frozenset(),
        context_window=16_000,
    )
    assert not m.has(Capability.VISION)
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_capabilities.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement modules**

```python
# src/spiresight/llm/__init__.py
```

```python
# src/spiresight/llm/capabilities.py
from __future__ import annotations
from enum import StrEnum


class Capability(StrEnum):
    VISION = "vision"
    TOOL_USE = "tool_use"
    JSON_MODE = "json_mode"
    THINKING = "thinking"
```

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
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/test_capabilities.py -v`
Expected: PASS, 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/llm tests/test_capabilities.py
git commit -m "feat(llm): Capability enum and ModelInfo dataclass"
```

---

### Task 5: LLMProvider Protocol, StreamChunk, errors

**Files:**
- Create: `src/spiresight/llm/provider.py`
- Create: `src/spiresight/llm/errors.py`
- Test: `tests/test_provider_contract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provider_contract.py
import threading
from collections.abc import Iterator

from spiresight.llm.provider import LLMProvider, StreamChunk
from spiresight.llm.models import ModelInfo
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import (
    LLMError,
    MissingAPIKey,
    MissingCapabilityError,
    AuthError,
    RateLimitError,
    NetworkError,
)


class _Fake:
    name = "fake"

    def list_models(self) -> list[ModelInfo]:
        return [ModelInfo("fake-1", "Fake 1", frozenset({Capability.VISION}), 8000)]

    def stream(self, *, model, system, user_text, image_png, cancel_event) -> Iterator[StreamChunk]:
        yield StreamChunk(text_delta="hi")
        yield StreamChunk(text_delta="!", finish_reason="stop")


def test_protocol_structural_typing():
    fake: LLMProvider = _Fake()  # static-typing reassurance; runtime is duck-typed
    assert fake.name == "fake"
    assert fake.list_models()[0].id == "fake-1"


def test_streamchunk_defaults():
    c = StreamChunk(text_delta="x")
    assert c.text_delta == "x"
    assert c.finish_reason is None


def test_errors_inherit_from_llm_error():
    for cls in (MissingAPIKey, MissingCapabilityError, AuthError, RateLimitError, NetworkError):
        assert issubclass(cls, LLMError)


def test_missing_capability_carries_missing_set():
    err = MissingCapabilityError(model="gpt-3.5-turbo", missing={Capability.VISION})
    assert "gpt-3.5-turbo" in str(err)
    assert err.model == "gpt-3.5-turbo"
    assert err.missing == {Capability.VISION}


def test_streaming_via_protocol_consumes_chunks():
    fake: LLMProvider = _Fake()
    chunks = list(fake.stream(
        model="fake-1", system="sys", user_text="hi",
        image_png=None, cancel_event=threading.Event(),
    ))
    assert "".join(c.text_delta for c in chunks) == "hi!"
    assert chunks[-1].finish_reason == "stop"
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_provider_contract.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement provider.py and errors.py**

```python
# src/spiresight/llm/provider.py
from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .models import ModelInfo


@dataclass
class StreamChunk:
    text_delta: str
    finish_reason: str | None = None


@runtime_checkable
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

```python
# src/spiresight/llm/errors.py
from __future__ import annotations

from .capabilities import Capability


class LLMError(Exception):
    """Base class for all LLM-provider-related errors."""


class MissingAPIKey(LLMError):
    def __init__(self, provider: str) -> None:
        super().__init__(f"No API key configured for provider '{provider}'")
        self.provider = provider


class MissingCapabilityError(LLMError):
    def __init__(self, *, model: str, missing: set[Capability]) -> None:
        names = ", ".join(sorted(c.value for c in missing))
        super().__init__(f"Model '{model}' lacks required capabilities: {names}")
        self.model = model
        self.missing = set(missing)


class AuthError(LLMError):
    """Provider rejected the API key (HTTP 401)."""


class RateLimitError(LLMError):
    """Provider rate-limited the request (HTTP 429)."""
    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("Rate limited")
        self.retry_after = retry_after


class NetworkError(LLMError):
    """Network failure or timeout."""
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/test_provider_contract.py -v`
Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/llm tests/test_provider_contract.py
git commit -m "feat(llm): provider Protocol, StreamChunk, and error hierarchy"
```

---

### Task 6: OpenAI provider with streaming

**Files:**
- Create: `src/spiresight/llm/providers/__init__.py`
- Create: `src/spiresight/llm/providers/openai_provider.py`
- Test: `tests/test_openai_provider.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_openai_provider.py
import base64
import threading

import httpx
import pytest
import respx

from spiresight.config.schema import ProviderConfig
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import AuthError, MissingAPIKey, NetworkError, RateLimitError
from spiresight.llm.providers.openai_provider import OpenAIProvider


def _sse(*chunks: str) -> str:
    return "".join(f"data: {c}\n\n" for c in chunks) + "data: [DONE]\n\n"


def test_list_models_includes_vision_and_non_vision():
    p = OpenAIProvider(ProviderConfig(api_key="sk-x"))
    ids = {m.id for m in p.list_models()}
    assert "gpt-4o" in ids and "gpt-4o-mini" in ids
    gpt4o = next(m for m in p.list_models() if m.id == "gpt-4o")
    assert Capability.VISION in gpt4o.capabilities
    non_vision = next(m for m in p.list_models() if m.id == "gpt-3.5-turbo")
    assert Capability.VISION not in non_vision.capabilities


def test_missing_api_key_raises_on_stream():
    p = OpenAIProvider(ProviderConfig(api_key=""))
    with pytest.raises(MissingAPIKey):
        list(p.stream(
            model="gpt-4o", system="s", user_text="hi",
            image_png=None, cancel_event=threading.Event(),
        ))


@respx.mock
def test_stream_text_only_request_yields_chunks():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse(
                '{"choices":[{"delta":{"content":"Hello"}}]}',
                '{"choices":[{"delta":{"content":" world"},"finish_reason":null}]}',
                '{"choices":[{"delta":{},"finish_reason":"stop"}]}',
            ),
        )
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-test"))
    chunks = list(p.stream(
        model="gpt-4o", system="sys", user_text="hi",
        image_png=None, cancel_event=threading.Event(),
    ))
    assert route.called
    assert "".join(c.text_delta for c in chunks) == "Hello world"
    assert chunks[-1].finish_reason == "stop"
    # text-only requests must not include an image part
    body = route.calls.last.request.content.decode()
    assert "image_url" not in body


@respx.mock
def test_stream_with_image_sends_multimodal_payload():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse('{"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}'),
        )
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-test"))
    png = b"\x89PNG\r\n\x1a\nFAKE"
    list(p.stream(
        model="gpt-4o", system="sys", user_text="see this",
        image_png=png, cancel_event=threading.Event(),
    ))
    body = respx.calls.last.request.content.decode()
    expected_b64 = base64.b64encode(png).decode()
    assert "image_url" in body
    assert expected_b64 in body


@respx.mock
def test_401_maps_to_auth_error():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-bad"))
    with pytest.raises(AuthError):
        list(p.stream(
            model="gpt-4o", system="s", user_text="u",
            image_png=None, cancel_event=threading.Event(),
        ))


@respx.mock
def test_429_maps_to_rate_limit():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(429, headers={"retry-after": "3"}, json={})
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-x"))
    with pytest.raises(RateLimitError) as exc:
        list(p.stream(
            model="gpt-4o", system="s", user_text="u",
            image_png=None, cancel_event=threading.Event(),
        ))
    assert exc.value.retry_after == 3.0


@respx.mock
def test_network_error_maps():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=httpx.ConnectError("boom")
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-x"))
    with pytest.raises(NetworkError):
        list(p.stream(
            model="gpt-4o", system="s", user_text="u",
            image_png=None, cancel_event=threading.Event(),
        ))


@respx.mock
def test_cancel_event_aborts_stream_mid_flight():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=_sse(
                '{"choices":[{"delta":{"content":"part1"}}]}',
                '{"choices":[{"delta":{"content":"part2"}}]}',
                '{"choices":[{"delta":{"content":"part3"},"finish_reason":"stop"}]}',
            ),
        )
    )
    p = OpenAIProvider(ProviderConfig(api_key="sk-x"))
    evt = threading.Event()
    out: list[str] = []
    for chunk in p.stream(
        model="gpt-4o", system="s", user_text="u",
        image_png=None, cancel_event=evt,
    ):
        out.append(chunk.text_delta)
        if "part1" in out:
            evt.set()
    assert out == ["part1"]
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_openai_provider.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement the provider**

```python
# src/spiresight/llm/providers/__init__.py
```

```python
# src/spiresight/llm/providers/openai_provider.py
"""OpenAI Chat Completions streaming provider.

Talks to OpenAI's HTTP API directly via httpx so we can parse SSE chunks
incrementally and respect a cancel_event between chunks. This sidesteps
the official SDK's iterator semantics for finer control under Qt.
"""
from __future__ import annotations

import base64
import json
import threading
from collections.abc import Iterator
from typing import Final

import httpx

from spiresight.config.schema import ProviderConfig
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import AuthError, MissingAPIKey, NetworkError, RateLimitError
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import StreamChunk

_DEFAULT_BASE: Final = "https://api.openai.com/v1"

_MODELS: Final = [
    ModelInfo("gpt-4o", "GPT-4o",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE}),
              context_window=128_000),
    ModelInfo("gpt-4o-mini", "GPT-4o mini",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE}),
              context_window=128_000),
    ModelInfo("gpt-4-turbo", "GPT-4 Turbo",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE}),
              context_window=128_000),
    ModelInfo("gpt-3.5-turbo", "GPT-3.5 Turbo",
              frozenset({Capability.TOOL_USE, Capability.JSON_MODE}),
              context_window=16_000),
]


class OpenAIProvider:
    name = "openai"

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    def list_models(self) -> list[ModelInfo]:
        return list(_MODELS)

    def stream(
        self,
        *,
        model: str,
        system: str,
        user_text: str,
        image_png: bytes | None,
        cancel_event: threading.Event,
    ) -> Iterator[StreamChunk]:
        if not self._config.api_key:
            raise MissingAPIKey(self.name)

        base_url = (self._config.base_url or _DEFAULT_BASE).rstrip("/")
        url = f"{base_url}/chat/completions"
        payload = {
            "model": model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": self._build_user_content(user_text, image_png)},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        try:
            with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code == 401:
                        raise AuthError("Invalid OpenAI API key")
                    if resp.status_code == 429:
                        retry = resp.headers.get("retry-after")
                        raise RateLimitError(float(retry) if retry else None)
                    if resp.status_code >= 400:
                        body = resp.read().decode(errors="replace")
                        raise NetworkError(f"OpenAI HTTP {resp.status_code}: {body[:200]}")
                    yield from self._parse_sse(resp, cancel_event)
        except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException) as exc:
            raise NetworkError(str(exc)) from exc

    @staticmethod
    def _build_user_content(text: str, image_png: bytes | None) -> list[dict] | str:
        if image_png is None:
            return text
        b64 = base64.b64encode(image_png).decode()
        return [
            {"type": "text", "text": text},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]

    @staticmethod
    def _parse_sse(resp: httpx.Response, cancel_event: threading.Event) -> Iterator[StreamChunk]:
        for line in resp.iter_lines():
            if cancel_event.is_set():
                return
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                return
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            finish = choices[0].get("finish_reason")
            text = delta.get("content") or ""
            if text or finish:
                yield StreamChunk(text_delta=text, finish_reason=finish)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/test_openai_provider.py -v`
Expected: PASS, 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/llm/providers tests/test_openai_provider.py
git commit -m "feat(llm): OpenAI streaming provider with vision support"
```

---

### Task 7: Anthropic and Gemini stubs

**Files:**
- Create: `src/spiresight/llm/providers/anthropic_provider.py`
- Create: `src/spiresight/llm/providers/gemini_provider.py`
- Test: `tests/test_provider_stubs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provider_stubs.py
import threading
import pytest
from spiresight.config.schema import ProviderConfig
from spiresight.llm.providers.anthropic_provider import AnthropicProvider
from spiresight.llm.providers.gemini_provider import GeminiProvider


@pytest.mark.parametrize("cls,name", [
    (AnthropicProvider, "anthropic"),
    (GeminiProvider, "gemini"),
])
def test_stub_advertises_name_and_models(cls, name):
    p = cls(ProviderConfig(api_key=""))
    assert p.name == name
    assert p.list_models() == []  # stubs offer no models yet


@pytest.mark.parametrize("cls", [AnthropicProvider, GeminiProvider])
def test_stub_stream_raises_not_implemented(cls):
    p = cls(ProviderConfig(api_key="sk-x"))
    with pytest.raises(NotImplementedError):
        list(p.stream(
            model="x", system="s", user_text="u",
            image_png=None, cancel_event=threading.Event(),
        ))
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_provider_stubs.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement stubs**

```python
# src/spiresight/llm/providers/anthropic_provider.py
from __future__ import annotations
import threading
from collections.abc import Iterator
from spiresight.config.schema import ProviderConfig
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import StreamChunk


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    def list_models(self) -> list[ModelInfo]:
        return []

    def stream(self, *, model, system, user_text, image_png, cancel_event) -> Iterator[StreamChunk]:
        raise NotImplementedError("Anthropic provider is not implemented in MVP")
```

```python
# src/spiresight/llm/providers/gemini_provider.py
from __future__ import annotations
import threading
from collections.abc import Iterator
from spiresight.config.schema import ProviderConfig
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import StreamChunk


class GeminiProvider:
    name = "gemini"

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    def list_models(self) -> list[ModelInfo]:
        return []

    def stream(self, *, model, system, user_text, image_png, cancel_event) -> Iterator[StreamChunk]:
        raise NotImplementedError("Gemini provider is not implemented in MVP")
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/test_provider_stubs.py -v`
Expected: PASS, 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/llm/providers tests/test_provider_stubs.py
git commit -m "feat(llm): Anthropic and Gemini stubs raising NotImplementedError"
```

---

### Task 8: Provider registry

**Files:**
- Create: `src/spiresight/llm/registry.py`
- Test: `tests/test_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_registry.py
import pytest
from spiresight.config.schema import ProviderConfig
from spiresight.llm import registry
from spiresight.llm.providers.openai_provider import OpenAIProvider


def test_registry_lists_three_providers():
    assert set(registry.names()) == {"openai", "anthropic", "gemini"}


def test_registry_returns_concrete_provider():
    p = registry.get("openai", ProviderConfig(api_key="sk-x"))
    assert isinstance(p, OpenAIProvider)
    assert p.name == "openai"


def test_registry_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        registry.get("nonesuch", ProviderConfig())
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_registry.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement registry**

```python
# src/spiresight/llm/registry.py
from __future__ import annotations
from collections.abc import Callable

from spiresight.config.schema import ProviderConfig
from spiresight.llm.provider import LLMProvider
from spiresight.llm.providers.openai_provider import OpenAIProvider
from spiresight.llm.providers.anthropic_provider import AnthropicProvider
from spiresight.llm.providers.gemini_provider import GeminiProvider

_PROVIDERS: dict[str, Callable[[ProviderConfig], LLMProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
}


def names() -> list[str]:
    return list(_PROVIDERS.keys())


def get(name: str, config: ProviderConfig) -> LLMProvider:
    if name not in _PROVIDERS:
        raise KeyError(f"Unknown provider: {name}")
    return _PROVIDERS[name](config)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/test_registry.py -v`
Expected: PASS, 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/llm/registry.py tests/test_registry.py
git commit -m "feat(llm): provider registry with name-to-factory mapping"
```

---

## Phase C — Prompts, Capture, Orchestration

### Task 9: Prompt schema and loader

**Files:**
- Create: `src/spiresight/prompts/__init__.py`
- Create: `src/spiresight/prompts/schema.py`
- Create: `src/spiresight/prompts/loader.py`
- Test: `tests/test_prompt_loader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prompt_loader.py
import pytest
from spiresight.llm.capabilities import Capability
from spiresight.prompts.loader import PromptLoader, PromptReferenceError


def _write(p, name, text):
    f = p / name
    f.write_text(text, encoding="utf-8")
    return f


def test_loads_system_prompts(tmp_path):
    _write(tmp_path, "system_prompts.yaml", """
- id: sts_expert
  description: Expert
  content: |
    You are an expert.
""")
    (tmp_path / "locales" / "en").mkdir(parents=True)
    _write(tmp_path / "locales" / "en", "quick_actions.yaml", """
- id: card
  label: Cards
  system_prompt_id: sts_expert
  user_template: "Pick the card. {custom_text}"
  requires_screenshot: true
  required_capabilities: [VISION]
""")
    loader = PromptLoader(tmp_path)
    loader.reload(language="en")
    sp = loader.get_system_prompt("sts_expert")
    assert "expert" in sp.content.lower()
    qa = loader.get_quick_action("card")
    assert qa.label == "Cards"
    assert qa.required_capabilities == [Capability.VISION]
    assert "{custom_text}" in qa.user_template


def test_quick_actions_listed_in_order(tmp_path):
    _write(tmp_path, "system_prompts.yaml", "- id: s\n  description: ''\n  content: x\n")
    (tmp_path / "locales" / "en").mkdir(parents=True)
    _write(tmp_path / "locales" / "en", "quick_actions.yaml", """
- {id: a, label: A, system_prompt_id: s, user_template: "{custom_text}", required_capabilities: []}
- {id: b, label: B, system_prompt_id: s, user_template: "{custom_text}", required_capabilities: []}
""")
    loader = PromptLoader(tmp_path)
    loader.reload(language="en")
    assert [q.id for q in loader.quick_actions()] == ["a", "b"]


def test_dangling_system_prompt_reference_raises(tmp_path):
    _write(tmp_path, "system_prompts.yaml", "- id: s\n  description: ''\n  content: x\n")
    (tmp_path / "locales" / "en").mkdir(parents=True)
    _write(tmp_path / "locales" / "en", "quick_actions.yaml", """
- {id: a, label: A, system_prompt_id: missing, user_template: "{custom_text}", required_capabilities: []}
""")
    loader = PromptLoader(tmp_path)
    with pytest.raises(PromptReferenceError):
        loader.reload(language="en")


def test_locale_fallback_to_english(tmp_path):
    _write(tmp_path, "system_prompts.yaml", "- id: s\n  description: ''\n  content: x\n")
    (tmp_path / "locales" / "en").mkdir(parents=True)
    _write(tmp_path / "locales" / "en", "quick_actions.yaml", """
- {id: a, label: A, system_prompt_id: s, user_template: "{custom_text}", required_capabilities: []}
""")
    loader = PromptLoader(tmp_path)
    loader.reload(language="zh")  # zh dir doesn't exist
    assert loader.get_quick_action("a").label == "A"
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_prompt_loader.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement schema and loader**

```python
# src/spiresight/prompts/__init__.py
```

```python
# src/spiresight/prompts/schema.py
from __future__ import annotations
from pydantic import BaseModel, Field
from spiresight.llm.capabilities import Capability


class SystemPrompt(BaseModel):
    id: str
    description: str = ""
    content: str


class QuickAction(BaseModel):
    id: str
    label: str
    icon: str | None = None
    system_prompt_id: str
    user_template: str
    requires_screenshot: bool = True
    required_capabilities: list[Capability] = Field(default_factory=list)
```

```python
# src/spiresight/prompts/loader.py
"""YAML-backed prompt loader.

Layout:
  <root>/system_prompts.yaml
  <root>/locales/<lang>/quick_actions.yaml

Reload reads both files into memory and validates cross-references.
Reload is cheap; call it whenever the user changes language.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .schema import QuickAction, SystemPrompt


class PromptReferenceError(ValueError):
    """A QuickAction references a SystemPrompt id that doesn't exist."""


class PromptLoader:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._system: dict[str, SystemPrompt] = {}
        self._actions: dict[str, QuickAction] = {}
        self._action_order: list[str] = []

    def reload(self, language: str) -> None:
        sys_path = self._root / "system_prompts.yaml"
        sys_raw = yaml.safe_load(sys_path.read_text(encoding="utf-8")) or []
        self._system = {sp.id: sp for sp in (SystemPrompt(**r) for r in sys_raw)}

        actions_path = self._root / "locales" / language / "quick_actions.yaml"
        if not actions_path.exists():
            actions_path = self._root / "locales" / "en" / "quick_actions.yaml"
        raw = yaml.safe_load(actions_path.read_text(encoding="utf-8")) or []
        actions = [QuickAction(**r) for r in raw]
        for qa in actions:
            if qa.system_prompt_id not in self._system:
                raise PromptReferenceError(
                    f"QuickAction '{qa.id}' references unknown system_prompt_id "
                    f"'{qa.system_prompt_id}'"
                )
        self._actions = {qa.id: qa for qa in actions}
        self._action_order = [qa.id for qa in actions]

    def get_system_prompt(self, prompt_id: str) -> SystemPrompt:
        return self._system[prompt_id]

    def get_quick_action(self, action_id: str) -> QuickAction:
        return self._actions[action_id]

    def quick_actions(self) -> list[QuickAction]:
        return [self._actions[i] for i in self._action_order]
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/test_prompt_loader.py -v`
Expected: PASS, 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/prompts tests/test_prompt_loader.py
git commit -m "feat(prompts): YAML loader with cross-reference validation"
```

---

### Task 10: Ship default prompt YAML files (EN + ZH)

**Files:**
- Create: `prompts/system_prompts.yaml`
- Create: `prompts/locales/en/quick_actions.yaml`
- Create: `prompts/locales/zh/quick_actions.yaml`
- Test: `tests/test_default_prompts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_default_prompts.py
from pathlib import Path
from spiresight.prompts.loader import PromptLoader

REPO = Path(__file__).resolve().parents[1]
PROMPTS = REPO / "prompts"


def test_default_prompts_load_en():
    loader = PromptLoader(PROMPTS)
    loader.reload(language="en")
    ids = [qa.id for qa in loader.quick_actions()]
    for required in ("card_selection", "combat_strategy", "pathfinding", "relic_analysis"):
        assert required in ids


def test_default_prompts_load_zh():
    loader = PromptLoader(PROMPTS)
    loader.reload(language="zh")
    # zh must define the same ids
    assert {qa.id for qa in loader.quick_actions()} >= {
        "card_selection", "combat_strategy", "pathfinding", "relic_analysis",
    }
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_default_prompts.py -v`
Expected: FAIL (FileNotFoundError on system_prompts.yaml).

- [ ] **Step 3: Create system prompts**

```yaml
# prompts/system_prompts.yaml
- id: sts_expert
  description: General Slay the Spire II strategist
  content: |
    You are an expert Slay the Spire II strategist. You analyze game
    screenshots and provide concise, actionable advice.

    Conventions:
    - Lead with the recommendation in one sentence.
    - Justify in <= 3 bullet points.
    - Call out risks explicitly.
    - When uncertain, say so.

    Priorities, in order: immediate threats, long-run deck health,
    energy/economy curves.
```

- [ ] **Step 4: Create English quick actions**

```yaml
# prompts/locales/en/quick_actions.yaml
- id: card_selection
  label: "Card Selection Guide"
  icon: icons/card.svg
  system_prompt_id: sts_expert
  user_template: "Help me choose between the offered cards. {custom_text}"
  requires_screenshot: true
  required_capabilities: [VISION]

- id: combat_strategy
  label: "Combat Strategy"
  icon: icons/sword.svg
  system_prompt_id: sts_expert
  user_template: "What's the best play this turn? {custom_text}"
  requires_screenshot: true
  required_capabilities: [VISION]

- id: pathfinding
  label: "Pathfinding"
  icon: icons/path.svg
  system_prompt_id: sts_expert
  user_template: "Which path should I take and why? {custom_text}"
  requires_screenshot: true
  required_capabilities: [VISION]

- id: relic_analysis
  label: "Relic Analysis"
  icon: icons/relic.svg
  system_prompt_id: sts_expert
  user_template: "Evaluate this relic offering. {custom_text}"
  requires_screenshot: true
  required_capabilities: [VISION]
```

- [ ] **Step 5: Create Chinese quick actions**

```yaml
# prompts/locales/zh/quick_actions.yaml
- id: card_selection
  label: "选牌建议"
  icon: icons/card.svg
  system_prompt_id: sts_expert
  user_template: "请帮我选择卡牌。{custom_text}"
  requires_screenshot: true
  required_capabilities: [VISION]

- id: combat_strategy
  label: "战斗策略"
  icon: icons/sword.svg
  system_prompt_id: sts_expert
  user_template: "本回合最佳出牌是什么?{custom_text}"
  requires_screenshot: true
  required_capabilities: [VISION]

- id: pathfinding
  label: "地图选路"
  icon: icons/path.svg
  system_prompt_id: sts_expert
  user_template: "应该选哪条路线?为什么?{custom_text}"
  requires_screenshot: true
  required_capabilities: [VISION]

- id: relic_analysis
  label: "遗物评估"
  icon: icons/relic.svg
  system_prompt_id: sts_expert
  user_template: "评估这个遗物。{custom_text}"
  requires_screenshot: true
  required_capabilities: [VISION]
```

- [ ] **Step 6: Run tests, expect pass**

Run: `pytest tests/test_default_prompts.py -v`
Expected: PASS, 2 passed.

- [ ] **Step 7: Commit**

```bash
git add prompts tests/test_default_prompts.py
git commit -m "feat(prompts): ship default EN/ZH quick actions and system prompt"
```

---

### Task 11: Screen capture

**Files:**
- Create: `src/spiresight/capture/__init__.py`
- Create: `src/spiresight/capture/screen.py`
- Test: `tests/test_screen_capture.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_screen_capture.py
from io import BytesIO
import pytest
from PIL import Image

from spiresight.capture.screen import ScreenCapture, ScreenCaptureError


class _FakeMonitor:
    width = 4
    height = 2


class _FakeShot:
    width = 4
    height = 2
    rgb = b"\xff\x00\x00" * 8  # solid red, 4x2


class _FakeMSS:
    def __init__(self):
        self.monitors = [None, {"left": 0, "top": 0, "width": 4, "height": 2}]
    def grab(self, region):
        return _FakeShot()
    def __enter__(self): return self
    def __exit__(self, *a): pass


def test_capture_returns_png_bytes(monkeypatch):
    monkeypatch.setattr("spiresight.capture.screen.mss.mss", _FakeMSS)
    data = ScreenCapture().grab_primary()
    img = Image.open(BytesIO(data))
    assert img.format == "PNG"
    assert img.size == (4, 2)


def test_capture_wraps_errors(monkeypatch):
    class _Broken(_FakeMSS):
        def grab(self, region):
            raise RuntimeError("display unavailable")
    monkeypatch.setattr("spiresight.capture.screen.mss.mss", _Broken)
    with pytest.raises(ScreenCaptureError):
        ScreenCapture().grab_primary()
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_screen_capture.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement capture**

```python
# src/spiresight/capture/__init__.py
```

```python
# src/spiresight/capture/screen.py
"""Primary-screen capture as PNG bytes."""
from __future__ import annotations

from io import BytesIO

import mss
from PIL import Image


class ScreenCaptureError(RuntimeError):
    """Raised when the OS refuses to provide a screen image."""


class ScreenCapture:
    def grab_primary(self) -> bytes:
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # 0 is "all monitors"; 1 is primary
                shot = sct.grab(monitor)
        except Exception as exc:
            raise ScreenCaptureError(str(exc)) from exc
        img = Image.frombytes("RGB", (shot.width, shot.height), shot.rgb)
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=False)
        return buf.getvalue()
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/test_screen_capture.py -v`
Expected: PASS, 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/capture tests/test_screen_capture.py
git commit -m "feat(capture): primary-screen PNG capture via mss"
```

---

### Task 12: InferenceRequest + InferenceRunner

**Files:**
- Create: `src/spiresight/core/__init__.py`
- Create: `src/spiresight/core/request.py`
- Create: `src/spiresight/core/runner.py`
- Test: `tests/test_inference_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_inference_runner.py
import threading
import pytest

from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.core.request import InferenceRequest
from spiresight.core.runner import InferenceRunner
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import MissingAPIKey, MissingCapabilityError
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import StreamChunk
from spiresight.prompts.schema import QuickAction, SystemPrompt


class _FakeLoader:
    def __init__(self, qa, sp):
        self._qa, self._sp = qa, sp
    def get_quick_action(self, _): return self._qa
    def get_system_prompt(self, _): return self._sp


class _FakeProvider:
    name = "openai"
    def __init__(self, models, chunks):
        self._models = models
        self._chunks = chunks
        self.last_call: dict | None = None
    def list_models(self): return self._models
    def stream(self, *, model, system, user_text, image_png, cancel_event):
        self.last_call = dict(model=model, system=system, user_text=user_text,
                              image_png=image_png)
        yield from self._chunks


class _FakeCapture:
    def grab_primary(self): return b"PNG_BYTES"


def _runner(*, provider, loader, capture=None):
    cfg = AppConfig(active_provider="openai", active_model="gpt-4o")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    return InferenceRunner(
        config=cfg,
        prompt_loader=loader,
        provider_factory=lambda name, pcfg: provider,
        screen_capture=capture or _FakeCapture(),
    )


def test_run_streams_text_with_image_when_required():
    qa = QuickAction(id="card", label="Cards", system_prompt_id="s",
                     user_template="Pick. {custom_text}",
                     requires_screenshot=True,
                     required_capabilities=[Capability.VISION])
    sp = SystemPrompt(id="s", description="", content="be helpful")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o", frozenset({Capability.VISION}), 128_000)],
        chunks=[StreamChunk("Hello"), StreamChunk(" world", "stop")],
    )
    runner = _runner(provider=provider, loader=_FakeLoader(qa, sp))
    out = list(runner.run(
        InferenceRequest(prompt_id="card", custom_text="extra", include_screenshot=True),
        cancel_event=threading.Event(),
    ))
    assert "".join(c.text_delta for c in out) == "Hello world"
    assert provider.last_call["model"] == "gpt-4o"
    assert provider.last_call["system"] == "be helpful"
    assert provider.last_call["user_text"] == "Pick. extra"
    assert provider.last_call["image_png"] == b"PNG_BYTES"


def test_run_omits_image_when_screenshot_unchecked():
    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="just text {custom_text}",
                     requires_screenshot=True,
                     required_capabilities=[])
    sp = SystemPrompt(id="s", description="", content="s")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o", frozenset(), 128_000)],
        chunks=[StreamChunk("ok", "stop")],
    )
    runner = _runner(provider=provider, loader=_FakeLoader(qa, sp))
    list(runner.run(InferenceRequest("x", "", include_screenshot=False),
                    cancel_event=threading.Event()))
    assert provider.last_call["image_png"] is None


def test_capability_pre_flight_blocks_non_vision_model():
    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="t",
                     requires_screenshot=True,
                     required_capabilities=[Capability.VISION])
    sp = SystemPrompt(id="s", description="", content="s")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-3.5", "gpt-3.5", frozenset(), 16_000)],
        chunks=[],
    )
    cfg = AppConfig(active_provider="openai", active_model="gpt-3.5")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    runner = InferenceRunner(
        config=cfg,
        prompt_loader=_FakeLoader(qa, sp),
        provider_factory=lambda n, p: provider,
        screen_capture=_FakeCapture(),
    )
    with pytest.raises(MissingCapabilityError) as exc:
        list(runner.run(
            InferenceRequest("x", "", include_screenshot=True),
            cancel_event=threading.Event(),
        ))
    assert exc.value.missing == {Capability.VISION}


def test_missing_api_key_raises():
    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="t", requires_screenshot=False,
                     required_capabilities=[])
    sp = SystemPrompt(id="s", description="", content="s")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o", frozenset(), 128_000)],
        chunks=[],
    )
    cfg = AppConfig(active_provider="openai", active_model="gpt-4o")
    cfg.providers["openai"] = ProviderConfig(api_key="")
    runner = InferenceRunner(
        config=cfg, prompt_loader=_FakeLoader(qa, sp),
        provider_factory=lambda n, p: provider, screen_capture=_FakeCapture(),
    )
    with pytest.raises(MissingAPIKey):
        list(runner.run(InferenceRequest("x", "", False), cancel_event=threading.Event()))
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_inference_runner.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement request and runner**

```python
# src/spiresight/core/__init__.py
```

```python
# src/spiresight/core/request.py
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class InferenceRequest:
    prompt_id: str
    custom_text: str
    include_screenshot: bool
```

```python
# src/spiresight/core/runner.py
"""Orchestrates a single inference request end-to-end.

Pure Python, no Qt. Wrapped by ui/workers/inference_worker for the
QThread-based UI integration.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Iterator

from spiresight.capture.screen import ScreenCapture
from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.core.request import InferenceRequest
from spiresight.llm.errors import MissingAPIKey, MissingCapabilityError
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import LLMProvider, StreamChunk
from spiresight.prompts.loader import PromptLoader

ProviderFactory = Callable[[str, ProviderConfig], LLMProvider]


class InferenceRunner:
    def __init__(
        self,
        *,
        config: AppConfig,
        prompt_loader: PromptLoader,
        provider_factory: ProviderFactory,
        screen_capture: ScreenCapture,
    ) -> None:
        self._config = config
        self._loader = prompt_loader
        self._factory = provider_factory
        self._capture = screen_capture

    def run(
        self,
        request: InferenceRequest,
        *,
        cancel_event: threading.Event,
    ) -> Iterator[StreamChunk]:
        qa = self._loader.get_quick_action(request.prompt_id)
        sp = self._loader.get_system_prompt(qa.system_prompt_id)
        user_text = qa.user_template.format(custom_text=request.custom_text or "")

        provider_cfg = self._config.providers.get(
            self._config.active_provider, ProviderConfig()
        )
        if not provider_cfg.api_key:
            raise MissingAPIKey(self._config.active_provider)
        provider = self._factory(self._config.active_provider, provider_cfg)

        model = self._resolve_model(provider, self._config.active_model)
        missing = set(qa.required_capabilities) - set(model.capabilities)
        if missing:
            raise MissingCapabilityError(model=model.id, missing=missing)

        image_png: bytes | None = None
        if qa.requires_screenshot and request.include_screenshot:
            image_png = self._capture.grab_primary()

        yield from provider.stream(
            model=model.id,
            system=sp.content,
            user_text=user_text,
            image_png=image_png,
            cancel_event=cancel_event,
        )

    @staticmethod
    def _resolve_model(provider: LLMProvider, model_id: str) -> ModelInfo:
        for m in provider.list_models():
            if m.id == model_id:
                return m
        raise KeyError(f"Model '{model_id}' not advertised by provider '{provider.name}'")
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/test_inference_runner.py -v`
Expected: PASS, 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/core tests/test_inference_runner.py
git commit -m "feat(core): InferenceRunner with capability pre-flight"
```

---

### Task 13: Hotkey manager (headless tests)

**Files:**
- Create: `src/spiresight/hotkey/__init__.py`
- Create: `src/spiresight/hotkey/manager.py`
- Test: `tests/test_hotkey_manager.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hotkey_manager.py
import pytest
from spiresight.hotkey.manager import HotkeyManager, HotkeyRegistrationFailed


class _FakeListener:
    instances: list["_FakeListener"] = []

    def __init__(self, hotkeys=None):
        self.hotkeys = hotkeys
        self.started = False
        self.stopped = False
        _FakeListener.instances.append(self)

    def start(self): self.started = True
    def stop(self): self.stopped = True


class _BrokenListener:
    def __init__(self, hotkeys=None): raise RuntimeError("no permission")


def test_start_registers_hotkey(monkeypatch):
    _FakeListener.instances.clear()
    monkeypatch.setattr("spiresight.hotkey.manager.GlobalHotKeys", _FakeListener)
    hits: list[bool] = []
    mgr = HotkeyManager("<ctrl>+<shift>+s", on_press=lambda: hits.append(True))
    mgr.start()
    assert _FakeListener.instances[0].started
    # invoke the registered callback
    cb = next(iter(_FakeListener.instances[0].hotkeys.values()))
    cb()
    assert hits == [True]
    mgr.stop()
    assert _FakeListener.instances[0].stopped


def test_start_raises_friendly_error_on_permission_failure(monkeypatch):
    monkeypatch.setattr("spiresight.hotkey.manager.GlobalHotKeys", _BrokenListener)
    mgr = HotkeyManager("<ctrl>+<shift>+s", on_press=lambda: None)
    with pytest.raises(HotkeyRegistrationFailed):
        mgr.start()
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_hotkey_manager.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement hotkey manager**

```python
# src/spiresight/hotkey/__init__.py
```

```python
# src/spiresight/hotkey/manager.py
"""Global hotkey registration via pynput, isolated for testability.

The pynput dependency is imported at module load but the listener
class is referenced by name so tests can monkeypatch it.
"""
from __future__ import annotations

from collections.abc import Callable

from pynput.keyboard import GlobalHotKeys  # re-exported for monkeypatching


class HotkeyRegistrationFailed(RuntimeError):
    """Raised when the OS refuses to register the global hotkey."""


class HotkeyManager:
    def __init__(self, combo: str, *, on_press: Callable[[], None]) -> None:
        self._combo = combo
        self._on_press = on_press
        self._listener = None

    def start(self) -> None:
        try:
            self._listener = GlobalHotKeys({self._combo: self._on_press})
            self._listener.start()
        except Exception as exc:
            raise HotkeyRegistrationFailed(str(exc)) from exc

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/test_hotkey_manager.py -v`
Expected: PASS, 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/hotkey tests/test_hotkey_manager.py
git commit -m "feat(hotkey): pynput-backed global hotkey manager with error wrapping"
```

---

## Phase D — UI (PySide6)

> UI code is verified manually. Unit tests for these components are deliberately deferred (see spec §10).

### Task 14: Resources and theme loader

**Files:**
- Create: `src/spiresight/resources/__init__.py`
- Create: `src/spiresight/resources/qss/dark_fantasy.qss`
- Create: `src/spiresight/ui/__init__.py`
- Create: `src/spiresight/ui/theme.py`

- [ ] **Step 1: Create the QSS file**

```qss
/* src/spiresight/resources/qss/dark_fantasy.qss
   Dark-fantasy palette. Color tokens are inlined; if you change one,
   update src/spiresight/ui/theme.py::COLORS to match. */

QWidget {
    background-color: #1a1410;
    color: #d9b885;
    font-family: "Inter", "SF Pro Text", "Segoe UI", sans-serif;
    font-size: 12px;
}

QMainWindow, QDialog {
    background-color: #1a1410;
}

QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser {
    background-color: #15100c;
    border: 1px solid #4a3422;
    border-radius: 4px;
    padding: 6px;
    selection-background-color: #7a5728;
}

QComboBox {
    background-color: #1f160f;
    border: 1px solid #4a3422;
    border-radius: 4px;
    padding: 4px 8px;
}

QComboBox QAbstractItemView {
    background-color: #15100c;
    selection-background-color: #7a5728;
    border: 1px solid #4a3422;
}

QPushButton {
    background-color: #1f160f;
    border: 1px solid #4a3422;
    border-radius: 4px;
    padding: 6px 12px;
    color: #d9b885;
}

QPushButton:hover { background-color: #2a1d14; }
QPushButton:pressed { background-color: #15100c; }

QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #a87838, stop:1 #7a5728);
    border: 1px solid #c8a878;
    color: #1a1410;
    font-weight: 600;
}

QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #4a3422;
    background: #15100c;
}
QCheckBox::indicator:checked { background: #c8a878; }

QLabel[role="badge-vision"] {
    color: #b9d9b9;
    background: #3d5a3d;
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 10px;
}

QStatusBar { background-color: #0a0705; color: #88715a; }
```

- [ ] **Step 2: Implement theme loader**

```python
# src/spiresight/resources/__init__.py
```

```python
# src/spiresight/ui/__init__.py
```

```python
# src/spiresight/ui/theme.py
"""QSS loader and color tokens.

Tokens here must match the values in resources/qss/dark_fantasy.qss.
"""
from __future__ import annotations

from importlib import resources

COLORS = {
    "bg": "#1a1410",
    "panel": "#15100c",
    "border": "#4a3422",
    "text": "#d9b885",
    "muted": "#88715a",
    "accent": "#c8a878",
    "ember": "#a87838",
}


def load_qss(name: str = "dark_fantasy") -> str:
    return resources.files("spiresight.resources.qss").joinpath(f"{name}.qss").read_text(
        encoding="utf-8"
    )
```

- [ ] **Step 3: Verify package data is found**

Run: `python -c "from spiresight.ui.theme import load_qss; print(load_qss()[:40])"`
Expected: prints the first 40 characters of the QSS file (starts with `/* src/spiresight/resources/qss/`).

- [ ] **Step 4: Commit**

```bash
git add src/spiresight/resources src/spiresight/ui
git commit -m "feat(ui): dark-fantasy QSS theme and loader"
```

---

### Task 15: Provider/model picker widget

**Files:**
- Create: `src/spiresight/ui/widgets/__init__.py`
- Create: `src/spiresight/ui/widgets/provider_picker.py`

- [ ] **Step 1: Implement the widget**

```python
# src/spiresight/ui/widgets/__init__.py
```

```python
# src/spiresight/ui/widgets/provider_picker.py
"""Provider + model dropdowns with capability badges.

Emits selection_changed(provider_name, model_id) when either changes.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from spiresight.llm import registry
from spiresight.llm.capabilities import Capability
from spiresight.config.schema import ProviderConfig


class ProviderPicker(QWidget):
    selection_changed = Signal(str, str)  # provider, model_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._provider_box = QComboBox()
        for name in registry.names():
            self._provider_box.addItem(name.capitalize(), userData=name)

        model_row = QHBoxLayout()
        self._model_box = QComboBox()
        self._badge = QLabel()
        self._badge.setProperty("role", "badge-vision")
        self._badge.setVisible(False)
        model_row.addWidget(self._model_box, stretch=1)
        model_row.addWidget(self._badge)

        layout.addWidget(QLabel("Provider"))
        layout.addWidget(self._provider_box)
        layout.addWidget(QLabel("Model"))
        layout.addLayout(model_row)

        self._provider_box.currentIndexChanged.connect(self._reload_models)
        self._model_box.currentIndexChanged.connect(self._emit)

    def set_active(self, provider: str, model_id: str) -> None:
        idx = self._provider_box.findData(provider)
        if idx >= 0:
            self._provider_box.setCurrentIndex(idx)
        self._reload_models()
        midx = self._model_box.findData(model_id)
        if midx >= 0:
            self._model_box.setCurrentIndex(midx)

    def _reload_models(self) -> None:
        self._model_box.clear()
        name = self._provider_box.currentData()
        provider = registry.get(name, ProviderConfig())
        for m in provider.list_models():
            label = m.display_name
            if Capability.VISION in m.capabilities:
                label += "  (vision)"
            self._model_box.addItem(label, userData=m.id)
        self._update_badge()
        self._emit()

    def _update_badge(self) -> None:
        name = self._provider_box.currentData()
        model_id = self._model_box.currentData()
        if not name or not model_id:
            self._badge.setVisible(False)
            return
        provider = registry.get(name, ProviderConfig())
        for m in provider.list_models():
            if m.id == model_id:
                vision = Capability.VISION in m.capabilities
                self._badge.setText("vision" if vision else "no vision")
                self._badge.setVisible(True)
                return
        self._badge.setVisible(False)

    def _emit(self) -> None:
        self._update_badge()
        self.selection_changed.emit(
            self._provider_box.currentData() or "",
            self._model_box.currentData() or "",
        )
```

- [ ] **Step 2: Smoke import check**

Run: `python -c "from spiresight.ui.widgets.provider_picker import ProviderPicker; print('ok')"`
Expected: prints `ok` (PySide6 must be installed).

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/ui/widgets
git commit -m "feat(ui): provider/model picker with vision badge"
```

---

### Task 16: Quick-action prompt panel

**Files:**
- Create: `src/spiresight/ui/widgets/prompt_panel.py`

- [ ] **Step 1: Implement the widget**

```python
# src/spiresight/ui/widgets/prompt_panel.py
"""Vertical list of quick-action buttons.

Emits action_clicked(action_id).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from spiresight.prompts.loader import PromptLoader


class PromptPanel(QWidget):
    action_clicked = Signal(str)

    def __init__(self, loader: PromptLoader, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loader = loader
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._header = QLabel("Quick Actions")
        self._layout.addWidget(self._header)
        self.rebuild()

    def rebuild(self) -> None:
        # remove everything except the header (index 0) — buttons and any
        # trailing stretch are both regenerated.
        while self._layout.count() > 1:
            item = self._layout.takeAt(1)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for qa in self._loader.quick_actions():
            btn = QPushButton(qa.label)
            btn.clicked.connect(lambda _=False, aid=qa.id: self.action_clicked.emit(aid))
            self._layout.addWidget(btn)
        self._layout.addStretch(1)
```

- [ ] **Step 2: Smoke import check**

Run: `python -c "from spiresight.ui.widgets.prompt_panel import PromptPanel; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/ui/widgets/prompt_panel.py
git commit -m "feat(ui): quick-action prompt panel"
```

---

### Task 17: Streaming markdown output view

**Files:**
- Create: `src/spiresight/ui/widgets/output_view.py`

- [ ] **Step 1: Implement the widget**

```python
# src/spiresight/ui/widgets/output_view.py
"""Streaming markdown view.

Buffers incoming text deltas and re-renders markdown at most every
50ms (or every 32 deltas) to keep the UI responsive.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import QTextBrowser

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
        self.setMarkdown("")

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

    def _flush(self) -> None:
        self.setMarkdown("".join(self._buffer))
        self._pending = 0
        # keep scroll pinned to bottom while streaming
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())
```

- [ ] **Step 2: Smoke import check**

Run: `python -c "from spiresight.ui.widgets.output_view import OutputView; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/ui/widgets/output_view.py
git commit -m "feat(ui): streaming markdown output view with debounced flush"
```

---

### Task 18: Inference worker (QThread)

**Files:**
- Create: `src/spiresight/ui/workers/__init__.py`
- Create: `src/spiresight/ui/workers/inference_worker.py`

- [ ] **Step 1: Implement the worker**

```python
# src/spiresight/ui/workers/__init__.py
```

```python
# src/spiresight/ui/workers/inference_worker.py
"""QThread wrapping InferenceRunner.

Emits one signal per chunk and one terminal signal: either finished
on success, or failed(exception) on any error (including capability/
API-key issues — UI catches and renders these as modals).
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from spiresight.core.request import InferenceRequest
from spiresight.core.runner import InferenceRunner


class InferenceWorker(QThread):
    chunk = Signal(str)              # text delta
    finished_ok = Signal()           # successful end-of-stream
    failed = Signal(object)          # exception instance

    def __init__(self, runner: InferenceRunner, request: InferenceRequest, parent=None) -> None:
        super().__init__(parent)
        self._runner = runner
        self._request = request
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            for c in self._runner.run(self._request, cancel_event=self._cancel):
                if c.text_delta:
                    self.chunk.emit(c.text_delta)
                if c.finish_reason is not None:
                    break
            self.finished_ok.emit()
        except Exception as exc:  # noqa: BLE001 — UI thread renders all errors
            self.failed.emit(exc)
```

- [ ] **Step 2: Smoke import check**

Run: `python -c "from spiresight.ui.workers.inference_worker import InferenceWorker; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/ui/workers
git commit -m "feat(ui): InferenceWorker QThread bridging runner to Qt signals"
```

---

### Task 19: Mini-bar widget

**Files:**
- Create: `src/spiresight/ui/widgets/mini_bar.py`

- [ ] **Step 1: Implement the mini-bar**

```python
# src/spiresight/ui/widgets/mini_bar.py
"""Always-on-top compact bar with quick-action buttons.

Frameless, draggable. Emits the same action_clicked(action_id) signal
as the main PromptPanel so a single handler covers both.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from spiresight.prompts.loader import PromptLoader


class MiniBar(QWidget):
    action_clicked = Signal(str)
    expand_requested = Signal()

    def __init__(self, loader: PromptLoader, hotkey_hint: str, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._drag_offset: QPoint | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)
        for qa in loader.quick_actions():
            btn = QPushButton(qa.label)
            btn.clicked.connect(lambda _=False, aid=qa.id: self.action_clicked.emit(aid))
            row.addWidget(btn)
        row.addWidget(QLabel(hotkey_hint))
        expand = QPushButton("▭")
        expand.setToolTip("Expand to main window")
        expand.clicked.connect(self.expand_requested.emit)
        row.addWidget(expand)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._drag_offset = None
```

- [ ] **Step 2: Smoke import check**

Run: `python -c "from spiresight.ui.widgets.mini_bar import MiniBar; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/ui/widgets/mini_bar.py
git commit -m "feat(ui): draggable always-on-top mini-bar"
```

---

### Task 20: Settings dialog

**Files:**
- Create: `src/spiresight/ui/windows/__init__.py`
- Create: `src/spiresight/ui/windows/settings_dialog.py`

- [ ] **Step 1: Implement the dialog**

```python
# src/spiresight/ui/windows/__init__.py
```

```python
# src/spiresight/ui/windows/settings_dialog.py
"""Settings dialog: API keys per provider, language, hotkey, always-on-top."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QLineEdit, QTabWidget, QVBoxLayout, QWidget,
)

from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.llm import registry


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SpireSight — Settings")
        self._config = config
        self._key_inputs: dict[str, QLineEdit] = {}

        root = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_keys_tab(), "API Keys")
        tabs.addTab(self._build_general_tab(), "General")
        root.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._apply_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_keys_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        for name in registry.names():
            cfg = self._config.providers.get(name, ProviderConfig())
            edit = QLineEdit(cfg.api_key)
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setPlaceholderText(f"{name} API key")
            self._key_inputs[name] = edit
            form.addRow(name.capitalize(), edit)
        return page

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

        form.addRow("Language", self._lang)
        form.addRow("Hotkey", self._hotkey)
        form.addRow("Always on top", self._on_top)
        return page

    def _apply_and_accept(self) -> None:
        for name, edit in self._key_inputs.items():
            current = self._config.providers.get(name, ProviderConfig())
            self._config.providers[name] = ProviderConfig(
                api_key=edit.text().strip(),
                base_url=current.base_url,
            )
        self._config.language = self._lang.currentData()
        self._config.hotkey = self._hotkey.text().strip() or self._config.hotkey
        self._config.always_on_top = self._on_top.isChecked()
        self.accept()
```

- [ ] **Step 2: Smoke import check**

Run: `python -c "from spiresight.ui.windows.settings_dialog import SettingsDialog; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/ui/windows
git commit -m "feat(ui): settings dialog (keys, language, hotkey, always-on-top)"
```

---

### Task 21: macOS permission dialog

**Files:**
- Create: `src/spiresight/ui/windows/permission_dialog.py`

- [ ] **Step 1: Implement the dialog**

```python
# src/spiresight/ui/windows/permission_dialog.py
"""First-launch macOS Accessibility permission helper.

Shown when HotkeyRegistrationFailed is raised on darwin.
"""
from __future__ import annotations

import subprocess
import sys

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout


class PermissionDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Accessibility Permission Required")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "SpireSight needs Accessibility permission to register the\n"
            "global hotkey on macOS.\n\n"
            "Click below to open System Settings, find SpireSight under\n"
            "Privacy & Security → Accessibility, and toggle it on, then\n"
            "restart the app."
        ))
        open_btn = QPushButton("Open System Settings")
        open_btn.clicked.connect(self._open_settings)
        layout.addWidget(open_btn)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    @staticmethod
    def _open_settings() -> None:
        if sys.platform != "darwin":
            return
        subprocess.Popen([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        ])
```

- [ ] **Step 2: Commit**

```bash
git add src/spiresight/ui/windows/permission_dialog.py
git commit -m "feat(ui): macOS Accessibility permission dialog"
```

---

### Task 22: Main window

**Files:**
- Create: `src/spiresight/ui/windows/main_window.py`

- [ ] **Step 1: Implement the main window**

```python
# src/spiresight/ui/windows/main_window.py
"""Primary application window.

Wires PromptPanel + ProviderPicker + custom text + Send button +
OutputView. Owns the InferenceWorker lifecycle, the MiniBar toggle,
and the SettingsDialog. Catches MissingCapabilityError / MissingAPIKey
and renders the appropriate modal.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QStatusBar, QVBoxLayout, QWidget,
)

from spiresight.capture.screen import ScreenCapture
from spiresight.config.schema import AppConfig
from spiresight.config.store import ConfigStore
from spiresight.core.request import InferenceRequest
from spiresight.core.runner import InferenceRunner
from spiresight.llm import registry
from spiresight.llm.errors import (
    AuthError, MissingAPIKey, MissingCapabilityError, NetworkError, RateLimitError,
)
from spiresight.prompts.loader import PromptLoader
from spiresight.ui.widgets.mini_bar import MiniBar
from spiresight.ui.widgets.output_view import OutputView
from spiresight.ui.widgets.prompt_panel import PromptPanel
from spiresight.ui.widgets.provider_picker import ProviderPicker
from spiresight.ui.windows.settings_dialog import SettingsDialog
from spiresight.ui.workers.inference_worker import InferenceWorker


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, store: ConfigStore, loader: PromptLoader) -> None:
        super().__init__()
        self.setWindowTitle("SpireSight")
        self.resize(880, 520)
        self._config = config
        self._store = store
        self._loader = loader
        self._capture = ScreenCapture()
        self._worker: InferenceWorker | None = None
        self._mini_bar: MiniBar | None = None

        self._apply_always_on_top()

        # left sidebar
        self._picker = ProviderPicker()
        self._picker.set_active(config.active_provider, config.active_model)
        self._picker.selection_changed.connect(self._on_picker_changed)

        self._prompt_panel = PromptPanel(loader)
        self._prompt_panel.action_clicked.connect(self._on_action)

        sidebar = QWidget()
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(12, 12, 12, 12)
        sb_layout.addWidget(self._picker)
        sb_layout.addSpacing(12)
        sb_layout.addWidget(self._prompt_panel)
        sb_layout.addStretch(1)
        sidebar.setFixedWidth(240)

        # right pane
        self._custom_text = QPlainTextEdit()
        self._custom_text.setPlaceholderText("Optional context for this query…")
        self._custom_text.setMaximumHeight(80)

        self._include_screenshot = QCheckBox("Include screenshot")
        self._include_screenshot.setChecked(True)

        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("primary")
        self._send_btn.clicked.connect(self._on_send_last)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        controls = QHBoxLayout()
        controls.addWidget(self._include_screenshot)
        controls.addStretch(1)
        controls.addWidget(self._cancel_btn)
        controls.addWidget(self._send_btn)

        self._output = OutputView()

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.addWidget(QLabel("Custom (optional)"))
        right_layout.addWidget(self._custom_text)
        right_layout.addLayout(controls)
        right_layout.addWidget(self._output, stretch=1)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.addWidget(sidebar)
        body_layout.addWidget(right, stretch=1)
        self.setCentralWidget(body)

        # menubar (Settings, Mini-bar)
        menu = self.menuBar().addMenu("&App")
        menu.addAction("Settings…", self._open_settings)
        menu.addAction("Mini-bar mode", self._toggle_mini_bar)
        menu.addSeparator()
        menu.addAction("Quit", self.close)

        self.setStatusBar(QStatusBar())

    # ─── lifecycle helpers ───────────────────────────────────────

    def _apply_always_on_top(self) -> None:
        flags = self.windowFlags()
        if self._config.always_on_top:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)

    def _on_picker_changed(self, provider: str, model_id: str) -> None:
        if provider:
            self._config.active_provider = provider
        if model_id:
            self._config.active_model = model_id
        self._store.save(self._config)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._config, self)
        if dlg.exec():
            self._store.save(self._config)
            self._loader.reload(language=self._config.language)
            self._prompt_panel.rebuild()
            self._apply_always_on_top()
            self.show()  # re-apply flags

    def _toggle_mini_bar(self) -> None:
        if self._mini_bar is None:
            self._mini_bar = MiniBar(self._loader, hotkey_hint=self._config.hotkey)
            self._mini_bar.action_clicked.connect(self._on_action)
            self._mini_bar.expand_requested.connect(self._exit_mini_bar)
        self.hide()
        self._mini_bar.show()
        self._config.mini_bar_mode = True
        self._store.save(self._config)

    def _exit_mini_bar(self) -> None:
        if self._mini_bar is not None:
            self._mini_bar.hide()
        self.show()
        self._config.mini_bar_mode = False
        self._store.save(self._config)

    # ─── inference flow ──────────────────────────────────────────

    def fire_last_action(self) -> None:
        """Called by the global hotkey."""
        if self._config.last_used_prompt_id:
            self._on_action(self._config.last_used_prompt_id)

    def _on_send_last(self) -> None:
        # If no previously-clicked action, default to the first quick action.
        actions = self._loader.quick_actions()
        if not actions:
            return
        action_id = self._config.last_used_prompt_id or actions[0].id
        self._on_action(action_id)

    def _on_action(self, action_id: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            return  # one at a time
        self._config.last_used_prompt_id = action_id
        self._store.save(self._config)

        runner = InferenceRunner(
            config=self._config,
            prompt_loader=self._loader,
            provider_factory=registry.get,
            screen_capture=self._capture,
        )
        request = InferenceRequest(
            prompt_id=action_id,
            custom_text=self._custom_text.toPlainText().strip(),
            include_screenshot=self._include_screenshot.isChecked(),
        )
        self._output.reset()
        self._send_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self.statusBar().showMessage("Streaming…")

        self._worker = InferenceWorker(runner, request, self)
        self._worker.chunk.connect(self._output.append_delta)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _on_finished(self) -> None:
        self._output.finalize()
        self._reset_buttons()
        self.statusBar().showMessage("Done.", 3000)

    def _on_failed(self, exc: Exception) -> None:
        self._output.finalize()
        self._reset_buttons()
        if isinstance(exc, MissingAPIKey):
            QMessageBox.warning(self, "API key required",
                                "Add your API key under App → Settings → API Keys.")
        elif isinstance(exc, MissingCapabilityError):
            missing = ", ".join(sorted(c.value for c in exc.missing))
            QMessageBox.warning(self, "Model can't do that",
                                f"Model '{exc.model}' lacks: {missing}.\n"
                                f"Switch model or uncheck 'Include screenshot'.")
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

    def _reset_buttons(self) -> None:
        self._send_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
```

- [ ] **Step 2: Smoke import check**

Run: `python -c "from spiresight.ui.windows.main_window import MainWindow; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/ui/windows/main_window.py
git commit -m "feat(ui): main window wiring picker, prompts, worker, mini-bar"
```

---

## Phase E — App Bootstrap & Polish

### Task 23: Logging setup

**Files:**
- Create: `src/spiresight/logging_setup.py`
- Test: `tests/test_logging_setup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_logging_setup.py
import logging
from spiresight.logging_setup import configure_logging
from spiresight.config import paths


def test_configure_creates_rotating_file_handler(monkeypatch, tmp_path):
    monkeypatch.setenv("SPIRESIGHT_CONFIG_DIR", str(tmp_path))
    paths.ensure_dirs()
    configure_logging()
    log = logging.getLogger("spiresight.test")
    log.info("hello")
    log_file = paths.log_dir() / "app.log"
    assert log_file.exists()
    assert "hello" in log_file.read_text()
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_logging_setup.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement logging setup**

```python
# src/spiresight/logging_setup.py
"""Single place to configure logging for the app and CLI entry."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from spiresight.config import paths


def configure_logging(level: int = logging.INFO) -> None:
    paths.ensure_dirs()
    root = logging.getLogger()
    root.setLevel(level)
    # avoid duplicate handlers on hot-reload
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s")
    file_h = RotatingFileHandler(
        paths.log_dir() / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8",
    )
    file_h.setFormatter(fmt)
    root.addHandler(file_h)
    stream_h = logging.StreamHandler()
    stream_h.setFormatter(fmt)
    root.addHandler(stream_h)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/test_logging_setup.py -v`
Expected: PASS, 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/spiresight/logging_setup.py tests/test_logging_setup.py
git commit -m "feat: rotating-file + stream logging configuration"
```

---

### Task 24: App bootstrap

**Files:**
- Create: `src/spiresight/app.py`

- [ ] **Step 1: Implement the bootstrap**

```python
# src/spiresight/app.py
"""QApplication wiring: load config, prompts, theme, hotkey, main window."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from spiresight.config import paths
from spiresight.config.store import ConfigStore
from spiresight.hotkey.manager import HotkeyManager, HotkeyRegistrationFailed
from spiresight.logging_setup import configure_logging
from spiresight.prompts.loader import PromptLoader
from spiresight.ui.theme import load_qss
from spiresight.ui.windows.main_window import MainWindow
from spiresight.ui.windows.permission_dialog import PermissionDialog

log = logging.getLogger(__name__)


def _prompts_root() -> Path:
    """Locate the prompts/ directory whether running from source or bundle."""
    here = Path(__file__).resolve()
    # source layout: <repo>/src/spiresight/app.py → <repo>/prompts/
    for parent in here.parents:
        candidate = parent / "prompts"
        if (candidate / "system_prompts.yaml").exists():
            return candidate
    raise FileNotFoundError("Could not locate prompts/ directory")


def run() -> int:
    configure_logging()
    paths.ensure_dirs()

    store = ConfigStore()
    config = store.load()

    loader = PromptLoader(_prompts_root())
    loader.reload(language=config.language)

    qt_app = QApplication(sys.argv)
    qt_app.setStyleSheet(load_qss(config.theme))

    window = MainWindow(config, store, loader)
    window.show()

    hotkey_mgr: HotkeyManager | None = None
    try:
        hotkey_mgr = HotkeyManager(config.hotkey, on_press=window.fire_last_action)
        hotkey_mgr.start()
    except HotkeyRegistrationFailed as exc:
        log.warning("Hotkey registration failed: %s", exc)
        if sys.platform == "darwin":
            PermissionDialog(window).exec()

    try:
        return qt_app.exec()
    finally:
        if hotkey_mgr is not None:
            hotkey_mgr.stop()
```

- [ ] **Step 2: Smoke import check**

Run: `python -c "from spiresight.app import run; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/spiresight/app.py
git commit -m "feat: app bootstrap (config, prompts, theme, hotkey, main window)"
```

---

### Task 25: Manual smoke test and README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Author README**

```markdown
# SpireSight

AI visual assistant for *Slay the Spire II*. Captures a screenshot, runs a
selected prompt through a vision-capable LLM, streams markdown advice back.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate    # macOS / Linux
# .venv\Scripts\activate                              # Windows

pip install -e ".[dev]"
python -m spiresight
```

On first run, open **App → Settings → API Keys** and paste your OpenAI key.

## macOS: Accessibility permission

The global hotkey (`Ctrl/Cmd + Shift + S` by default) needs Accessibility
permission. If registration fails, a dialog opens System Settings — toggle
SpireSight on, then relaunch.

## Layout

- `src/spiresight/` — application code
- `prompts/` — user-editable system prompts and locale-specific quick actions
- `tests/` — pytest suite (`pytest -q`, runs in <2s, no display required)
- `docs/superpowers/specs/` — design document for the MVP

## Adding a provider

1. Drop a file at `src/spiresight/llm/providers/<name>_provider.py` implementing
   the `LLMProvider` Protocol (`name`, `list_models()`, `stream(...)`).
2. Register the factory in `src/spiresight/llm/registry.py::_PROVIDERS`.
3. Done — UI picks it up automatically.

## Security note

API keys are stored in **plaintext** in the app's config directory in this
MVP. Migration to the OS keyring is tracked in the design doc.
```

- [ ] **Step 2: Run the full test suite**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 3: Manual smoke test**

Steps (perform manually — UI is not automated):
1. Run `python -m spiresight`.
2. Open Settings, paste an OpenAI key, click OK.
3. Type "I'm at 12 HP fighting Hexaghost" in the custom text area.
4. Click "Combat Strategy" with "Include screenshot" checked.
5. Verify: stream begins within ~2s, markdown renders bolds/lists, finishes cleanly.
6. Click "Mini-bar mode" — main window hides, mini-bar appears, draggable, always on top.
7. Press the global hotkey — fires the last action (Combat Strategy) again.
8. Switch model to `gpt-3.5-turbo` in the picker, click Combat Strategy → capability warning modal appears.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README with quickstart, layout, and security note"
```

---

### Task 26: PyInstaller packaging recipe

**Files:**
- Create: `packaging/spiresight.spec`
- Create: `packaging/build.sh`
- Create: `packaging/build.bat`

- [ ] **Step 1: Write the PyInstaller spec**

```python
# packaging/spiresight.spec
# Run from repo root: pyinstaller packaging/spiresight.spec
# Produces a windowed (no console) bundle that includes prompts/ and resources/.

from PyInstaller.utils.hooks import collect_data_files
import sys

datas = [
    ("prompts", "prompts"),
    ("src/spiresight/resources", "spiresight/resources"),
]

a = Analysis(
    ["src/spiresight/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "spiresight.llm.providers.openai_provider",
        "spiresight.llm.providers.anthropic_provider",
        "spiresight.llm.providers.gemini_provider",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="SpireSight",
    console=False,
    icon=None,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    name="SpireSight",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="SpireSight.app",
        icon=None,
        bundle_identifier="dev.haochen.spiresight",
    )
```

- [ ] **Step 2: Write build scripts**

```bash
# packaging/build.sh
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
pip install pyinstaller
pyinstaller --noconfirm packaging/spiresight.spec
echo "Bundle: dist/SpireSight/  (or dist/SpireSight.app on macOS)"
```

```bat
:: packaging/build.bat
@echo off
pushd "%~dp0\.."
pip install pyinstaller
pyinstaller --noconfirm packaging\spiresight.spec
echo Bundle: dist\SpireSight\
popd
```

- [ ] **Step 3: Mark build.sh executable and verify (do not commit a bundle)**

```bash
chmod +x packaging/build.sh
```

Optional sanity check: `bash packaging/build.sh`. Bundle output lands in `dist/` (gitignored).

- [ ] **Step 4: Commit**

```bash
git add packaging
git commit -m "chore: PyInstaller spec and build scripts for mac/windows"
```

---

## Done

After Task 26, you have:
- A working `python -m spiresight` desktop app on macOS and Windows
- Streaming OpenAI chat with vision support
- Capability pre-flight that catches model/feature mismatches at send time
- Always-on-top main window + draggable mini-bar + global hotkey
- YAML-decoupled prompts in EN + ZH
- Plaintext config persistence (with `# TODO(security)` marker for the keyring follow-up)
- A pytest suite covering every non-UI module, running in under 2s without a display
- A reproducible PyInstaller build recipe

Open follow-ups, in priority order, are listed in spec §11 (Future Improvements).
