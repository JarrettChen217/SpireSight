"""Regression tests for follow-up UI / prompt selection (no full MainWindow)."""
from unittest.mock import MagicMock

import pytest

from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.core.messages import Message
from spiresight.core.request import FollowUpRequest
from spiresight.core.runner import InferenceRunner
from spiresight.llm.capabilities import Capability
from spiresight.llm.models import ModelInfo


@pytest.fixture
def runner():
    cfg = AppConfig(active_provider="openai", active_model="gpt-4o", request_timeout_seconds=60)
    cfg.providers = {"openai": ProviderConfig(api_key="sk-x")}
    loader = MagicMock()
    factory = MagicMock()
    factory.return_value.list_models.return_value = [
        ModelInfo("gpt-4o", "GPT-4o", frozenset({Capability.VISION}), context_window=128_000)
    ]
    return InferenceRunner(
        config=cfg,
        prompt_loader=loader,
        provider_factory=factory,
        screen_capture=MagicMock(),
        run_state_store=None,
    )


def test_snapshot_follow_up_empty_history_uses_freeform(runner):
    req = FollowUpRequest(user_text="hello", include_screenshot=False)
    snap = runner.snapshot_follow_up(req, ())
    assert "continuing" not in snap.system.lower()
    assert "slay" in snap.system.lower() or "spire" in snap.system.lower()


def test_snapshot_follow_up_with_history_uses_guard(runner):
    hist = (
        Message(role="user", text="hi"),
        Message(role="assistant", text="there"),
    )
    req = FollowUpRequest(user_text="why?", include_screenshot=False)
    snap = runner.snapshot_follow_up(req, hist)
    assert "continuing" in snap.system.lower()
