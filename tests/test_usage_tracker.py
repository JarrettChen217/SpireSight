from datetime import datetime, timezone

import pytest
from PySide6.QtWidgets import QApplication

from spiresight.core.usage import CallRecord, TokenUsage, UsageTracker


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_record(model: str = "gpt-4o", input_t: int = 100, output_t: int = 200,
                 cost: float | None = 0.001, known: bool = True) -> CallRecord:
    return CallRecord(
        timestamp=datetime(2026, 5, 17, tzinfo=timezone.utc),
        model=model,
        usage=TokenUsage(input_t, output_t),
        usage_known=known,
        cost_usd=cost,
        input_preview="q",
        output_preview="a",
    )


def test_initial_state(qtwidgets_app):
    t = UsageTracker()
    assert t.totals == TokenUsage(0, 0, 0)
    assert t.total_cost_usd is None
    assert t.last_status == "idle"
    assert t.records == []
    assert t.has_unpriced_calls is False


def test_call_started_emits_running_and_remembers_prior(qtwidgets_app):
    t = UsageTracker()
    statuses: list[str] = []
    t.status_changed.connect(statuses.append)

    t.call_started("gpt-4o", "hello")
    assert t.last_status == "running"
    assert statuses == ["running"]


def test_call_completed_ok_updates_totals_and_signals(qtwidgets_app):
    t = UsageTracker()
    seen_records: list[CallRecord] = []
    totals_signals: list[None] = []
    statuses: list[str] = []
    t.call_recorded.connect(seen_records.append)
    t.totals_changed.connect(lambda: totals_signals.append(None))
    t.status_changed.connect(statuses.append)

    t.call_started("gpt-4o", "q1")
    t.call_completed_ok(_make_record(input_t=100, output_t=200, cost=0.01))
    t.call_started("gpt-4o", "q2")
    t.call_completed_ok(_make_record(input_t=50, output_t=75, cost=0.005))

    assert t.totals == TokenUsage(150, 275, 0)
    assert t.total_cost_usd == pytest.approx(0.015)
    assert len(seen_records) == 2
    assert len(totals_signals) == 2
    assert statuses[-1] == "ok"


def test_call_failed_sets_error_no_record(qtwidgets_app):
    t = UsageTracker()
    t.call_started("gpt-4o", "q")
    t.call_failed("HTTP 429")
    assert t.last_status == "error"
    assert t.records == []
    assert t.totals == TokenUsage(0, 0, 0)


def test_call_cancelled_restores_prior_status(qtwidgets_app):
    t = UsageTracker()
    # one successful call → status ok
    t.call_started("gpt-4o", "q1")
    t.call_completed_ok(_make_record(cost=0.01))
    assert t.last_status == "ok"

    # second run cancelled → status returns to ok, not error
    t.call_started("gpt-4o", "q2")
    assert t.last_status == "running"
    t.call_cancelled()
    assert t.last_status == "ok"
    assert len(t.records) == 1  # cancelled run did not append


def test_records_capped_at_200_but_totals_accumulate(qtwidgets_app):
    t = UsageTracker()
    for _ in range(250):
        t.call_started("gpt-4o", "q")
        t.call_completed_ok(_make_record(input_t=1, output_t=1, cost=0.0001))
    assert len(t.records) == 200
    assert t.totals == TokenUsage(250, 250, 0)
    assert t.total_cost_usd == pytest.approx(250 * 0.0001)


def test_total_cost_is_none_when_no_priced_calls(qtwidgets_app):
    t = UsageTracker()
    t.call_started("mystery", "q")
    t.call_completed_ok(_make_record(model="mystery", cost=None))
    assert t.total_cost_usd is None
    assert t.has_unpriced_calls is True


def test_total_cost_sums_priced_only_when_mixed(qtwidgets_app):
    t = UsageTracker()
    t.call_started("gpt-4o", "q")
    t.call_completed_ok(_make_record(cost=0.01))
    t.call_started("mystery", "q")
    t.call_completed_ok(_make_record(model="mystery", cost=None))
    assert t.total_cost_usd == pytest.approx(0.01)
    assert t.has_unpriced_calls is True


def test_records_are_most_recent_first(qtwidgets_app):
    t = UsageTracker()
    t.call_started("gpt-4o", "q1")
    t.call_completed_ok(_make_record(model="first"))
    t.call_started("gpt-4o", "q2")
    t.call_completed_ok(_make_record(model="second"))
    assert t.records[0].model == "second"
    assert t.records[1].model == "first"

def test_totals_accumulate_cached(qtwidgets_app):
    t = UsageTracker()
    t.call_started("gpt-4o", "q")
    t.call_completed_ok(_make_record(input_t=100, output_t=50))
    r = CallRecord(
        timestamp=datetime(2026, 5, 17, tzinfo=timezone.utc),
        model="gpt-4o",
        usage=TokenUsage(80, 40, 60),
        usage_known=True,
        cost_usd=0.01,
        input_preview="q",
        output_preview="a",
    )
    t.call_started("gpt-4o", "q2")
    t.call_completed_ok(r)
    assert t.totals == TokenUsage(180, 90, 60)
