from __future__ import annotations

import threading
from collections.abc import Iterator
from unittest.mock import MagicMock


from spiresight.core.messages import Message
from spiresight.core.runner import RequestSnapshot
from spiresight.core.usage import RequestLog
from spiresight.llm.errors import RequestTimeoutError
from spiresight.llm.provider import StreamChunk
from spiresight.ui.workers.inference_worker import InferenceWorker


def _make_worker(run_fn, *, snap=None):
    runner = MagicMock()
    snap = snap or RequestSnapshot(
        provider="openai", model="gpt-4o",
        system="SYS", messages=(Message(role="user", text="hi", image_png=None),),
        params={"json_mode": False, "has_images": False},
    )
    w = InferenceWorker(
        runner=runner, run_fn=run_fn,
        model_id="gpt-4o", input_preview="hi",
        snapshot=snap, correlation_id="aaaaaaaa",
    )
    return w


def test_request_logged_fires_before_stream_consumed(qtbot):
    def run_fn(cancel: threading.Event) -> Iterator[StreamChunk]:
        yield StreamChunk(text_delta="abc")

    w = _make_worker(run_fn)
    with qtbot.waitSignal(w.request_logged, timeout=2000) as blocker:
        w.run()
    rec = blocker.args[0]
    assert isinstance(rec, RequestLog)
    assert rec.correlation_id == "aaaaaaaa"
    assert rec.status == "sent"
    assert rec.system == "SYS"


def test_response_logged_on_success(qtbot):
    def run_fn(cancel):
        yield StreamChunk(text_delta="hello ")
        yield StreamChunk(text_delta="world", finish_reason="stop")
    w = _make_worker(run_fn)
    with qtbot.waitSignal(w.response_logged, timeout=2000) as blocker:
        w.run()
    cid, status, text, err = blocker.args
    assert cid == "aaaaaaaa"
    assert status == "ok"
    assert text == "hello world"
    assert err is None


def test_response_logged_on_timeout(qtbot):
    def run_fn(cancel):
        yield StreamChunk(text_delta="partial")
        raise RequestTimeoutError("Request exceeded 5s timeout")
    w = _make_worker(run_fn)
    with qtbot.waitSignal(w.response_logged, timeout=2000) as blocker:
        w.run()
    cid, status, text, err = blocker.args
    assert status == "timeout"
    assert text == "partial"
    assert "5s timeout" in err


def test_response_logged_on_cancel(qtbot):
    def run_fn(cancel):
        yield StreamChunk(text_delta="abc")
        cancel.set()
        yield StreamChunk(text_delta="never")
    w = _make_worker(run_fn)
    with qtbot.waitSignal(w.response_logged, timeout=2000) as blocker:
        w.run()
    cid, status, text, err = blocker.args
    assert status == "cancelled"
    assert text == "abc"
