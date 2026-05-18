# tests/test_inference_runner.py
import threading
from datetime import datetime, timezone
import pytest
from PySide6.QtCore import QCoreApplication

from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.core.request import QuickActionRequest
from spiresight.core.runner import InferenceRunner
from spiresight.core.run_state import Card, RunState
from spiresight.llm.capabilities import Capability
from spiresight.llm.capabilities import Capability as Cap
from spiresight.llm.errors import MissingAPIKey, MissingCapabilityError
from spiresight.llm.models import ModelInfo
from spiresight.llm.provider import StreamChunk
from spiresight.prompts.schema import QuickAction, SystemPrompt
from spiresight.ui.state.run_state_store import RunStateStore


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
    def stream(self, *, model, system, user_text="", images=(), cancel_event=None, json_mode=False, messages=None):
        if cancel_event is None:
            cancel_event = threading.Event()
        self.last_call = dict(model=model, system=system, user_text=user_text,
                              images=images, json_mode=json_mode, messages=messages)
        yield from self._chunks


class _FakeCapture:
    def grab_primary(self): return b"PNG_BYTES"


def _runner(*, provider, loader, capture=None):
    cfg = AppConfig(active_provider="openai", active_model="gpt-4o")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    return InferenceRunner(
        config=cfg,
        prompt_loader=loader,
        provider_factory=lambda name, pcfg, opts=None: provider,
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
    out = list(runner.run_quick_action(
        QuickActionRequest(prompt_id="card", custom_text="extra", include_screenshot=True),
        cancel_event=threading.Event(),
    ))
    assert "".join(c.text_delta for c in out) == "Hello world"
    assert provider.last_call["model"] == "gpt-4o"
    assert provider.last_call["system"] == "be helpful"
    assert provider.last_call["user_text"] == "Pick. extra"
    assert provider.last_call["images"] == [b"PNG_BYTES"]


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
    list(runner.run_quick_action(QuickActionRequest("x", "", include_screenshot=False),
                    cancel_event=threading.Event()))
    assert provider.last_call["images"] == []


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
        provider_factory=lambda n, p, opts=None: provider,
        screen_capture=_FakeCapture(),
    )
    with pytest.raises(MissingCapabilityError) as exc:
        list(runner.run_quick_action(
            QuickActionRequest("x", "", include_screenshot=True),
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
        provider_factory=lambda n, p, opts=None: provider, screen_capture=_FakeCapture(),
    )
    with pytest.raises(MissingAPIKey):
        list(runner.run_quick_action(QuickActionRequest("x", "", False), cancel_event=threading.Event()))


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def _stateful_runner(provider, loader, capture, store):
    cfg = AppConfig(active_provider="openai", active_model="gpt-4o")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    return InferenceRunner(
        config=cfg,
        prompt_loader=loader,
        provider_factory=lambda name, pcfg, opts=None: provider,
        screen_capture=capture,
        run_state_store=store,
    )


def test_run_appends_run_state_block_to_system_when_store_has_state(qapp):
    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="t {custom_text}", requires_screenshot=False,
                     required_capabilities=[])
    sp = SystemPrompt(id="s", description="", content="base prompt")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o", frozenset(), 128_000)],
        chunks=[StreamChunk("ok", "stop")],
    )
    store = RunStateStore()
    store.set(RunState(
        cards=[Card(name="Heavy Blade+", count=1, rarity="uncommon", usefulness="key")],
        relics=[], potions=[], archetype_candidates=[],
        overall_eval="lean strength",
        inspected_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
    ))
    runner = _stateful_runner(provider, _FakeLoader(qa, sp), _FakeCapture(), store)
    list(runner.run_quick_action(QuickActionRequest("x", "", False), cancel_event=threading.Event()))
    assert provider.last_call["system"].startswith("base prompt")
    assert "## Current Run Context" in provider.last_call["system"]
    assert "Heavy Blade+" in provider.last_call["system"]
    assert "lean strength" in provider.last_call["system"]


