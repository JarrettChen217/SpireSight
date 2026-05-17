from datetime import datetime, timezone
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.history_store import HistoryEntry, HistoryStore
from spiresight.ui.tabs.history_tab import HistoryTab


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def locale(tmp_path: Path) -> UILocale:
    en = tmp_path / "en"
    en.mkdir()
    (en / "ui_strings.yaml").write_text(
        "history:\n"
        "  empty: 'No history yet.'\n"
        "  resend: 'Resend'\n"
        "  copy_md: 'Copy'\n"
        "  row_format: '{time} · {label} · {model}'\n",
        encoding="utf-8",
    )
    return UILocale(tmp_path, language="en")


def _entry(prompt_id: str = "hand", ts: datetime | None = None) -> HistoryEntry:
    return HistoryEntry(
        timestamp=ts or datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
        prompt_id=prompt_id,
        custom_text="",
        model_id="gpt-4o",
        include_screenshot=True,
        screenshot_png=None,
        markdown=f"# {prompt_id}",
    )


def test_empty_state(qtwidgets_app, locale):
    store = HistoryStore()
    tab = HistoryTab(store, locale)
    assert tab._list.count() == 0


def test_entries_populate_list_newest_first(qtwidgets_app, locale):
    store = HistoryStore()
    tab = HistoryTab(store, locale)
    store.append(_entry("a", ts=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)))
    store.append(_entry("b", ts=datetime(2026, 5, 17, 12, 1, tzinfo=timezone.utc)))
    assert tab._list.count() == 2
    # Newest first means item 0 is "b".
    assert "b" in tab._list.item(0).text()


def test_resend_emits_with_entry(qtwidgets_app, locale):
    store = HistoryStore()
    tab = HistoryTab(store, locale)
    e = _entry("x")
    store.append(e)
    tab._list.setCurrentRow(0)
    fired: list[HistoryEntry] = []
    tab.resend_requested.connect(lambda en: fired.append(en))
    tab._resend_btn.click()
    assert fired == [e]


def test_selecting_row_loads_detail(qtwidgets_app, locale):
    store = HistoryStore()
    tab = HistoryTab(store, locale)
    store.append(_entry("xyz"))
    tab._list.setCurrentRow(0)
    # OutputView buffers in current_markdown()
    assert "xyz" in tab._detail.current_markdown()
