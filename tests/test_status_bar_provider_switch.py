"""Test status bar behavior when switching between providers with/without models."""
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spiresight.config.store import ConfigStore
from spiresight.prompts.loader import PromptLoader
from spiresight.core.usage import PricingTable
from spiresight.core.conversation import ConversationStore
from spiresight.ui.windows.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication instance for tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def main_window(qapp, tmp_path):
    """Create MainWindow instance for testing."""
    store = ConfigStore()
    config = store.load()

    # Use test prompts directory
    prompts_dir = Path(__file__).parent.parent / "prompts"
    loader = PromptLoader(prompts_dir)

    # Load pricing (may be empty)
    pricing = PricingTable.load(prompts_dir / "prices.yaml")

    conversation_store = ConversationStore()

    window = MainWindow(config, store, loader, pricing=pricing, conversation_store=conversation_store)
    yield window
    window.close()


def test_initial_state(main_window):
    """Test initial status bar shows correct model."""
    status_text = main_window._usage_bar.text_for_test()
    assert main_window._config.active_model in status_text
    assert main_window._compose.isEnabled()
    assert main_window._prompt_panel.isEnabled()


def test_switch_to_provider_without_models(main_window):
    """Test switching to a provider with no models."""
    # Switch to anthropic (no models in MVP)
    picker = main_window._picker
    picker._provider_box.setCurrentIndex(picker._provider_box.findData("anthropic"))

    # Status bar should show provider name with "(no models)"
    status_text = main_window._usage_bar.text_for_test()
    assert "anthropic" in status_text.lower()
    assert "no models" in status_text.lower()

    # UI should be disabled
    assert not main_window._compose.isEnabled()
    assert not main_window._prompt_panel.isEnabled()

    # Config should reflect provider change
    assert main_window._config.active_provider == "anthropic"


def test_switch_back_to_provider_with_models(main_window):
    """Test switching back to a provider with models."""
    # First switch to anthropic
    picker = main_window._picker
    picker._provider_box.setCurrentIndex(picker._provider_box.findData("anthropic"))

    # Then switch back to openai
    picker._provider_box.setCurrentIndex(picker._provider_box.findData("openai"))

    # Status bar should show a valid model name
    status_text = main_window._usage_bar.text_for_test()
    assert "no models" not in status_text.lower()

    # UI should be enabled
    assert main_window._compose.isEnabled()
    assert main_window._prompt_panel.isEnabled()

    # Config should reflect provider change
    assert main_window._config.active_provider == "openai"


def test_multiple_switches(main_window):
    """Test multiple switches between providers."""
    picker = main_window._picker

    # openai -> anthropic -> openai -> anthropic
    for _ in range(2):
        # To anthropic
        picker._provider_box.setCurrentIndex(picker._provider_box.findData("anthropic"))
        assert "no models" in main_window._usage_bar.text_for_test().lower()
        assert not main_window._compose.isEnabled()

        # Back to openai
        picker._provider_box.setCurrentIndex(picker._provider_box.findData("openai"))
        assert "no models" not in main_window._usage_bar.text_for_test().lower()
        assert main_window._compose.isEnabled()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
