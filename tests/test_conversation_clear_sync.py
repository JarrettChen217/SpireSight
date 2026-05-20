"""Regression tests for conversation clear and main/minibar transcript sync."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.core.messages import Message


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def main_window(qtwidgets_app, tmp_path, monkeypatch):
    from spiresight.config.schema import AppConfig
    from spiresight.config.store import ConfigStore
    from spiresight.core.conversation import ConversationStore
    from spiresight.core.usage import PricingTable
    from spiresight.prompts.loader import PromptLoader
    from spiresight.ui.windows.main_window import MainWindow

    cfg = AppConfig()
    store = ConfigStore(tmp_path / "config.json")
    store.save(cfg)
    repo_prompts = Path(__file__).resolve().parents[1] / "prompts"
    loader = PromptLoader(repo_prompts)
    pricing = PricingTable({})
    conv = ConversationStore()
    w = MainWindow(cfg, store, loader, pricing=pricing, conversation_store=conv)
    yield w
    w.close()


def test_clear_context_empties_store_and_both_uis(main_window):
    mw = main_window
    mw._toggle_mini_bar()
    turns = (
        Message(role="user", text="hi"),
        Message(role="assistant", text="hello"),
    )
    mw._conversation.append(turns[0])
    mw._conversation.append(turns[1])
    mw._chat_tab.render_turns(turns)
    mw._bubble.render_history(turns)

    mw._clear_conversation_context(cancel_worker=False)

    assert mw._conversation.turns() == ()
    assert mw._chat_tab.output.is_empty()
    assert mw._bubble.is_empty()


def test_on_action_in_main_mode_resets_bubble(main_window, monkeypatch):
    mw = main_window
    mw._toggle_mini_bar()
    mw._conversation.append(Message(role="user", text="old"))
    mw._conversation.append(Message(role="assistant", text="stale"))
    mw._bubble.render_history(mw._conversation.turns())
    assert not mw._bubble.is_empty()

    mw._config.mini_bar_mode = False
    action_id = "test_action"
    mw._config.last_used_prompt_id = action_id

    mock_worker_cls = MagicMock()
    mock_worker = MagicMock()
    mock_worker.isRunning.return_value = False
    mock_worker_cls.for_quick_action.return_value = mock_worker
    monkeypatch.setattr(
        "spiresight.ui.windows.main_window.InferenceWorker",
        mock_worker_cls,
    )
    monkeypatch.setattr(
        mw._loader,
        "get_quick_action",
        lambda _pid: MagicMock(label="Test"),
    )

    mw._on_action(action_id)

    assert mw._bubble.is_empty()


def test_toggle_mini_bar_after_clear_shows_empty_bubble(main_window):
    mw = main_window
    mw._toggle_mini_bar()
    mw._bubble.render_history((
        Message(role="user", text="x"),
        Message(role="assistant", text="y"),
    ))
    mw._exit_mini_bar()

    mw._clear_conversation_context(cancel_worker=False)
    mw._toggle_mini_bar()

    assert mw._bubble.is_empty()
    assert not mw._bubble.isVisible()


def test_dispatch_follow_up_does_not_cancel_running_worker(main_window, monkeypatch):
    mw = main_window
    running = MagicMock()
    running.isRunning.return_value = True
    mw._worker = running

    mw._dispatch_follow_up("next", recapture=False)

    running.cancel.assert_not_called()