def test_run_leaves_system_unchanged_when_store_empty(qapp):
    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="t", requires_screenshot=False,
                     required_capabilities=[])
    sp = SystemPrompt(id="s", description="", content="base prompt")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o", frozenset(), 128_000)],
        chunks=[StreamChunk("ok", "stop")],
    )
    store = RunStateStore()  # empty
    runner = _stateful_runner(provider, _FakeLoader(qa, sp), _FakeCapture(), store)
    list(runner.run_quick_action(QuickActionRequest("x", "", False), cancel_event=threading.Event()))
    assert provider.last_call["system"] == "base prompt"


def test_run_without_store_works_unchanged():
    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="t", requires_screenshot=False,
                     required_capabilities=[])
    sp = SystemPrompt(id="s", description="", content="base prompt")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o", frozenset(), 128_000)],
        chunks=[StreamChunk("ok", "stop")],
    )
    runner = _runner(provider=provider, loader=_FakeLoader(qa, sp))  # no store
    list(runner.run_quick_action(QuickActionRequest("x", "", False), cancel_event=threading.Event()))
    assert provider.last_call["system"] == "base prompt"


def _inspect_provider(*, models, chunks):
    return _FakeProvider(models=models, chunks=chunks)


def test_inspect_buffers_chunks_parses_json_returns_run_state():
    sp = SystemPrompt(id="inspector", description="", content="emit JSON only")
    provider = _inspect_provider(
        models=[ModelInfo("gpt-4o", "gpt-4o",
                          frozenset({Cap.VISION, Cap.JSON_MODE}), 128_000)],
        chunks=[
            StreamChunk('{"cards":[{"name":"Strike","count":4,"rarity":"starter",'),
            StreamChunk('"usefulness":"skip","note":""}],"relics":[],"potions":[],'),
            StreamChunk('"archetype_candidates":[],"overall_eval":"",'),
            StreamChunk('"inspected_at":"2026-05-16T00:00:00+00:00"}', "stop"),
        ],
    )

    class _StaticLoader:
        def get_system_prompt(self, _): return sp

    cfg = AppConfig(active_provider="openai", active_model="gpt-4o")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    runner = InferenceRunner(
        config=cfg, prompt_loader=_StaticLoader(),
        provider_factory=lambda n, p, opts=None: provider, screen_capture=_FakeCapture(),
    )

    state = runner.inspect(images=[b"PNG_BYTES"], cancel_event=threading.Event())
    assert state.cards[0].name == "Strike"
    assert state.cards[0].count == 4
    assert provider.last_call["json_mode"] is True
    assert provider.last_call["images"] == [b"PNG_BYTES"]
    assert provider.last_call["system"] == "emit JSON only"


def test_inspect_raises_value_error_on_malformed_json():
    sp = SystemPrompt(id="inspector", description="", content="json please")
    provider = _inspect_provider(
        models=[ModelInfo("gpt-4o", "gpt-4o",
                          frozenset({Cap.VISION, Cap.JSON_MODE}), 128_000)],
        chunks=[StreamChunk("not json at all", "stop")],
    )

    class _StaticLoader:
        def get_system_prompt(self, _): return sp

    cfg = AppConfig(active_provider="openai", active_model="gpt-4o")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    runner = InferenceRunner(
        config=cfg, prompt_loader=_StaticLoader(),
        provider_factory=lambda n, p, opts=None: provider, screen_capture=_FakeCapture(),
    )

    with pytest.raises(ValueError):
        runner.inspect(images=[b"PNG_BYTES"], cancel_event=threading.Event())


def test_inspect_raises_missing_capability_when_model_lacks_json_mode():
    sp = SystemPrompt(id="inspector", description="", content="json")
    provider = _inspect_provider(
        models=[ModelInfo("o3", "o3",
                          frozenset({Cap.VISION}), 200_000)],  # no JSON_MODE
        chunks=[],
    )

    class _StaticLoader:
        def get_system_prompt(self, _): return sp

    cfg = AppConfig(active_provider="openai", active_model="o3")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    runner = InferenceRunner(
        config=cfg, prompt_loader=_StaticLoader(),
        provider_factory=lambda n, p, opts=None: provider, screen_capture=_FakeCapture(),
    )

    with pytest.raises(MissingCapabilityError) as exc:
        runner.inspect(images=[b"PNG_BYTES"], cancel_event=threading.Event())
    assert Cap.JSON_MODE in exc.value.missing
    assert Cap.VISION not in exc.value.missing  # model has VISION


