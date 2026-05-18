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

    def __init__(self, config: ProviderConfig, options: ProviderOptions | None = None) -> None:
        self._config = config
        self._options = options or ProviderOptions()
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
        raw_parts: list = [{"text": user_text}]
        for png in images:
            raw_parts.append(genai_types.Part.from_bytes(data=png, mime_type="image/png"))
        return [{"role": "user", "parts": raw_parts}]
