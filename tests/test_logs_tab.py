from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.tabs.logs_tab import LogsTab


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def locale(tmp_path: Path) -> UILocale:
    en = tmp_path / "en"
    en.mkdir()
    (en / "ui_strings.yaml").write_text(
        "logs:\n"
        "  empty: 'No events yet.'\n"
        "  copy_all: 'Copy'\n"
        "  clear: 'Clear'\n",
        encoding="utf-8",
    )
    return UILocale(tmp_path, language="en")


def test_starts_empty(qtwidgets_app, locale):
    tab = LogsTab(locale)
    assert tab._view.toPlainText() == ""


def test_log_appends_newest_on_top(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log("first")
    tab.log("second")
    text = tab._view.toPlainText()
    assert text.splitlines()[0].endswith("second")
    assert text.splitlines()[1].endswith("first")


def test_clear_empties(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log("a")
    tab._clear_btn.click()
    assert tab._view.toPlainText() == ""


def test_ring_buffer_caps_at_200(qtwidgets_app, locale):
    tab = LogsTab(locale)
    for i in range(250):
        tab.log(f"line-{i}")
    assert len(tab._view.toPlainText().splitlines()) == 200
    # oldest evicted: line-0 not present
    assert "line-0\n" not in tab._view.toPlainText()
    assert "line-49" not in tab._view.toPlainText()


from datetime import datetime, timezone

from spiresight.core.usage import CallRecord, TokenUsage


def _record(model: str = "gpt-4o", in_t: int = 312, out_t: int = 421,
            cost: float | None = 0.005, known: bool = True,
            qprev: str = "How do I survive elite",
            aprev: str = "You should drop two energy") -> CallRecord:
    return CallRecord(
        timestamp=datetime(2026, 5, 17, 12, 1, 23, tzinfo=timezone.utc),
        model=model,
        usage=TokenUsage(in_t, out_t),
        usage_known=known,
        cost_usd=cost,
        input_preview=qprev,
        output_preview=aprev,
    )


def test_log_cost_renders_all_fields(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log_cost(_record())
    text = tab._view.toPlainText()
    assert "[cost]" in text
    assert "gpt-4o" in text
    assert "312" in text
    assert "421" in text
    assert "~$0.0050" in text
    assert "How do I survive elite" in text
    assert "You should drop two energy" in text


def test_log_cost_falls_back_to_dash_when_cost_none(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log_cost(_record(cost=None))
    text = tab._view.toPlainText()
    assert "~$—" in text


def test_log_cost_renders_question_marks_when_usage_unknown(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log_cost(_record(in_t=0, out_t=0, known=False, cost=None))
    text = tab._view.toPlainText()
    assert "↑ ?" in text
    assert "↓ ?" in text


def test_log_cost_escapes_html_in_previews(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log_cost(_record(qprev="<script>alert(1)</script>", aprev="<b>bold</b>"))
    text = tab._view.toPlainText()
    # script tag text should appear literally in plain text — not be executed/stripped
    assert "<script>alert(1)</script>" in text
    assert "<b>bold</b>" in text


def test_log_and_log_cost_share_buffer_cap(qtwidgets_app, locale):
    tab = LogsTab(locale)
    for i in range(150):
        tab.log(f"plain-{i}")
    for i in range(100):
        tab.log_cost(_record(model=f"m-{i}"))
    # cap is 200; combined inserts (250) → oldest evicted
    text = tab._view.toPlainText()
    assert "plain-0" not in text
    # newest cost row visible
    assert "m-99" in text
