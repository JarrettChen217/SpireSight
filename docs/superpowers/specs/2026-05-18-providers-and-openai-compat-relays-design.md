# Providers + OpenAI-Compatible Relays

- **Date:** 2026-05-18
- **Status:** design approved, implementation pending
- **Related specs:** `2026-05-15-spiresight-mvp-design.md`, `2026-05-18-logs-request-context-and-timeout-design.md`
- **Sibling spec (future):** model profiles (fast / medium / accurate, per-feature mapping)

## 1. Motivation

Three pain points share a provider-layer fix:

1. `AnthropicProvider` and `GeminiProvider` are `NotImplementedError` stubs. Only OpenAI works end-to-end today.
2. Users want to route through OpenAI-compatible relays (OpenRouter, DeepSeek, Groq, Ollama, …) to test cheaper / faster / locally-hosted models. The schema (`ProviderConfig.base_url`) already supports this, but Settings does not expose it.
3. The OpenAI provider rolls its own SSE parser via raw httpx. Anthropic / Gemini reaching feature parity would require duplicating that work. Adopting official SDKs across all three providers is the simpler path now that we tolerate chunk-granularity cancel.

We will:

- Adopt the official `openai`, `anthropic`, and `google-genai` SDKs for all three providers, replacing the existing httpx-based OpenAI implementation.
- Add a fourth provider entry `"openai_compat"` (subclass of OpenAI) that requires `base_url` and has no built-in model list.
- Add per-provider remote model refresh: a `fetch_remote_models()` method, a `ModelRefreshWorker`, and a Settings UI that triggers it and caches the result into `ProviderConfig.cached_models`.
- Rewrite the Settings dialog around a `ProviderPane` widget that surfaces api_key + (optional) base_url + Refresh + cached-model count per provider.
- Maintain a small static `KNOWN_MODEL_CAPS` table so refreshed model IDs map to plausible capability sets; unknown IDs assume-all-true and the inference is surfaced in request logs.

## 2. Non-goals

- Persisting multiple OpenAI-compatible relay entries side by side. One slot only; switching relays means editing `base_url` and re-refreshing.
- Runtime capability probing — `infer_capabilities` is a static table plus a permissive fallback.
- API-key encryption / OS keyring migration. Plaintext per the existing MVP decision.
- Anthropic / Gemini `tools=[…]` requests. Capability advertising only.
- Anthropic extended-thinking budget or OpenAI `reasoning_effort` parameters — left to the future model-profile spec.
- Changing the existing `AppConfig.active_provider` / `active_model` interaction. ProviderPicker stays as-is; `openai_compat` joins the dropdown via `registry.names()`.
- Cross-device config import/export.

## 3. Architecture overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          SettingsDialog                                  │
│ ┌─────────────────────────────────────────────────────────────────────┐ │
│ │ Providers (parent tab)                                              │ │
│ │ ┌─ OpenAI ──┬─ OpenAI-Compat ──┬─ Anthropic ──┬─ Gemini ──┐         │ │
│ │ │ [api_key]            │ [api_key]                                  │ │
│ │ │ [base_url? + preset] │ [base_url?]                                │ │
│ │ │ [Refresh]  N models  │ [Refresh]  N models                        │ │
│ │ └──────────────────────┴────────────────────────────────────────┘   │ │
│ ├─ General  (existing — request_timeout_seconds already lives here)   │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ click Refresh
                                 ▼
              ┌─────────────────────────────────────┐
              │      ModelRefreshWorker (QThread)    │
              │  provider.fetch_remote_models()      │
              │  succeeded(name, list[ModelInfo])    │
              │  failed(name, Exception)             │
              └────────┬─────────────────┬──────────┘
                       │ persist          │ QMessageBox + LogsTab
                       ▼                  ▼
       AppConfig.providers[name].cached_models  →  ConfigStore.save()
                       ▲
                       │ list_models() reads cached_models;
                       │ falls back to _BUILTIN_DEFAULTS when empty
                       │
       ┌────────────────────────────────────────────────────────────┐
       │              registry.make_provider(name, cfg, opts)        │
       │ "openai"        → OpenAIProvider          (openai SDK)     │
       │ "openai_compat" → OpenAICompatProvider    (subclass)        │
       │ "anthropic"     → AnthropicProvider       (anthropic SDK)   │
       │ "gemini"        → GeminiProvider          (google-genai SDK)│
       └────────────────────────────────────────────────────────────┘
