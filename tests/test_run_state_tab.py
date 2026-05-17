from datetime import datetime, timezone
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.core.run_state import ArchetypeCandidate, Card, RunState
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.run_state_store import RunStateStore
from spiresight.ui.tabs.run_state_tab import RunStateTab


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def locale(tmp_path: Path) -> UILocale:
    en = tmp_path / "en"
    en.mkdir()
    (en / "ui_strings.yaml").write_text(
        "panel:\n"
        "  empty_hint: 'hint'\n"
        "  archetype: 'Archetype'\n"
        "  cards: 'Cards ({total})'\n"
        "  relics: 'Relics'\n"
        "  potions: 'Potions'\n"
        "  eval: 'Eval'\n"
        "  cards_group:\n"
        "    key: 'KEY'\n"
        "    good: 'GOOD'\n"
        "    situational: 'SITUATIONAL'\n"
        "    skip: 'SKIP'\n",
        encoding="utf-8",
    )
    return UILocale(tmp_path, language="en")


def test_construct_with_empty_store(qtwidgets_app, locale):
    store = RunStateStore()
    tab = RunStateTab(store, locale)
    assert tab is not None


def test_renders_after_store_set(qtwidgets_app, locale):
    store = RunStateStore()
    tab = RunStateTab(store, locale)
    state = RunState(
        cards=[
            Card(name="Cold Snap", count=2, rarity="common", usefulness="key", note="core"),
            Card(name="Defend", count=3, rarity="common", usefulness="good"),
        ],
        relics=[], potions=[],
        archetype_candidates=[ArchetypeCandidate(name="Frost", confidence="high")],
        overall_eval="",
        inspected_at=datetime(2026, 5, 17, tzinfo=timezone.utc),
    )
    store.set(state)
    # Did not raise; at least one child widget exists under the scroll area.
    assert tab._panel._content_layout.count() > 0
