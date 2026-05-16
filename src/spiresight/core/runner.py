# src/spiresight/core/runner.py
"""Orchestrates a single inference request end-to-end.

Pure Python, no Qt. Wrapped by ui/workers/inference_worker for the
QThread-based UI integration.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from typing import Protocol

from spiresight.capture.screen import ScreenCapture
from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.core.request import InferenceRequest
from spiresight.core.run_state import RunState
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import MissingAPIKey, MissingCapabilityError
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import LLMProvider, StreamChunk
from spiresight.prompts.loader import PromptLoader

INSPECTOR_PROMPT_ID = "sts_inspector"
INSPECTOR_USER_TEXT = (
    "Extract the current run state from this screenshot. "
    "Output JSON only, matching the schema specified in the system prompt."
)
_INSPECT_CAPS = frozenset({Capability.VISION, Capability.JSON_MODE})

ProviderFactory = Callable[[str, ProviderConfig], LLMProvider]


class RunStateSource(Protocol):
    def get(self) -> RunState | None: ...


class InferenceRunner:
    def __init__(
        self,
        *,
        config: AppConfig,
        prompt_loader: PromptLoader,
        provider_factory: ProviderFactory,
        screen_capture: ScreenCapture,
        run_state_store: RunStateSource | None = None,
    ) -> None:
        self._config = config
        self._loader = prompt_loader
        self._factory = provider_factory
        self._capture = screen_capture
        self._store = run_state_store

    def _compose_system(self, base: str) -> str:
        if self._store is None:
            return base
        state = self._store.get()
        if state is None:
            return base
        return f"{base}\n\n{state.to_prompt_block()}"

    def inspect(self, *, images: list[bytes], cancel_event: threading.Event) -> RunState:
        """Send N pre-captured PNG frames to the inspector prompt, parse RunState."""
        if not images:
            raise ValueError("inspect requires at least one frame")

        sp = self._loader.get_system_prompt(INSPECTOR_PROMPT_ID)

        provider_cfg = self._config.providers.get(
            self._config.active_provider, ProviderConfig()
        )
        if not provider_cfg.api_key:
            raise MissingAPIKey(self._config.active_provider)
        provider = self._factory(self._config.active_provider, provider_cfg)

        model = self._resolve_model(provider, self._config.active_model)
        missing = _INSPECT_CAPS - set(model.capabilities)
        if missing:
            raise MissingCapabilityError(model=model.id, missing=missing)

        buffer: list[str] = []
        for chunk in provider.stream(
            model=model.id,
            system=sp.content,
            user_text=INSPECTOR_USER_TEXT,
            images=images,
            cancel_event=cancel_event,
            json_mode=True,
        ):
            if chunk.text_delta:
                buffer.append(chunk.text_delta)
            if chunk.finish_reason is not None:
                break

        raw = "".join(buffer).strip()
        try:
            return RunState.model_validate_json(raw)
        except Exception as exc:
            raise ValueError(
                f"Inspector returned unparseable JSON: {raw[:200]}"
            ) from exc

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
            system=self._compose_system(sp.content),
            user_text=user_text,
            images=[image_png] if image_png is not None else [],
            cancel_event=cancel_event,
        )

    @staticmethod
    def _resolve_model(provider: LLMProvider, model_id: str) -> ModelInfo:
        for m in provider.list_models():
            if m.id == model_id:
                return m
        raise KeyError(f"Model '{model_id}' not advertised by provider '{provider.name}'")