```

## 4. Schema changes (`config/schema.py`)

```python
from typing import Literal
from pydantic import BaseModel, Field


class ModelInfoDict(BaseModel):
    """JSON-serializable mirror of llm.models.ModelInfo for ProviderConfig."""
    id: str
    display_name: str
    capabilities: list[Literal["vision", "tool_use", "json_mode", "thinking"]] = []
    context_window: int = 0


class ProviderConfig(BaseModel):
    api_key: str = ""
    base_url: str | None = None
    cached_models: list[ModelInfoDict] = Field(default_factory=list)


class AppConfig(BaseSettings):
    ...
    active_provider: Literal["openai", "openai_compat", "anthropic", "gemini"] = "openai"
```

`ModelInfoDict` is independent of `llm.models.ModelInfo` to avoid a `config → llm` import in the wrong direction. The two are bridged by `ModelInfo.from_dict(d)` / `ModelInfo.to_dict()`. Migration is implicit: pydantic supplies the empty default for any older config.json that lacks these keys.

## 5. `LLMProvider` protocol extension

```python
# llm/provider.py
@runtime_checkable
class LLMProvider(Protocol):
    name: str
    def list_models(self) -> list[ModelInfo]: ...
    def fetch_remote_models(self) -> list[ModelInfo]:
        """Fetch models from the upstream API. May raise LLMError on failure."""
    def stream(self, *, model, system, user_text="", images=(), messages=None,
               cancel_event=None, json_mode=False) -> Iterator[StreamChunk]: ...
```

Every concrete provider implements `fetch_remote_models()`. Errors propagate as `AuthError`, `RateLimitError`, `RequestTimeoutError`, or generic `NetworkError`.

## 6. OpenAI provider — rewrite around `openai` SDK

The current httpx-based implementation is replaced. Cancellation moves from per-SSE-line to per-chunk (the SDK's iterator boundary), which is acceptable.

```python
# llm/providers/openai_provider.py
from openai import OpenAI, APIStatusError, APIConnectionError, APITimeoutError

class OpenAIProvider:
    name = "openai"
    _DEFAULT_BASE: Final[str | None] = "https://api.openai.com/v1"
    _BUILTIN_DEFAULTS: Final[list[ModelInfo]] = [...]  # current _MODELS list

    def __init__(self, config: ProviderConfig, options: ProviderOptions) -> None:
        self._config = config
        self._options = options
        base = config.base_url or self._DEFAULT_BASE
        if base is None:
            raise MissingBaseURL(self.name)   # OpenAICompatProvider path
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
            raise RequestTimeoutError(f"Refresh timed out after {self._options.request_timeout_seconds}s") from exc
        except APIStatusError as exc:
            if exc.status_code == 401:
                raise AuthError("Invalid OpenAI API key") from exc
            raise NetworkError(f"HTTP {exc.status_code}: {exc.message}") from exc
        except APIConnectionError as exc:
            raise NetworkError(str(exc)) from exc

        out: list[ModelInfo] = []
        for m in resp.data:
            caps, _inferred = infer_capabilities(m.id)
            out.append(ModelInfo(id=m.id, display_name=m.id, capabilities=caps, context_window=0))
        return out

    def stream(self, *, model, system, user_text="", images=(), messages=None,
               cancel_event=None, json_mode=False) -> Iterator[StreamChunk]:
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
        except APIStatusError as exc:
            if exc.status_code == 401:
                raise AuthError("Invalid OpenAI API key") from exc
            if exc.status_code == 429:
                retry = exc.response.headers.get("retry-after") if exc.response else None
                raise RateLimitError(float(retry) if retry else None) from exc
            raise NetworkError(f"HTTP {exc.status_code}: {exc.message}") from exc
        except APIConnectionError as exc:
            raise NetworkError(str(exc)) from exc
