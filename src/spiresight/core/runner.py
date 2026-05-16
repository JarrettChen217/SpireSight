# src/spiresight/core/runner.py
"""Orchestrates a single inference request end-to-end.

Pure Python, no Qt. Wrapped by ui/workers/inference_worker for the
QThread-based UI integration.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Iterator

from spiresight.capture.screen import ScreenCapture
from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.core.request import InferenceRequest
from spiresight.llm.errors import MissingAPIKey, MissingCapabilityError
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import LLMProvider, StreamChunk
from spiresight.prompts.loader import PromptLoader

ProviderFactory = Callable[[str, ProviderConfig], LLMProvider]


class InferenceRunner:
    def __init__(
        self,
        *,
        config: AppConfig,
        prompt_loader: PromptLoader,
        provider_factory: ProviderFactory,
        screen_capture: ScreenCapture,
    ) -> None:
        self._config = config
        self._loader = prompt_loader
        self._factory = provider_factory
        self._capture = screen_capture

    def run(
        self,
        request: InferenceRequest,
        *,
        cancel_event: threading.Event,
    ) -> Iterator[StreamChunk]:
        qa = self._loader.get_quick_action(request.prompt_id)
        sp = self._loader.get_system_prompt(qa.system_prompt_id)
        user_text = qa.user_template.format(custom_text=request.custom_text or "")

        provider_cfg = self._config.providers.get(
            self._config.active_provider, ProviderConfig()
        )
        if not provider_cfg.api_key:
            raise MissingAPIKey(self._config.active_provider)
        provider = self._factory(self._config.active_provider, provider_cfg)

        model = self._resolve_model(provider, self._config.active_model)
        missing = set(qa.required_capabilities) - set(model.capabilities)
        if missing:
            raise MissingCapabilityError(model=model.id, missing=missing)

        image_png: bytes | None = None
        if qa.requires_screenshot and request.include_screenshot:
            image_png = self._capture.grab_primary()

        yield from provider.stream(
            model=model.id,
            system=sp.content,
            user_text=user_text,
            image_png=image_png,
            cancel_event=cancel_event,
        )

    @staticmethod
    def _resolve_model(provider: LLMProvider, model_id: str) -> ModelInfo:
        for m in provider.list_models():
            if m.id == model_id:
                return m
        raise KeyError(f"Model '{model_id}' not advertised by provider '{provider.name}'")
