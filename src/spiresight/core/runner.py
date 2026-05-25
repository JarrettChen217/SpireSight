# src/spiresight/core/runner.py
"""Orchestrates a single inference request end-to-end.

Pure Python, no Qt. Wrapped by ui/workers/inference_worker for the
QThread-based UI integration.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.core.message_composer import (
    apply_image_policy,
    compose_follow_up_system,
    resolve_follow_up_image,
)
from spiresight.core.messages import Message
from spiresight.core.request import FollowUpRequest, QuickActionRequest
from spiresight.core.run_state import RunState
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import MissingAPIKey, MissingCapabilityError
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import LLMProvider, ProviderOptions, StreamChunk
from spiresight.knowledge.gateway import KnowledgeGateway
from spiresight.prompts.loader import PromptLoader

_log = logging.getLogger(__name__)

INSPECTOR_PROMPT_ID = "sts_inspector"
INSPECTOR_USER_TEXT = (
    "Extract the current run state from this screenshot. "
    "Output JSON only, matching the schema specified in the system prompt."
)
_INSPECT_CAPS = frozenset({Capability.VISION, Capability.JSON_MODE})


def _load_prompt_file(name: str, *, fallback: str) -> str:
    """Locate prompts/<name> relative to the repo root."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "prompts" / name
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()
    return fallback


def _load_guard_prompt() -> str:
    return _load_prompt_file(
        "guard.txt",
        fallback=(
            "You are continuing a previous conversation. "
            "Rely on prior assistant messages for context. "
            "If you lack needed information, say so explicitly."
        ),
    )


def _load_freeform_prompt() -> str:
    return _load_prompt_file(
        "freeform.txt",
        fallback=(
            "You are a Slay the Spire 2 strategy assistant. "
            "Answer using the user's message and any screenshot provided."
        ),
    )


ProviderFactory = Callable[[str, ProviderConfig, ProviderOptions], LLMProvider]


@dataclass(frozen=True)
class RequestSnapshot:
    provider: str
    model: str
    system: str
    messages: tuple[Message, ...]
    params: dict[str, object]


class CaptureSource(Protocol):
    def grab_primary(self) -> bytes: ...


class RunStateSource(Protocol):
    def get(self) -> RunState | None: ...