```

`_build_messages` and `_build_user_content` static methods are preserved unchanged from the current implementation.

## 7. OpenAI-compat provider

```python
# llm/providers/openai_compat_provider.py
from spiresight.llm.providers.openai_provider import OpenAIProvider

RELAY_PRESETS: Final[dict[str, str]] = {
    "OpenRouter":   "https://openrouter.ai/api/v1",
    "DeepSeek":     "https://api.deepseek.com/v1",
    "Groq":         "https://api.groq.com/openai/v1",
    "Ollama local": "http://localhost:11434/v1",
}

class OpenAICompatProvider(OpenAIProvider):
    """OpenAI Chat Completions API against a third-party relay.

    Inherits stream() and fetch_remote_models() unchanged. Differences from
    the base class:
      - name is "openai_compat"
      - base_url is required (no fallback to api.openai.com)
      - _BUILTIN_DEFAULTS is empty: model selection comes entirely from the
        cached_models populated by the user's Settings Refresh action.
    """
    name = "openai_compat"
    _DEFAULT_BASE: Final[str | None] = None
    _BUILTIN_DEFAULTS: Final[list[ModelInfo]] = []
```

New error in `llm/errors.py`:

```python
class MissingBaseURL(LLMError):
    def __init__(self, provider: str) -> None:
        super().__init__(f"Provider '{provider}' requires base_url to be set in Settings")
        self.provider = provider
```

## 8. Anthropic provider

```python
# llm/providers/anthropic_provider.py
from anthropic import Anthropic, APIStatusError, APIConnectionError, APITimeoutError

class AnthropicProvider:
    name = "anthropic"
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
            raise NetworkError(f"HTTP {exc.status_code}: {exc.message}") from exc
        except APIConnectionError as exc:
            raise NetworkError(str(exc)) from exc

        out: list[ModelInfo] = []
        for m in resp.data:
            caps, _ = infer_capabilities(m.id)
            out.append(ModelInfo(id=m.id, display_name=getattr(m, "display_name", m.id) or m.id,
                                  capabilities=caps, context_window=200_000))
        return out

    def stream(self, *, model, system, user_text="", images=(), messages=None,
               cancel_event=None, json_mode=False) -> Iterator[StreamChunk]:
        del json_mode  # Anthropic has no native JSON mode; relies on prompt
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
                for event in stream:
                    if cancel_event.is_set():
                        return
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield StreamChunk(text_delta=event.delta.text, finish_reason=None, usage=None)
                    elif event.type == "message_stop":
                        msg = stream.current_message_snapshot
                        usage = TokenUsage(
                            input_tokens=int(msg.usage.input_tokens or 0),
                            output_tokens=int(msg.usage.output_tokens or 0),
                        ) if msg and msg.usage else None
                        yield StreamChunk(text_delta="", finish_reason="stop", usage=usage)
        except APITimeoutError as exc:
            raise RequestTimeoutError(
                f"Request exceeded {self._options.request_timeout_seconds}s timeout"
            ) from exc
        except APIStatusError as exc:
            if exc.status_code == 401:
                raise AuthError("Invalid Anthropic API key") from exc
            if exc.status_code == 429:
                raise RateLimitError() from exc
            raise NetworkError(f"HTTP {exc.status_code}: {exc.message}") from exc
        except APIConnectionError as exc:
            raise NetworkError(str(exc)) from exc

    @staticmethod
    def _build_messages(messages, user_text, images) -> list[dict]:
        """Anthropic content schema:
          role:    "user" | "assistant"
          content: str | list of {"type":"text","text":...} or
                                 {"type":"image","source":{"type":"base64","media_type":"image/png","data":...}}
        """
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

