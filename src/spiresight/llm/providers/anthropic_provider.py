"""Anthropic streaming provider via the official anthropic SDK."""
from __future__ import annotations

import base64
import threading
from collections.abc import Iterator
from typing import Any, Final

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

    def __init__(self, config: ProviderConfig, options: ProviderOptions | None = None) -> None:
        self._config = config
        self._options = options or ProviderOptions()
        self._client = Anthropic(
            api_key=config.api_key or "missing",
            base_url=config.base_url,
            timeout=float(self._options.request_timeout_seconds),
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
        kwargs: dict[str, Any] = {
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
                    if event.type == "content_block_delta" and getattr(event.delta, "type", "") == "text_delta":
                        yield StreamChunk(text_delta=event.delta.text, finish_reason=None, usage=None)  # type: ignore[union-attr]
                    elif event.type == "message_stop":
                        snap = getattr(stream, "current_message_snapshot", None)
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
