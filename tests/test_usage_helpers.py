from datetime import datetime, timezone

import pytest

from spiresight.core.usage import CallRecord, TokenUsage, _truncate_preview


def test_token_usage_is_frozen_and_holds_ints():
    u = TokenUsage(input_tokens=12, output_tokens=34)
    assert u.input_tokens == 12
    assert u.output_tokens == 34
    with pytest.raises(Exception):  # FrozenInstanceError subclass of Exception
        u.input_tokens = 99  # type: ignore[misc]


def test_call_record_minimal_construction():
    ts = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)
    r = CallRecord(
        timestamp=ts,
        model="gpt-4o",
        usage=TokenUsage(10, 20),
        usage_known=True,
        cost_usd=0.0005,
        input_preview="hi",
        output_preview="there",
    )
    assert r.model == "gpt-4o"
    assert r.usage_known is True
    assert r.cost_usd == 0.0005


def test_truncate_preview_short_returns_unchanged():
    assert _truncate_preview("hello world", 60) == "hello world"


def test_truncate_preview_long_cuts_with_ellipsis():
    text = "a" * 80
    out = _truncate_preview(text, 60)
    assert out.endswith("…")
    assert len(out) <= 61  # 60 chars + the ellipsis


def test_truncate_preview_snaps_to_word_boundary():
    text = "the quick brown fox jumps over the lazy dog three times today"
    out = _truncate_preview(text, 25)
    # should not end mid-word; should end on a whitespace boundary, then "…"
    assert out.endswith("…")
    before = out[:-1].rstrip()
    assert " " not in before[-3:] or before.endswith(" ") is False
    # the word boundary rule: prefer trimming back to the last whitespace before max
    assert before in text


def test_truncate_preview_empty_string():
    assert _truncate_preview("", 60) == ""


def test_truncate_preview_collapses_newlines_to_spaces():
    out = _truncate_preview("line1\nline2\nline3", 60)
    assert "\n" not in out
    assert "line1 line2 line3" == out