Notes:

- Anthropic's `system` is a top-level argument, not a message with role=system. The provider keeps it separate.
- `max_tokens=8192` is a required field; the value is generous for current quick-action and inspect use cases.
- `json_mode` is accepted but ignored at the provider level; the inspector's system prompt already forces JSON output. `RequestSnapshot.params` will surface `json_mode_supported: False` so the user can see it in LogsTab.

## 9. Gemini provider

```python
# llm/providers/gemini_provider.py
from google import genai
from google.genai import types as genai_types
from google.genai import errors as genai_errors

class GeminiProvider:
    name = "gemini"
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

    def __init__(self, config: ProviderConfig, options: ProviderOptions) -> None:
        self._config = config
        self._options = options
        http_options = (
            genai_types.HttpOptions(base_url=config.base_url) if config.base_url else None
        )
        self._client = genai.Client(api_key=config.api_key or "missing", http_options=http_options)

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
            mid = m.name.removeprefix("models/")
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

    def stream(self, *, model, system, user_text="", images=(), messages=None,
               cancel_event=None, json_mode=False) -> Iterator[StreamChunk]:
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
        """Gemini Content schema:
          role:  "user" | "model"   (assistant → model)
          parts: list of {"text": ...} or Part.from_bytes(data, mime_type)
        """
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

## 10. Registry

```python
# llm/registry.py
def names() -> list[str]:
    return ["openai", "openai_compat", "anthropic", "gemini"]

def make_provider(name, config, options=None):
    options = options or ProviderOptions()
    if name == "openai":        return OpenAIProvider(config, options)
    if name == "openai_compat": return OpenAICompatProvider(config, options)
    if name == "anthropic":     return AnthropicProvider(config, options)
    if name == "gemini":        return GeminiProvider(config, options)
    raise KeyError(f"Unknown provider: {name}")
```

## 11. Capability inference (`llm/capability_table.py`)

```python
from spiresight.llm.capabilities import Capability

_V, _T, _J, _TH = Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING

