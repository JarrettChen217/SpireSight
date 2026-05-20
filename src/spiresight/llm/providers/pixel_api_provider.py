"""PixelAPI-(OpenAI) provider — third-party relay at pixel.try-chatapi.com.

This relay's chat.completions endpoint dumps every request into a ~76-second
buffer queue, so OpenAIProvider (which speaks chat.completions) is unusable
against it. The relay's Responses API endpoint streams in real time, so this
provider speaks the Responses API exclusively.

Other characteristics observed on the relay:
  - `reasoning_effort` is silently ignored upstream
  - JSON mode via `text={"format": {"type": "json_object"}}` returns valid JSON
  - Image input (data URI) is forwarded to upstream OpenAI without breaking the
    fast path
"""
from __future__ import annotations

import base64
import logging
import threading
import time
from collections.abc import Iterator
from typing import Any, Final

from openai import (
    OpenAI, APIConnectionError, APIStatusError, APITimeoutError,
    RateLimitError as OpenAIRateLimitError,
)

from spiresight.config.schema import ProviderConfig
from spiresight.llm.usage_parsing import parse_openai_usage
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import (
    AuthError, MissingAPIKey, NetworkError, RateLimitError, RequestTimeoutError,
)
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import ProviderOptions, StreamChunk

_log = logging.getLogger(__name__)


PIXEL_API_BASE_URL: Final[str] = "http://pixel.try-chatapi.com/v1"


def _estimate_input_chars(api_input: Any) -> int:
    """Rough char count of the `input` payload (text + base64 image data)."""
    if isinstance(api_input, str):
        return len(api_input)
    total = 0
    if isinstance(api_input, list):
        for msg in api_input:
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, str):
                total += len(content)
            elif isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if "text" in part:
                        total += len(part["text"])
                    if "image_url" in part:
                        url = part["image_url"]
                        total += len(url) if isinstance(url, str) else 0
    return total


# Hardcoded from `GET /v1/models` on the relay. The relay puts /v1/models on a
# slow path (~76s), so we ship a known list rather than fetch on demand.
_ALL_CAPS = frozenset({
    Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING,
})

_BUILTIN_DEFAULTS: Final[list[ModelInfo]] = [
    ModelInfo("gpt-5.5",                "GPT-5.5",                _ALL_CAPS, 0),
    ModelInfo("gpt-5.4",                "GPT-5.4",                _ALL_CAPS, 0),
    ModelInfo("gpt-5.4-mini",           "GPT-5.4 mini",           _ALL_CAPS, 0),
    ModelInfo("gpt-5.4-2026-03-05",     "GPT-5.4 (2026-03-05)",   _ALL_CAPS, 0),
    ModelInfo("gpt-5.3-codex",          "GPT-5.3 codex",          _ALL_CAPS, 0),
    ModelInfo("gpt-5.3-codex-spark",    "GPT-5.3 codex spark",    _ALL_CAPS, 0),
    ModelInfo("gpt-5.2",                "GPT-5.2",                _ALL_CAPS, 0),
    ModelInfo("gpt-5.2-chat-latest",    "GPT-5.2 chat-latest",    _ALL_CAPS, 0),
    ModelInfo("gpt-5.2-pro",            "GPT-5.2 pro",            _ALL_CAPS, 0),
    ModelInfo("gpt-5.2-pro-2025-12-11", "GPT-5.2 pro (2025-12-11)", _ALL_CAPS, 0),
    ModelInfo("gpt-5.2-2025-12-11",     "GPT-5.2 (2025-12-11)",   _ALL_CAPS, 0),
]


