from datetime import datetime, timezone

import pytest

from spiresight.core.usage import LoggedMessage, RequestLog
from spiresight.ui.widgets.log_row import LogRow, TextRow


@pytest.fixture
def sample_record():
    return RequestLog(
        correlation_id="a3f2c1de",
        timestamp=datetime.now(tz=timezone.utc),
        provider="openai",
        model="gpt-4o",
        system="You are SpireSight.",
        messages=[
            LoggedMessage(role="user", text="What card?", image_summary="PNG, 245 KB, 1920×1080"),
        ],
        params={"json_mode": False, "has_images": True},
    )


def test_log_row_initial_collapsed(qtbot, sample_record):
    row = LogRow(sample_record)
    qtbot.addWidget(row)
    assert row.correlation_id == "a3f2c1de"
    assert row._body.isVisible() is False


def test_log_row_toggle_shows_body(qtbot, sample_record):
    row = LogRow(sample_record)
    qtbot.addWidget(row)
    row.show()
    row.toggle()
    assert row._body.isVisible() is True
    row.toggle()
    assert row._body.isVisible() is False


def test_log_row_set_response_ok(qtbot, sample_record):
    row = LogRow(sample_record)
    qtbot.addWidget(row)
    row.set_response("the answer", "ok", None)
    assert "ok" in row._summary.text()
    assert "the answer" in row._response.toPlainText()


def test_log_row_set_response_error_appends_error(qtbot, sample_record):
    row = LogRow(sample_record)
    qtbot.addWidget(row)
    row.set_response("partial", "error", "NetworkError: down")
    txt = row._response.toPlainText()
    assert "partial" in txt
    assert "[error] NetworkError: down" in txt


def test_log_row_to_plain_text_contains_all_sections(qtbot, sample_record):
    row = LogRow(sample_record)
    qtbot.addWidget(row)
    row.set_response("the answer", "ok", None)
    txt = row.to_plain_text()
    assert "System prompt" in txt
    assert "You are SpireSight." in txt
    assert "Messages" in txt
    assert "What card?" in txt
    assert "PNG, 245 KB, 1920×1080" in txt
    assert "Params" in txt
    assert "json_mode: False" in txt
    assert "Response" in txt
    assert "the answer" in txt


def test_text_row_no_body(qtbot):
    tr = TextRow("[12:03:40] saved settings")
    qtbot.addWidget(tr)
    assert tr.to_plain_text() == "[12:03:40] saved settings"
