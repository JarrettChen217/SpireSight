# src/spiresight/llm/provider.py
from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from spiresight.core.usage import TokenUsage
from .models import ModelInfo


@dataclass
class StreamChunk:
    text_delta: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def list_models(self) -> list[ModelInfo]: ...

    def stream(
        self,
        *,
        model: str,
        system: str,
        user_text: str = "",
        images: list[bytes] = (),  # type: ignore[assignment]
        messages: list | None = None,   # list[Message], deferred import
        cancel_event: threading.Event = None,  # type: ignore[assignment]
        json_mode: bool = False,
    ) -> Iterator[StreamChunk]: ...
