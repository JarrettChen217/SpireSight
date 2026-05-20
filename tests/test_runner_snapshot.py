from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.core.messages import Message
from spiresight.core.request import FollowUpRequest, QuickActionRequest
from spiresight.core.runner import InferenceRunner, RequestSnapshot
from spiresight.llm.models import ModelInfo
from spiresight.llm.capabilities import Capability


@pytest.fixture
def runner():
    cfg = AppConfig(active_provider="openai", active_model="gpt-4o", request_timeout_seconds=60)
    cfg.providers = {"openai": ProviderConfig(api_key="sk-x")}

    loader = MagicMock()
    loader.get_quick_action.return_value = MagicMock(
        system_prompt_id="sts_helper",
        user_template="Help with {custom_text}",
        requires_screenshot=False,
        required_capabilities=frozenset(),
    )
    loader.get_system_prompt.return_value = MagicMock(content="SYS BASE")

    fake_provider = MagicMock()
    fake_provider.name = "openai"
    fake_provider.list_models.return_value = [
        ModelInfo("gpt-4o", "GPT-4o", frozenset({Capability.VISION, Capability.JSON_MODE}), context_window=128_000)
    ]
    factory = MagicMock(return_value=fake_provider)

    capture = MagicMock()
    capture.grab_primary.return_value = b"\x89PNG\r\n\x1a\n"

    return InferenceRunner(
        config=cfg,
        prompt_loader=loader,
        provider_factory=factory,
        screen_capture=capture,
        run_state_store=None,
    )


def test_snapshot_quick_action_basic(runner):
    req = QuickActionRequest(prompt_id="explain", custom_text="this", include_screenshot=False)
    snap = runner.snapshot_quick_action(req)
    assert isinstance(snap, RequestSnapshot)
    assert snap.provider == "openai"
    assert snap.model == "gpt-4o"
    assert snap.system == "SYS BASE"
    assert len(snap.messages) == 1
    assert snap.messages[0].role == "user"
    assert snap.messages[0].text == "Help with this"


def test_snapshot_quick_action_with_history(runner):
    hist = (
        Message(role="user", text="earlier", image_png=None),
        Message(role="assistant", text="reply", image_png=None),
    )
    req = QuickActionRequest(prompt_id="explain", custom_text="now", include_screenshot=False)
    snap = runner.snapshot_quick_action(req, history=hist)
    assert len(snap.messages) == 3
    assert snap.messages[-1].text == "Help with now"
    assert snap.system == "SYS BASE"


def test_snapshot_follow_up_appends_user_message(runner):
    hist = (
        Message(role="user", text="first", image_png=None),
        Message(role="assistant", text="reply", image_png=None),
    )
    req = FollowUpRequest(user_text="why?", include_screenshot=False, recapture=False)
    snap = runner.snapshot_follow_up(req, hist)
    assert len(snap.messages) == 3
    assert snap.messages[-1].role == "user"
    assert snap.messages[-1].text == "why?"


def test_snapshot_inspect_json_mode_true(runner):
    snap = runner.snapshot_inspect([b"\x89PNG\r\n\x1a\n"])
    assert snap.params["json_mode"] is True
    assert len(snap.messages) == 1
    assert snap.messages[0].image_png is not None