class PixelApiProvider:
    """PixelAPI-(OpenAI) — relay via OpenAI Responses API streaming."""
    name = "pixel_api"
    display_name = "PixelAPI-(OpenAI)"
    _DEFAULT_BASE: Final[str] = PIXEL_API_BASE_URL
    _BUILTIN_DEFAULTS: list[ModelInfo] = _BUILTIN_DEFAULTS

    def __init__(self, config: ProviderConfig, options: ProviderOptions | None = None) -> None:
        self._config = config
        self._options = options or ProviderOptions()
        base = config.base_url or self._DEFAULT_BASE
        self._client = OpenAI(
            api_key=config.api_key or "missing",
            base_url=base,
            timeout=float(self._options.request_timeout_seconds),
            max_retries=0,
        )

    def list_models(self) -> list[ModelInfo]:
        if self._config.cached_models:
            return [ModelInfo.from_dict(m) for m in self._config.cached_models]
        return list(self._BUILTIN_DEFAULTS)

    def fetch_remote_models(self) -> list[ModelInfo]:
        # NOTE: the relay puts GET /v1/models on a ~76s slow path, so we never
        # hit it. Return the builtin list — users can still type custom model ids
        # if the relay adds new ones.
        return list(self._BUILTIN_DEFAULTS)

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

        t0 = time.monotonic()
        def _t() -> str:
            return f"T+{time.monotonic() - t0:6.3f}s"

        n_msgs = len(messages) if messages is not None else 0
        n_imgs = len(images) if images else 0
        _log.info(
            "%s pixel_api.stream entered  model=%s json_mode=%s images=%d messages=%d system_len=%d",
            _t(), model, json_mode, n_imgs, n_msgs, len(system or ""),
        )

        # IMPORTANT: the relay's fast path only fires for the simplest input
        # shapes. Structured `input=[{role, content: [parts]}]` consistently
        # routes to a ~76s slow queue even when there are no images. So we use
        # plain-string `input=user_text` whenever possible, and only fall back
        # to the structured form when images or conversation history are present.
        api_input: Any
        if messages is not None:
            api_input = self._build_input_from_messages(messages)
            input_kind = "structured(history)"
        elif images:
            api_input = [{
                "role": "user",
                "content": self._build_user_content(user_text, images),
            }]
            input_kind = "structured(image)"
        else:
            api_input = user_text
            input_kind = "string"

        kwargs: dict[str, Any] = {
            "model": model,
            "input": api_input,
        }
        # Only set instructions when non-empty — empty `instructions=""` has
        # been observed to add noticeable latency on this relay.
        if system:
            kwargs["instructions"] = system
        if json_mode:
            # The relay's upstream returns 502 for `{"type": "json_object"}` on
            # every Responses API call we've seen. `json_schema` with a
            # permissive any-object schema works. Don't switch back without
            # re-testing against this specific relay.
            kwargs["text"] = {"format": {
                "type": "json_schema",
                "name": "response",
                "schema": {"type": "object", "additionalProperties": True},
                "strict": False,
            }}

        # Estimate request body size for visibility — useful when chasing slow
        # paths caused by large/duplicated payloads.
        body_chars = _estimate_input_chars(api_input) + len(system or "")
        _log.info(
            "%s pixel_api.stream input_kind=%s body_chars≈%d  → calling responses.stream()",
            _t(), input_kind, body_chars,
        )

        try:
            with self._client.responses.stream(**kwargs) as stream:
                first_event_logged = False
                first_delta_logged = False
                for event in stream:
                    if cancel_event.is_set():
                        _log.info("%s pixel_api.stream cancelled", _t())
                        return
                    etype = getattr(event, "type", "")
                    if not first_event_logged:
                        _log.info("%s pixel_api.stream first event  type=%s", _t(), etype)
                        first_event_logged = True
                    if etype == "response.output_text.delta":
                        if not first_delta_logged:
                            _log.info("%s pixel_api.stream first text delta (TTFT)", _t())
                            first_delta_logged = True
                        yield StreamChunk(
                            text_delta=getattr(event, "delta", "") or "",
                            finish_reason=None,
                            usage=None,
                        )
                    elif etype == "response.completed":
                        resp = getattr(event, "response", None)
                        usage = getattr(resp, "usage", None) if resp is not None else None
                        parsed = parse_openai_usage(usage) if usage else None
                        _log.info(
                            "%s pixel_api.stream completed  in_tokens=%s cached=%s out_tokens=%s",
                            _t(),
                            parsed.input_tokens if parsed else "?",
                            parsed.cached_tokens if parsed else "?",
                            parsed.output_tokens if parsed else "?",
                        )
                        yield StreamChunk(
                            text_delta="",
                            finish_reason="stop",
                            usage=parsed,
                        )
        except APITimeoutError as exc:
            raise RequestTimeoutError(
                f"Request exceeded {self._options.request_timeout_seconds}s timeout"
            ) from exc
        except OpenAIRateLimitError as exc:
            retry = exc.response.headers.get("retry-after") if getattr(exc, "response", None) else None
            raise RateLimitError(float(retry) if retry else None) from exc
        except APIStatusError as exc:
            if exc.status_code == 401:
                raise AuthError("Invalid PixelAPI key") from exc
            if exc.status_code == 429:
                raise RateLimitError() from exc
            raise NetworkError(f"HTTP {exc.status_code}: {exc}") from exc
        except APIConnectionError as exc:
            raise NetworkError(str(exc)) from exc

    @staticmethod
    def _build_user_content(text: str, images: list[bytes]) -> list[dict]:
        parts: list[dict] = [{"type": "input_text", "text": text}]
        for png in images:
            b64 = base64.b64encode(png).decode()
            parts.append({
                "type": "input_image",
                "image_url": f"data:image/png;base64,{b64}",
            })
        return parts

    @staticmethod
    def _build_input_from_messages(messages: list) -> list[dict]:
        """Build Responses API `input` from conversation history.

        System messages are dropped here — `instructions=` carries the system prompt.
        """
        result: list[dict] = []
        for m in messages:
            if m.role == "user":
                content: list[dict] = [{"type": "input_text", "text": m.text}]
                if m.image_png is not None:
                    b64 = base64.b64encode(m.image_png).decode()
                    content.append({
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{b64}",
                    })
                result.append({"role": "user", "content": content})
            elif m.role == "assistant":
                result.append({
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": m.text}],
                })
        return result
