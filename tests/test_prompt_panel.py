from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.widgets.prompt_panel import PromptPanel


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def locale(tmp_path: Path) -> UILocale:
    en = tmp_path / "en"
    en.mkdir()
    (en / "ui_strings.yaml").write_text(
        "quick_action:\n"
        "  clear_context: 'New session'\n"
        "  clear_context_tip: 'tip'\n",
        encoding="utf-8",
    )
    return UILocale(tmp_path, language="en")


def test_clear_context_toggle_emits(qtwidgets_app, locale, tmp_path):
    from spiresight.prompts.loader import PromptLoader

    (tmp_path / "locales" / "en").mkdir(parents=True)
    (tmp_path / "locales" / "en" / "quick_actions.yaml").write_text(
        "- id: a\n  label: A\n  system_prompt_id: s\n"
        "  user_template: 't'\n  requires_screenshot: false\n",
        encoding="utf-8",
    )
    tmp_path.joinpath("system_prompts.yaml").write_text(
        "- id: s\n  description: d\n  content: sys\n", encoding="utf-8",
    )
    loader = PromptLoader(tmp_path)
    loader.reload(language="en")

    panel = PromptPanel(loader, locale, clear_context=True)
    seen: list[bool] = []
    panel.clear_context_toggled.connect(seen.append)
    panel._clear_ctx_chk.setChecked(False)
    assert seen == [False]
