# tests/test_inference_runner.py
import threading
import pytest

from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.core.request import InferenceRequest
from spiresight.core.runner import InferenceRunner
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import MissingAPIKey, MissingCapabilityError
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import StreamChunk
from spiresight.prompts.schema import QuickAction, SystemPrompt


class _FakeLoader:
    def __init__(self, qa, sp):
        self._qa, self._sp = qa, sp
    def get_quick_action(self, _): return self._qa
    def get_system_prompt(self, _): return self._sp


class _FakeProvider:
    name = "openai"
    def __init__(self, models, chunks):
        self._models = models
        self._chunks = chunks
        self.last_call: dict | None = None
    def list_models(self): return self._models
    def stream(self, *, model, system, user_text, image_png, cancel_event):
        self.last_call = dict(model=model, system=system, user_text=user_text,
                              image_png=image_png)
        yield from self._chunks


class _FakeCapture:
    def grab_primary(self): return b"PNG_BYTES"


def _runner(*, provider, loader, capture=None):
    cfg = AppConfig(active_provider="openai", active_model="gpt-4o")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    return InferenceRunner(
        config=cfg,
        prompt_loader=loader,
        provider_factory=lambda name, pcfg: provider,
        screen_capture=capture or _FakeCapture(),
    )


def test_run_streams_text_with_image_when_required():
    qa = QuickAction(id="card", label="Cards", system_prompt_id="s",
                     user_template="Pick. {custom_text}",
                     requires_screenshot=True,
                     required_capabilities=[Capability.VISION])
    sp = SystemPrompt(id="s", description="", content="be helpful")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o", frozenset({Capability.VISION}), 128_000)],
        chunks=[StreamChunk("Hello"), StreamChunk(" world", "stop")],
    )
    runner = _runner(provider=provider, loader=_FakeLoader(qa, sp))
    out = list(runner.run(
        InferenceRequest(prompt_id="card", custom_text="extra", include_screenshot=True),
        cancel_event=threading.Event(),
    ))
    assert "".join(c.text_delta for c in out) == "Hello world"
    assert provider.last_call["model"] == "gpt-4o"
    assert provider.last_call["system"] == "be helpful"
    assert provider.last_call["user_text"] == "Pick. extra"
    assert provider.last_call["image_png"] == b"PNG_BYTES"


def test_run_omits_image_when_screenshot_unchecked():
    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="just text {custom_text}",
                     requires_screenshot=True,
                     required_capabilities=[])
    sp = SystemPrompt(id="s", description="", content="s")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o", frozenset(), 128_000)],
        chunks=[StreamChunk("ok", "stop")],
    )
    runner = _runner(provider=provider, loader=_FakeLoader(qa, sp))
    list(runner.run(InferenceRequest("x", "", include_screenshot=False),
                    cancel_event=threading.Event()))
    assert provider.last_call["image_png"] is None


def test_capability_pre_flight_blocks_non_vision_model():
    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="t",
                     requires_screenshot=True,
                     required_capabilities=[Capability.VISION])
    sp = SystemPrompt(id="s", description="", content="s")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-3.5", "gpt-3.5", frozenset(), 16_000)],
        chunks=[],
    )
    cfg = AppConfig(active_provider="openai", active_model="gpt-3.5")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    runner = InferenceRunner(
        config=cfg,
        prompt_loader=_FakeLoader(qa, sp),
        provider_factory=lambda n, p: provider,
        screen_capture=_FakeCapture(),
    )
    with pytest.raises(MissingCapabilityError) as exc:
        list(runner.run(
            InferenceRequest("x", "", include_screenshot=True),
            cancel_event=threading.Event(),
        ))
    assert exc.value.missing == {Capability.VISION}


def test_missing_api_key_raises():
    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="t", requires_screenshot=False,
                     required_capabilities=[])
    sp = SystemPrompt(id="s", description="", content="s")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o", frozenset(), 128_000)],
        chunks=[],
    )
    cfg = AppConfig(active_provider="openai", active_model="gpt-4o")
    cfg.providers["openai"] = ProviderConfig(api_key="")
    runner = InferenceRunner(
        config=cfg, prompt_loader=_FakeLoader(qa, sp),
        provider_factory=lambda n, p: provider, screen_capture=_FakeCapture(),
    )
    with pytest.raises(MissingAPIKey):
        list(runner.run(InferenceRequest("x", "", False), cancel_event=threading.Event()))
