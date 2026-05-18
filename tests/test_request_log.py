from datetime import datetime, timezone

from spiresight.core.usage import RequestLog, LoggedMessage


def test_logged_message_image_summary_optional():
    m1 = LoggedMessage(role="user", text="hi", image_summary=None)
    m2 = LoggedMessage(role="user", text="look", image_summary="PNG, 245 KB, 1920×1080")
    assert m1.image_summary is None
    assert m2.image_summary == "PNG, 245 KB, 1920×1080"


def test_request_log_defaults_and_mutability():
    now = datetime.now(tz=timezone.utc)
    record = RequestLog(
        correlation_id="a3f2c1de",
        timestamp=now,
        provider="openai",
        model="gpt-4o",
        system="you are helpful",
        messages=[LoggedMessage(role="user", text="hi", image_summary=None)],
        params={"json_mode": False, "has_images": False},
    )
    assert record.response == ""
    assert record.status == "sent"
    assert record.error is None
    assert record.finished_at is None
    # response is mutable so update_response can rewrite in place
    record.response = "world"
    record.status = "ok"
    assert record.response == "world"
    assert record.status == "ok"


def test_correlation_id_is_eight_hex():
    from uuid import uuid4
    cid = uuid4().hex[:8]
    assert len(cid) == 8
    assert all(c in "0123456789abcdef" for c in cid)
