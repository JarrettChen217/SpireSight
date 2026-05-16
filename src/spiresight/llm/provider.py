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
        json_mode: bool = False,
    ) -> Iterator[StreamChunk]: ...