KNOWN_MODEL_CAPS: dict[str, frozenset[Capability]] = {
    # OpenAI
    "gpt-5":            frozenset({_V, _T, _J, _TH}),
    "gpt-5.5":          frozenset({_V, _T, _J, _TH}),
    "gpt-5-mini":       frozenset({_V, _T, _J, _TH}),
    "gpt-4o":           frozenset({_V, _T, _J}),
    "gpt-4o-mini":      frozenset({_V, _T, _J}),
    "o4-mini":          frozenset({_V, _T, _TH}),
    "o3":               frozenset({_V, _T, _TH}),
    "gpt-3.5-turbo":    frozenset({_T, _J}),

    # Anthropic
    "claude-opus-4-7-20251015":    frozenset({_V, _T, _J, _TH}),
    "claude-sonnet-4-6-20251001":  frozenset({_V, _T, _J, _TH}),
    "claude-haiku-4-5-20251001":   frozenset({_V, _T, _J}),

    # Gemini
    "gemini-2.5-pro":         frozenset({_V, _T, _J, _TH}),
    "gemini-2.5-flash":       frozenset({_V, _T, _J, _TH}),
    "gemini-2.5-flash-lite":  frozenset({_V, _T, _J}),

    # OpenRouter (common aliases — non-exhaustive)
    "anthropic/claude-opus-4-7":       frozenset({_V, _T, _J, _TH}),
    "google/gemini-2.5-pro":           frozenset({_V, _T, _J, _TH}),
    "deepseek/deepseek-chat":          frozenset({_T, _J}),
    "deepseek/deepseek-reasoner":      frozenset({_T, _TH}),
    "meta-llama/llama-3.3-70b":        frozenset({_T}),

    # DeepSeek direct
    "deepseek-chat":      frozenset({_T, _J}),
    "deepseek-reasoner":  frozenset({_T, _TH}),

    # Groq
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

`ModelInfo` itself does not store the inferred-flag; instead, when runner builds a `RequestSnapshot`, it includes `params["capabilities_inferred"] = inferred` so LogsTab can surface it.

## 12. `ModelInfo` ↔ `ModelInfoDict` bridge

```python
# llm/models.py
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
        assert isinstance(d, ModelInfoDict)
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

Lazy import inside the methods avoids a circular import at module load.

## 13. `ModelRefreshWorker` (`ui/workers/model_refresh_worker.py`)

```python
from PySide6.QtCore import QThread, Signal

class ModelRefreshWorker(QThread):
    """Fetches the upstream model list for one provider, off the UI thread."""
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

## 14. Settings dialog rewrite

The existing `SettingsDialog` keeps its `General` tab unchanged. The `API Keys` tab is replaced by a `Providers` parent tab containing a nested `QTabWidget` with one `ProviderPane` per provider.

### 14.1 `ProviderPane` widget (`ui/widgets/provider_pane.py`)

```python
class ProviderPane(QWidget):
    def __init__(
        self,
        provider_name: str,
        config: ProviderConfig,
        *,
        require_base_url: bool,
        base_url_presets: dict[str, str] | None = None,
        on_refresh: Callable[[str], None],
        parent=None,
    ) -> None:
        ...
```

UI elements:

| Control | Notes |
|---|---|
| `api_key: QLineEdit (Password)` | Always shown. |
| `base_url_preset: QComboBox` | Editable=False. Items: preset names + "Custom…". Hidden when `require_base_url=False` and config has no base_url already. |
| `base_url: QLineEdit` | Shown whenever `require_base_url` or `base_url_preset` is visible. Selecting a preset writes to this field; user edits override. |
| `refresh_btn: QPushButton("Refresh")` | Disabled while a worker is in flight. Calls `on_refresh(provider_name)`. |
| `model_count: QLabel("N models cached")` | Updates on refresh success. Shows `"using built-in defaults"` when `cached_models` is empty. |

Public API:

```python
def api_key_value(self) -> str: ...
def base_url_value(self) -> str: ...
def set_busy(self, busy: bool) -> None: ...
def set_model_count(self, n: int) -> None: ...
```

### 14.2 `SettingsDialog` orchestration

```python
class SettingsDialog(QDialog):
    models_refreshed = Signal(str)              # provider_name
    models_refresh_failed = Signal(str, object) # provider_name, Exception

    def __init__(self, config: AppConfig, store: ConfigStore, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._store = store
        self._panes: dict[str, ProviderPane] = {}
        self._workers: dict[str, ModelRefreshWorker] = {}
        # ...build tabs:
        # - Providers (nested QTabWidget with one ProviderPane per registry.names())
        # - General (unchanged)

    def refresh_provider(self, name: str) -> None:
        pane = self._panes[name]
        pane.set_busy(True)
        cfg_now = ProviderConfig(
            api_key=pane.api_key_value(),
            base_url=pane.base_url_value() or None,
            cached_models=self._config.providers.get(name, ProviderConfig()).cached_models,
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
        # `models` is list[ModelInfo]
        cur = self._config.providers.get(name, ProviderConfig())
        self._config.providers[name] = ProviderConfig(
            api_key=cur.api_key,
            base_url=cur.base_url,
            cached_models=[m.to_dict() for m in models],
        )
        self._store.save(self._config)
        self._panes[name].set_model_count(len(models))
        self.models_refreshed.emit(name)

    def _on_refresh_failed(self, name: str, exc: Exception) -> None:
        QMessageBox.warning(self, "Refresh failed", f"{name}: {exc}")
        # LogsTab access lives in MainWindow; emit a signal so MainWindow can
        # append the log line without giving this dialog a LogsTab reference.
        self.models_refresh_failed.emit(name, exc)

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

Add a second signal `models_refresh_failed = Signal(str, object)` mirroring `models_refreshed` so MainWindow can log both outcomes to `LogsTab` without `SettingsDialog` taking a reference to it.

### 14.3 MainWindow wiring

```python
dialog = SettingsDialog(self._config, self._store, parent=self)
dialog.models_refreshed.connect(self._on_provider_models_refreshed)
dialog.models_refresh_failed.connect(self._on_provider_models_refresh_failed)
dialog.exec()
```

`_on_provider_models_refreshed(name)` reloads the provider picker if `name == self._config.active_provider` and appends a log line. `_on_provider_models_refresh_failed(name, exc)` logs the error.

## 15. Dependencies

`pyproject.toml`:

```toml
dependencies = [
    ...
    "openai>=1.50.0",
    "anthropic>=0.40.0",
    "google-genai>=1.0.0",
]
```

Estimated PyInstaller bundle delta: +10–15 MB (including transitive `google-auth`, `websockets`, etc.). Acceptable for desktop distribution.

`registry.make_provider` and provider constructors must not make network calls — verified by inspection: `OpenAI()`, `Anthropic()`, `genai.Client()` are all client-construction only.

Re-run `uv lock` (or `pip-compile`) to update the lockfile after the dependency bump.

## 16. Error path summary

| Origin | Wrapped as | Worker / UI behavior |
|---|---|---|
| `APITimeoutError` | `RequestTimeoutError` | LogRow status `timeout`; matches spec #1. |
| `APIStatusError` 401 | `AuthError` | LogRow status `error`. |
| `APIStatusError` 429 | `RateLimitError` | LogRow status `error`. |
| Other `APIStatusError` | `NetworkError` | LogRow status `error`. |
| `APIConnectionError` | `NetworkError` | LogRow status `error`. |
| `MissingAPIKey` | itself | Raised pre-stream; LogRow status `error`. |
| `MissingBaseURL` | itself | Raised in `__init__` of `OpenAICompatProvider` when constructed; surfaces in Settings Refresh path as `QMessageBox`. |
| Cancellation | none | LogRow status `cancelled`. |

## 17. Testing

### Pure Python (no Qt)

- `tests/test_capability_table.py`
  - `infer_capabilities("gpt-4o")` → table hit, `inferred=False`.
  - `infer_capabilities("gpt-4o-2024-08-06")` → prefix hit, `inferred=False`.
  - `infer_capabilities("totally-new-model")` → `ASSUME_ALL_CAPS`, `inferred=True`.

- `tests/test_provider_config_models.py`
  - `ProviderConfig.cached_models` round-trips through `model_dump_json` / `model_validate_json`.
  - `ModelInfo.to_dict()` then `ModelInfo.from_dict()` reproduces the same instance.

- `tests/test_openai_compat_provider.py`
  - Construct with `base_url=None` → raises `MissingBaseURL`.
  - Construct with `base_url="http://x"` → succeeds.
  - `_BUILTIN_DEFAULTS == []`; `list_models()` returns `[]` when `cached_models` empty.

- `tests/test_openai_provider.py` (extend existing)
  - Monkeypatch `openai.OpenAI` with a fake whose `chat.completions.create` returns an iterable of fake events; assert produced `StreamChunk` sequence.
  - Fake raises `openai.APITimeoutError` → provider raises `RequestTimeoutError`.
  - Fake raises `openai.APIStatusError(status_code=401)` → `AuthError`.
  - Fake raises `openai.APIStatusError(status_code=429)` with `retry-after: 30` → `RateLimitError(retry_after=30.0)`.
  - `fetch_remote_models()` against fake `client.models.list()` returns `ModelInfo` list with capabilities from `KNOWN_MODEL_CAPS` for known IDs.

- `tests/test_anthropic_provider.py`
  - Fake `Anthropic.messages.stream()` context manager yields a hand-crafted event list; assert `system` is passed as a top-level kwarg, not as a message.
  - `assistant` role survives unmodified in `_build_messages`.
  - Image message produces `{"type":"image","source":{...}}` with base64 data matching `base64.b64encode(png).decode()`.
  - `cancel_event.set()` between chunks causes early `return`.
  - Fake raises `anthropic.APIStatusError(status_code=401)` → `AuthError`.

- `tests/test_gemini_provider.py`
  - Fake `genai.Client().models.generate_content_stream(...)` yields chunks with `text` and `usage_metadata`; assert role mapping `assistant → model` and `system_instruction` set in config.
  - `json_mode=True` → `response_mime_type="application/json"` in the config.
  - `fetch_remote_models()` filters out names containing `embed` or `aqa`.

- `tests/test_runner_capability_check.py` (extend existing `test_inference_runner.py`)
  - Inferred (unknown) model → no `MissingCapabilityError` for inspect (because `ASSUME_ALL_CAPS` includes JSON_MODE).
  - Known model lacking JSON_MODE (e.g. `"llama-3.3-70b-versatile"`) → inspect raises `MissingCapabilityError`.

### Qt (pytest-qt)

- `tests/test_model_refresh_worker.py`
  - Fake provider whose `fetch_remote_models` returns a list → `succeeded` fires with `(name, list)`.
  - Fake provider whose `fetch_remote_models` raises `AuthError` → `failed` fires with `(name, exc)`.

- `tests/test_provider_pane.py`
  - `require_base_url=True` → base_url QComboBox + QLineEdit visible.
  - `require_base_url=False` and config without base_url → base_url controls hidden.
  - Selecting a preset writes its URL into the QLineEdit.
  - `set_busy(True)` disables the Refresh button.
  - `set_model_count(5)` updates the label.

- `tests/test_settings_dialog_providers.py`
  - Open dialog → 4 nested tabs exist with names matching `registry.names()`.
  - Type into OpenAI-Compat tab's api_key + base_url and click Refresh → `ModelRefreshWorker` is constructed with a `OpenAICompatProvider` instance.
  - Simulate `succeeded` → `_config.providers["openai_compat"].cached_models` matches fake output; `ConfigStore.save` invoked once.
  - Simulate `failed` → `QMessageBox` shown; nothing written to config.
  - Click OK → `_config.providers[name]` matches every pane's `api_key_value()` / `base_url_value()`.

### Manual

1. Launch → Settings → Providers → OpenAI-Compat → select OpenRouter preset → paste OpenRouter key → Refresh. Model count updates. Click OK. Switch ProviderPicker to `openai_compat`. Run Quick Action against an OpenRouter-hosted model.
2. Anthropic tab → paste real Anthropic key → Refresh → switch to anthropic → Quick Action with screenshot → verify vision works → expand LogRow body, confirm `system` is the top-level prompt (not a message).
3. Gemini tab → real Gemini key → Refresh → switch to gemini → run Inspect → assert JSON output parses into `RunState`.
4. Set OpenAI-Compat base_url to `http://localhost:99999/v1` → Refresh → `QMessageBox` shows connection error; LogsTab appends a line. No partial write to `cached_models`.

## 18. Acceptance

- All tests in §17 pass.
- All four providers stream successfully against their respective real endpoints (manual verification).
- `cached_models` round-trips through `ConfigStore.save()` / `load()` and survives an app restart.
- `ProviderPicker` automatically lists `openai_compat` after this spec.
- Refreshing during open Settings updates the picker live (via `models_refreshed` signal).
- PyInstaller bundle builds without missing-module errors (`google-genai` and its transitive deps are present).
