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

    def stream(
        self,
        *,
        model: str,
        system: str,
        user_text: str,
        image_png: bytes | None,
        cancel_event: threading.Event,
        json_mode: bool = False,
    ) -> Iterator[StreamChunk]:
        raise NotImplementedError("Anthropic provider is not implemented in MVP")