def test_inspect_with_multiple_frames_passes_all_to_provider():
    sp = SystemPrompt(id="inspector", description="", content="emit JSON only")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o",
                          frozenset({Cap.VISION, Cap.JSON_MODE}), 128_000)],
        chunks=[
            StreamChunk('{"cards":[],"relics":[],"potions":[],'),
            StreamChunk('"archetype_candidates":[],"overall_eval":"",'),
            StreamChunk('"inspected_at":"2026-05-16T00:00:00+00:00"}', "stop"),
        ],
    )

    class _StaticLoader:
        def get_system_prompt(self, _): return sp

    cfg = AppConfig(active_provider="openai", active_model="gpt-4o")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    runner = InferenceRunner(
        config=cfg, prompt_loader=_StaticLoader(),
        provider_factory=lambda n, p, opts=None: provider, screen_capture=_FakeCapture(),
    )

    state = runner.inspect(
        images=[b"PNG_A", b"PNG_B", b"PNG_C"],
        cancel_event=threading.Event(),
    )
    assert state.cards == []
    assert provider.last_call["images"] == [b"PNG_A", b"PNG_B", b"PNG_C"]


def test_inspect_with_no_frames_raises_value_error():
    sp = SystemPrompt(id="inspector", description="", content="json")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o",
                          frozenset({Cap.VISION, Cap.JSON_MODE}), 128_000)],
        chunks=[],
    )

    class _StaticLoader:
        def get_system_prompt(self, _): return sp

    cfg = AppConfig(active_provider="openai", active_model="gpt-4o")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    runner = InferenceRunner(
        config=cfg, prompt_loader=_StaticLoader(),
        provider_factory=lambda n, p, opts=None: provider, screen_capture=_FakeCapture(),
    )

    with pytest.raises(ValueError, match="at least one frame"):
        runner.inspect(images=[], cancel_event=threading.Event())
    assert provider.last_call is None  # provider was never called


# ---------------------------------------------------------------------------
# run_follow_up tests
# ---------------------------------------------------------------------------

def test_run_follow_up_uses_guard_prompt_and_messages():
    from spiresight.core.messages import Message
    from spiresight.core.request import FollowUpRequest

    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="t", requires_screenshot=False,
                     required_capabilities=[])
    sp = SystemPrompt(id="s", description="", content="base prompt")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o", frozenset(), 128_000)],
        chunks=[StreamChunk("follow-up reply", "stop")],
    )
    runner = _runner(provider=provider, loader=_FakeLoader(qa, sp))

    history = (
        Message(role="user", text="what should I pick?"),
        Message(role="assistant", text="pick Bash"),
    )
    req = FollowUpRequest(user_text="why Bash?", recapture=False)
    out = list(runner.run_follow_up(req, history, cancel_event=threading.Event()))

    assert "".join(c.text_delta for c in out) == "follow-up reply"
    assert provider.last_call is not None
    # Guard prompt must not contain the base prompt
    assert "base prompt" not in provider.last_call["system"]
    assert "conversation" in provider.last_call["system"].lower()
    # Must pass messages, not user_text
    assert provider.last_call["messages"] is not None
    assert provider.last_call.get("user_text", "") == ""
    # Messages should have 3 entries: 2 from history + 1 new user msg
    assert len(provider.last_call["messages"]) == 3
    assert provider.last_call["messages"][2].role == "user"
    assert provider.last_call["messages"][2].text == "why Bash?"


def test_run_follow_up_recapture_grabs_new_screenshot():
    from spiresight.core.messages import Message
    from spiresight.core.request import FollowUpRequest

    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="t", requires_screenshot=False,
                     required_capabilities=[])
    sp = SystemPrompt(id="s", description="", content="s")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o", frozenset(), 128_000)],
        chunks=[StreamChunk("ok", "stop")],
    )
    capture = _FakeCapture()
    cfg = AppConfig(active_provider="openai", active_model="gpt-4o")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    runner = InferenceRunner(
        config=cfg, prompt_loader=_FakeLoader(qa, sp),
        provider_factory=lambda n, p, opts=None: provider, screen_capture=capture,
    )

    history = (Message(role="user", text="hi"),)
    req = FollowUpRequest(user_text="again", recapture=True)
    list(runner.run_follow_up(req, history, cancel_event=threading.Event()))

    messages = provider.last_call["messages"]
    assert messages[-1].image_png == b"PNG_BYTES"


