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
from typing import Any, Final

from openai import OpenAI, APIConnectionError, APIStatusError, APITimeoutError, RateLimitError as OpenAIRateLimitError

from spiresight.config.schema import ProviderConfig
from spiresight.llm.usage_parsing import parse_openai_usage
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
        kwargs: dict[str, Any] = {
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
                            usage=parse_openai_usage(event.usage),
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
