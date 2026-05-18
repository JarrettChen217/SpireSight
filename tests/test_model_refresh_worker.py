from unittest.mock import MagicMock

from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import AuthError
from spiresight.llm.models import ModelInfo
from spiresight.ui.workers.model_refresh_worker import ModelRefreshWorker


def test_succeeded_signal_emits_models(qtbot):
    fake_provider = MagicMock()
    fake_models = [ModelInfo("a", "A", frozenset({Capability.VISION}), 1_000)]
    fake_provider.fetch_remote_models.return_value = fake_models

    w = ModelRefreshWorker("openai", fake_provider)
    with qtbot.waitSignal(w.succeeded, timeout=2000) as blocker:
        w.run()
    name, models = blocker.args
    assert name == "openai"
    assert models == fake_models


def test_failed_signal_emits_exception(qtbot):
    fake_provider = MagicMock()
    err = AuthError("invalid key")
    fake_provider.fetch_remote_models.side_effect = err

    w = ModelRefreshWorker("anthropic", fake_provider)
    with qtbot.waitSignal(w.failed, timeout=2000) as blocker:
        w.run()
    name, exc = blocker.args
    assert name == "anthropic"
    assert exc is err
