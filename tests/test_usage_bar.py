from datetime import datetime, timezone

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.core.usage import CallRecord, TokenUsage, UsageTracker
from spiresight.ui.widgets.usage_bar import UsageBar, _format_k


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_format_k_under_1000_is_raw():
    assert _format_k(0) == "0"
    assert _format_k(312) == "312"
    assert _format_k(999) == "999"


def test_format_k_thousands_one_decimal():
    assert _format_k(1000) == "1.0k"
    assert _format_k(1500) == "1.5k"
    assert _format_k(12_345) == "12.3k"
    assert _format_k(4_567) == "4.6k"   # plan had "4.5k" but :.1f rounds 4.567 up
    assert _format_k(99_999) == "100.0k"


def test_format_k_hundred_thousands_no_decimal():
    assert _format_k(100_000) == "100k"
    assert _format_k(123_456) == "123k"
    assert _format_k(1_500_000) == "1500k"


def _record(model: str = "gpt-4o", in_t: int = 12_345, out_t: int = 4_567,
            cost: float | None = 0.1834) -> CallRecord:
    return CallRecord(
        timestamp=datetime(2026, 5, 17, tzinfo=timezone.utc),
        model=model,
        usage=TokenUsage(in_t, out_t),
        usage_known=True,
        cost_usd=cost,
        input_preview="q",
        output_preview="a",
    )


def test_initial_render_shows_zero_tokens_and_dash_cost(qtwidgets_app):
    tracker = UsageTracker()
    bar = UsageBar(tracker, model_label="gpt-4o")
    assert "gpt-4o" in bar.text_for_test()
    assert "↑ 0" in bar.text_for_test()
    assert "↓ 0" in bar.text_for_test()
    assert "~$—" in bar.text_for_test()


def test_compact_format_after_recorded_call(qtwidgets_app):
    tracker = UsageTracker()
    bar = UsageBar(tracker, model_label="gpt-4o")
    tracker.call_started("gpt-4o", "q")
    tracker.call_completed_ok(_record(in_t=12_345, out_t=4_567, cost=0.1834))
    txt = bar.text_for_test()
    assert "↑ 12.3k" in txt
    assert "↓ 4.6k" in txt   # 4567 → 4.567 → rounds to 4.6 with :.1f
    assert "~$0.18" in txt


def test_dot_color_changes_with_status(qtwidgets_app):
    tracker = UsageTracker()
    bar = UsageBar(tracker, model_label="gpt-4o")
    assert "6b7280" in bar.dot_stylesheet_for_test().lower()  # idle gray

    tracker.call_started("gpt-4o", "q")
    assert "fbbf24" in bar.dot_stylesheet_for_test().lower()  # running amber

    tracker.call_completed_ok(_record())
    assert "4ade80" in bar.dot_stylesheet_for_test().lower()  # ok green

    tracker.call_started("gpt-4o", "q")
    tracker.call_failed("boom")
    assert "f87171" in bar.dot_stylesheet_for_test().lower()  # error red


def test_unpriced_session_shows_dash(qtwidgets_app):
    tracker = UsageTracker()
    bar = UsageBar(tracker, model_label="mystery")
    tracker.call_started("mystery", "q")
    tracker.call_completed_ok(_record(model="mystery", cost=None))
    assert "~$—" in bar.text_for_test()


def test_set_model_label_updates_display(qtwidgets_app):
    tracker = UsageTracker()
    bar = UsageBar(tracker, model_label="gpt-4o")
    bar.set_model_label("gpt-4o-mini")
    assert "gpt-4o-mini" in bar.text_for_test()


def test_tooltip_contains_precise_numbers_and_cost(qtwidgets_app):
    tracker = UsageTracker()
    bar = UsageBar(tracker, model_label="gpt-4o")
    tracker.call_started("gpt-4o", "q")
    tracker.call_completed_ok(_record(in_t=12_345, out_t=4_567, cost=0.1834))
    tip = bar.toolTip()
    assert "12,345" in tip or "12345" in tip
    assert "4,567" in tip or "4567" in tip
    assert "0.1834" in tip


def test_tooltip_notes_unpriced_when_mixed(qtwidgets_app):
    tracker = UsageTracker()
    bar = UsageBar(tracker, model_label="gpt-4o")
    tracker.call_started("gpt-4o", "q")
    tracker.call_completed_ok(_record(cost=0.01))
    tracker.call_started("mystery", "q")
    tracker.call_completed_ok(_record(model="mystery", cost=None))
    assert "unpriced" in bar.toolTip().lower()