def test_run_follow_up_reuses_screenshot_from_history():
    from spiresight.core.messages import Message
    from spiresight.core.request import FollowUpRequest

    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="t", requires_screenshot=False,
                     required_capabilities=[])
    sp = SystemPrompt(id="s", description="", content="s")
    provider = _FakeProvider(
        models=[ModelInfo("gpt-4o", "gpt-4o", frozenset(), 128_000)],
        chunks=[StreamChunk("ok", "stop")],
    )
    runner = _runner(provider=provider, loader=_FakeLoader(qa, sp))

    old_png = b"OLD_SCREENSHOT"
    history = (
        Message(role="user", text="first question", image_png=old_png),
        Message(role="assistant", text="first answer"),
    )
    req = FollowUpRequest(user_text="follow up", include_screenshot=True, recapture=False)
    list(runner.run_follow_up(req, history, cancel_event=threading.Event()))

    messages = provider.last_call["messages"]
    assert messages[-1].image_png == old_png


def test_run_follow_up_skips_capability_check():
    from spiresight.core.request import FollowUpRequest

    qa = QuickAction(id="x", label="X", system_prompt_id="s",
                     user_template="t", requires_screenshot=False,
                     required_capabilities=[])
    sp = SystemPrompt(id="s", description="", content="s")
    # Use a non-vision model — follow-up should NOT fail on capability check
    provider = _FakeProvider(
        models=[ModelInfo("gpt-3.5", "gpt-3.5", frozenset(), 16_000)],
        chunks=[StreamChunk("ok", "stop")],
    )
    cfg = AppConfig(active_provider="openai", active_model="gpt-3.5")
    cfg.providers["openai"] = ProviderConfig(api_key="sk-x")
    runner = InferenceRunner(
        config=cfg, prompt_loader=_FakeLoader(qa, sp),
        provider_factory=lambda n, p, opts=None: provider, screen_capture=_FakeCapture(),
    )
    req = FollowUpRequest(user_text="hello")
    # Should NOT raise MissingCapabilityError
    list(runner.run_follow_up(req, (), cancel_event=threading.Event()))


def test_inspect_rejects_model_without_json_mode(monkeypatch):
    """A model whose KNOWN_MODEL_CAPS entry lacks JSON_MODE must raise."""
    from spiresight.config.schema import ModelInfoDict
    from spiresight.core.runner import InferenceRunner
    from spiresight.llm.errors import MissingCapabilityError
    from spiresight.llm.models import ModelInfo
    from spiresight.llm.capabilities import Capability
    from unittest.mock import MagicMock
    import threading

    cfg = AppConfig(
        active_provider="openai_compat",
        active_model="llama-3.3-70b-versatile",
        request_timeout_seconds=60,
    )
    cfg.providers = {"openai_compat": ProviderConfig(
        api_key="k", base_url="http://x/v1",
        cached_models=[ModelInfoDict(
            id="llama-3.3-70b-versatile", display_name="L",
            capabilities=["tool_use"], context_window=8192,
        )],
    )}

    fake_provider = MagicMock()
    fake_provider.name = "openai_compat"
    fake_provider.list_models.return_value = [
        ModelInfo("llama-3.3-70b-versatile", "L", frozenset({Capability.TOOL_USE}), 8192)
    ]

    loader = MagicMock()
    loader.get_system_prompt.return_value = MagicMock(content="INSPECT-SYS")

    runner = InferenceRunner(
        config=cfg, prompt_loader=loader,
        provider_factory=lambda *a, **kw: fake_provider,
        screen_capture=MagicMock(), run_state_store=None,
    )
    with pytest.raises(MissingCapabilityError):
        runner.inspect(images=[b"\x89PNG"], cancel_event=threading.Event())
