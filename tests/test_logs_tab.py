from datetime import datetime, timezone
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.core.usage import CallRecord, TokenUsage
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


def _all_text(tab: LogsTab) -> str:
    """Concatenate to_plain_text() for every row in the stack (newest first)."""
    parts: list[str] = []
    for i in range(tab._row_count()):
        w = tab._stack.itemAt(i).widget()
        if hasattr(w, "to_plain_text"):
            parts.append(w.to_plain_text())
    return "\n".join(parts)


def test_starts_empty(qtwidgets_app, locale):
    tab = LogsTab(locale)
    assert tab._row_count() == 0


def test_log_appends_newest_on_top(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log("first")
    tab.log("second")
    text = _all_text(tab)
    lines = text.splitlines()
    # newest is at index 0 in the stack, so appears first in lines
    assert any("second" in line for line in lines[:2])
    assert any("first" in line for line in lines)
    second_pos = next(i for i, line in enumerate(lines) if "second" in line)
    first_pos = next(i for i, line in enumerate(lines) if "first" in line)
    assert second_pos < first_pos


def test_clear_empties(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log("a")
    tab._clear_btn.click()
    assert tab._row_count() == 0


def test_ring_buffer_caps_at_200(qtwidgets_app, locale):
    tab = LogsTab(locale)
    for i in range(250):
        tab.log(f"line-{i}")
    assert tab._row_count() == 200
    text = _all_text(tab)
    assert "line-0" not in text
    assert "line-49" not in text


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
    text = _all_text(tab)
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
    text = _all_text(tab)
    assert "~$—" in text


def test_log_cost_renders_question_marks_when_usage_unknown(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log_cost(_record(in_t=0, out_t=0, known=False, cost=None))
    text = _all_text(tab)
    assert "↑ ?" in text
    assert "↓ ?" in text


def test_log_cost_escapes_html_in_previews(qtwidgets_app, locale):
    tab = LogsTab(locale)
    tab.log_cost(_record(qprev="<script>alert(1)</script>", aprev="<b>bold</b>"))
    text = _all_text(tab)
    assert "<script>alert(1)</script>" in text
    assert "<b>bold</b>" in text


def test_log_and_log_cost_share_buffer_cap(qtwidgets_app, locale):
    tab = LogsTab(locale)
    for i in range(150):
        tab.log(f"plain-{i}")
    for i in range(100):
        tab.log_cost(_record(model=f"m-{i}"))
    assert tab._row_count() == 200
    text = _all_text(tab)
    assert "plain-0" not in text
    assert "m-99" in text