class InferenceRunner:
    def __init__(
        self,
        *,
        config: AppConfig,
        prompt_loader: PromptLoader,
        provider_factory: ProviderFactory,
        screen_capture: CaptureSource,
        run_state_store: RunStateSource | None = None,
        knowledge_gateway: KnowledgeGateway | None = None,
    ) -> None:
        self._config = config
        self._loader = prompt_loader
        self._factory = provider_factory
        self._capture = screen_capture
        self._store = run_state_store
        self._knowledge_gateway = knowledge_gateway

    def _compose_system(self, base: str) -> str:
        if self._store is None:
            return base
        state = self._store.get()
        if state is None:
            return base
        return f"{base}\n\n{state.to_prompt_block()}"

    def _get_provider_and_model(self):
        provider_cfg = self._config.providers.get(
            self._config.active_provider, ProviderConfig()
        )
        if not provider_cfg.api_key:
            raise MissingAPIKey(self._config.active_provider)
        options = ProviderOptions(
            request_timeout_seconds=self._config.request_timeout_seconds,
        )
        provider = self._factory(self._config.active_provider, provider_cfg, options)
        model = self._resolve_model(provider, self._config.active_model)
        return provider, model

    # ── snapshot methods ────────────────────────────────────────────────────

    def snapshot_quick_action(
        self,
        request: QuickActionRequest,
        *,
        history: tuple[Message, ...] = (),
    ) -> RequestSnapshot:
        qa = self._loader.get_quick_action(request.prompt_id)
        sp = self._loader.get_system_prompt(qa.system_prompt_id)
        user_text = qa.user_template.format(custom_text=request.custom_text or "")
        image_png: bytes | None = None
        if qa.requires_screenshot and request.include_screenshot:
            image_png = self._capture.grab_primary()
        user_msg = Message(role="user", text=user_text, image_png=image_png)
        messages = (*history, user_msg) if history else (user_msg,)
        provider, model = self._get_provider_and_model()
        system = self._compose_system(sp.content)
        knowledge_params: dict[str, object] = {
            "knowledge_gateway": self._config.knowledge_gateway_mode,
            "knowledge_injected": False,
            "knowledge_status": "skipped",
            "knowledge_hits": [],
        }
        if self._knowledge_gateway is not None:
            result = self._knowledge_gateway.evaluate(
                action_id=qa.id,
                mode=self._config.knowledge_gateway_mode,
                user_text=user_text,
            )
            knowledge_params.update(
                {
                    "knowledge_injected": result.injected,
                    "knowledge_status": result.status,
                    "knowledge_hits": result.hits,
                }
            )
            if result.injected:
                system = f"{system}\n\n{result.prompt_block}"
        return RequestSnapshot(
            provider=provider.name,
            model=model.id,
            system=system,
            messages=messages,
            params={
                "json_mode": False,
                "has_images": image_png is not None,
                **knowledge_params,
            },
        )

    def snapshot_follow_up(
        self,
        request: FollowUpRequest,
        history: tuple[Message, ...],
    ) -> RequestSnapshot:
        system_base = (
            _load_freeform_prompt() if not history else _load_guard_prompt()
        )
        capture_primary = self._capture.grab_primary() if request.recapture else None
        image_png = resolve_follow_up_image(
            request, history, capture_primary=capture_primary,
        )
        user_msg = Message(role="user", text=request.user_text, image_png=image_png)
        messages = apply_image_policy(self._config.image_policy, history, user_msg)
        run_state = self._store.get() if self._store is not None else None
        system = compose_follow_up_system(system_base, run_state)
        provider, model = self._get_provider_and_model()
        has_images = any(m.image_png is not None for m in messages)
        return RequestSnapshot(
            provider=provider.name,
            model=model.id,
            system=system,
            messages=messages,
            params={"json_mode": False, "has_images": has_images},
        )

    def snapshot_inspect(self, images: list[bytes]) -> RequestSnapshot:
        if not images:
            raise ValueError("inspect requires at least one frame")
        sp = self._loader.get_system_prompt(INSPECTOR_PROMPT_ID)
        provider, model = self._get_provider_and_model()
        msgs = tuple(
            Message(role="user", text=INSPECTOR_USER_TEXT, image_png=img) for img in images
        )
        return RequestSnapshot(
            provider=provider.name,
            model=model.id,
            system=sp.content,
            messages=msgs,
            params={"json_mode": True, "has_images": True, "image_count": len(images)},
        )

    # ── run methods ─────────────────────────────────────────────────────────

    def inspect(self, *, images: list[bytes], cancel_event: threading.Event) -> RunState:
        """Send N pre-captured PNG frames to the inspector prompt, parse RunState."""
        snap = self.snapshot_inspect(images)
        provider, model = self._get_provider_and_model()
        missing = _INSPECT_CAPS - set(model.capabilities)
        if missing:
            raise MissingCapabilityError(model=model.id, missing=set(missing))

        buffer: list[str] = []
        for chunk in provider.stream(
            model=snap.model,
            system=snap.system,
            user_text=INSPECTOR_USER_TEXT,
            images=[m.image_png for m in snap.messages if m.image_png is not None],
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

    def run_quick_action(
        self,
        request: QuickActionRequest,
        *,
        cancel_event: threading.Event,
    ) -> Iterator[StreamChunk]:
        t0 = time.monotonic()
        _log.info("run_quick_action: snapshotting (prompt_id=%s)", request.prompt_id)
        snap = self.snapshot_quick_action(request)
        provider, model = self._get_provider_and_model()
        qa = self._loader.get_quick_action(request.prompt_id)
        missing = set(qa.required_capabilities) - set(model.capabilities)
        if missing:
            raise MissingCapabilityError(model=model.id, missing=missing)
        msg = snap.messages[0]
        _log.info(
            "run_quick_action: T+%.3fs calling provider %s.stream  model=%s json=%s has_image=%s",
            time.monotonic() - t0, provider.name, snap.model,
            snap.params.get("json_mode", False), msg.image_png is not None,
        )
        yield from provider.stream(
            model=snap.model,
            system=snap.system,
            user_text=msg.text,
            images=[msg.image_png] if msg.image_png is not None else [],
            cancel_event=cancel_event,
            json_mode=snap.params.get("json_mode", False),
        )

    def run_follow_up(
        self,
        request: FollowUpRequest,
        history: tuple[Message, ...],
        *,
        cancel_event: threading.Event,
    ) -> Iterator[StreamChunk]:
        t0 = time.monotonic()
        _log.info(
            "run_follow_up: snapshotting (history=%d, recapture=%s, include_screenshot=%s)",
            len(history), request.recapture, request.include_screenshot,
        )
        snap = self.snapshot_follow_up(request, history)
        provider, _ = self._get_provider_and_model()
        n_imgs = sum(1 for m in snap.messages if m.image_png is not None)
        _log.info(
            "run_follow_up: T+%.3fs calling provider %s.stream  model=%s msgs=%d msgs_with_image=%d",
            time.monotonic() - t0, provider.name, snap.model,
            len(snap.messages), n_imgs,
        )
        yield from provider.stream(
            model=snap.model,
            system=snap.system,
            messages=list(snap.messages),
            cancel_event=cancel_event,
        )

    @staticmethod
    def _resolve_model(provider: LLMProvider, model_id: str) -> ModelInfo:
        for m in provider.list_models():
            if m.id == model_id:
                return m
        raise KeyError(f"Model '{model_id}' not advertised by provider '{provider.name}'")
