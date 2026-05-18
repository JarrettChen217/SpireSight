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
from spiresight.core.usage import TokenUsage
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import AuthError, MissingAPIKey, NetworkError, RateLimitError
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import StreamChunk

_DEFAULT_BASE: Final = "https://api.openai.com/v1"

_MODELS: Final = [
    ModelInfo("gpt-5.5", "GPT-5.5",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING}),
              context_window=128_000),
    ModelInfo("gpt-5.4", "GPT-5.4",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING}),
              context_window=128_000),
    ModelInfo("gpt-5.2", "GPT-5.2",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING}),
              context_window=128_000),
    ModelInfo("gpt-5.1", "GPT-5.1",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING}),
              context_window=128_000),
    ModelInfo("gpt-5", "GPT-5",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING}),
              context_window=128_000),
    ModelInfo("o4-mini", "o4-mini",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.THINKING}),
              context_window=200_000),
    ModelInfo("o3", "o3",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.THINKING}),
              context_window=200_000),
    ModelInfo("gpt-4.5", "GPT-4.5",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE}),
              context_window=128_000),
    ModelInfo("gpt-4.1", "GPT-4.1",
              frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE}),
              context_window=128_000),
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
        images: list[bytes],
        cancel_event: threading.Event,
        json_mode: bool = False,
    ) -> Iterator[StreamChunk]:
        if not self._config.api_key:
            raise MissingAPIKey(self.name)

        base_url = (self._config.base_url or _DEFAULT_BASE).rstrip("/")
        url = f"{base_url}/chat/completions"
        payload = {
            "model": model,
            "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": self._build_user_content(user_text, images)},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
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

            # Usage block arrives in a trailing chunk whose `choices` is empty.
            # When `stream_options.include_usage` is true, OpenAI sends one such
            # chunk after the finish_reason chunk. We always yield it as a
            # standalone StreamChunk so the caller can attribute totals.
            usage_obj = obj.get("usage")
            if usage_obj:
                yield StreamChunk(
                    text_delta="",
                    finish_reason=None,
                    usage=TokenUsage(
                        input_tokens=int(usage_obj.get("prompt_tokens", 0)),
                        output_tokens=int(usage_obj.get("completion_tokens", 0)),
                    ),
                )

            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            finish = choices[0].get("finish_reason")
            text = delta.get("content") or ""
            if text or finish:
                yield StreamChunk(text_delta=text, finish_reason=finish)
