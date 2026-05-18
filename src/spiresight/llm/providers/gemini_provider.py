from __future__ import annotations

import threading
from collections.abc import Iterator

from spiresight.config.schema import ProviderConfig
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import ProviderOptions, StreamChunk


class GeminiProvider:
    name = "gemini"

    def __init__(self, config: ProviderConfig, options: ProviderOptions | None = None) -> None:
        self._config = config
        self._options = options or ProviderOptions()

    def list_models(self) -> list[ModelInfo]:
        return []

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
        raise NotImplementedError("Gemini provider is not implemented in MVP")
