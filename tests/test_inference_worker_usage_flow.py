import threading
from collections.abc import Iterator

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from spiresight.core.request import QuickActionRequest
from spiresight.core.usage import CallRecord, TokenUsage
from spiresight.llm.provider import StreamChunk
from spiresight.ui.workers.inference_worker import InferenceWorker


@pytest.fixture(scope="module")
def qtwidgets_app():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeRunner:
    def __init__(self, chunks: list[StreamChunk]) -> None:
        self._chunks = chunks

    def run_quick_action(self, request, *, cancel_event: threading.Event) -> Iterator[StreamChunk]:
        for c in self._chunks:
            if cancel_event.is_set():
                return
            yield c


def _drain(worker: InferenceWorker, timeout_ms: int = 2000) -> None:
    """Spin a Qt event loop until the worker thread emits finished_ok or failed."""
    loop = QEventLoop()
    done = {"flag": False}

    def stop():
        done["flag"] = True
        loop.quit()

    worker.finished_ok.connect(stop)
    worker.failed.connect(stop)
    worker.cancelled.connect(stop)
    QTimer.singleShot(timeout_ms, loop.quit)
    worker.start()
    loop.exec()
    worker.wait(1000)
    assert done["flag"], "worker did not finish within timeout"


def test_worker_emits_run_started_then_usage_recorded(qtwidgets_app):
    chunks = [
        StreamChunk(text_delta="hello "),
        StreamChunk(text_delta="world", finish_reason="stop"),
        StreamChunk(text_delta="", usage=TokenUsage(12, 34)),
    ]
    runner = _FakeRunner(chunks)
    worker = InferenceWorker.for_quick_action(
        runner, QuickActionRequest(prompt_id="test", custom_text="", include_screenshot=False),
        model_id="gpt-4o",
        input_preview="How do I survive elite",
    )
    started: list[tuple[str, str]] = []
    records: list[CallRecord] = []
    finished: list[None] = []
    worker.run_started.connect(lambda m, q: started.append((m, q)))
    worker.usage_recorded.connect(records.append)
    worker.finished_ok.connect(lambda: finished.append(None))

    _drain(worker)

    assert started == [("gpt-4o", "How do I survive elite")]
    assert len(records) == 1
    rec = records[0]
    assert rec.model == "gpt-4o"
    assert rec.usage == TokenUsage(12, 34)
    assert rec.usage_known is True
    assert rec.cost_usd is None  # worker doesn't price; MainWindow does (see Task 10)
    assert rec.input_preview == "How do I survive elite"
    assert rec.output_preview == "hello world"
    assert finished == [None]


def test_worker_emits_usage_known_false_when_no_usage_chunk(qtwidgets_app):
    chunks = [
        StreamChunk(text_delta="bye", finish_reason="stop"),
    ]
    runner = _FakeRunner(chunks)
    worker = InferenceWorker.for_quick_action(
        runner, QuickActionRequest(prompt_id="test", custom_text="", include_screenshot=False),
        model_id="gpt-4o", input_preview="hi",
    )
    records: list[CallRecord] = []
    worker.usage_recorded.connect(records.append)

    _drain(worker)

    assert len(records) == 1
    assert records[0].usage_known is False
    assert records[0].usage == TokenUsage(0, 0)


def test_worker_continues_iterating_past_finish_reason(qtwidgets_app):
    """The usage chunk comes after finish_reason; worker must NOT break early."""
    chunks = [
        StreamChunk(text_delta="text"),
        StreamChunk(text_delta="", finish_reason="stop"),
        StreamChunk(text_delta="", usage=TokenUsage(5, 7)),
    ]
    runner = _FakeRunner(chunks)
    worker = InferenceWorker.for_quick_action(
        runner, QuickActionRequest(prompt_id="test", custom_text="", include_screenshot=False),
        model_id="gpt-4o", input_preview="hi",
    )
    records: list[CallRecord] = []
    worker.usage_recorded.connect(records.append)

    _drain(worker)

    assert records[0].usage == TokenUsage(5, 7)


def test_worker_emits_cancelled_when_cancelled_mid_stream(qtwidgets_app):
    """A canceled run does not append a record."""
    class _SlowRunner:
        def run_quick_action(self, request, *, cancel_event: threading.Event):
            # Yield one chunk, then check cancel.
            yield StreamChunk(text_delta="partial")
            # Wait briefly, allowing the caller to set cancel_event.
            for _ in range(20):
                if cancel_event.is_set():
                    return
                cancel_event.wait(0.01)
            yield StreamChunk(text_delta="", finish_reason="stop")
            yield StreamChunk(text_delta="", usage=TokenUsage(1, 1))

    worker = InferenceWorker.for_quick_action(
        _SlowRunner(), QuickActionRequest(prompt_id="test", custom_text="", include_screenshot=False),
        model_id="gpt-4o", input_preview="hi",
    )
    cancelled_signals: list[None] = []
    records: list[CallRecord] = []
    worker.cancelled.connect(lambda: cancelled_signals.append(None))
    worker.usage_recorded.connect(records.append)

    # Cancel shortly after starting.
    QTimer.singleShot(20, worker.cancel)
    _drain(worker, timeout_ms=2000)

    assert cancelled_signals == [None]
    assert records == []


def test_worker_emits_failed_on_exception(qtwidgets_app):
    class _BoomRunner:
        def run_quick_action(self, request, *, cancel_event: threading.Event):
            raise RuntimeError("boom")
            yield  # pragma: no cover  (make it a generator)

    worker = InferenceWorker.for_quick_action(
        _BoomRunner(), QuickActionRequest(prompt_id="test", custom_text="", include_screenshot=False),
        model_id="gpt-4o", input_preview="hi",
    )
    excs: list[BaseException] = []
    worker.failed.connect(excs.append)

    _drain(worker)

    assert len(excs) == 1
    assert isinstance(excs[0], RuntimeError)


def test_for_follow_up_emits_usage_recorded(qtwidgets_app):
    from spiresight.core.request import FollowUpRequest
    from spiresight.core.messages import Message

    class _FollowUpRunner:
        def run_follow_up(self, request, history, *, cancel_event):
            yield StreamChunk(text_delta="follow-up response", finish_reason="stop")
            yield StreamChunk(text_delta="", usage=TokenUsage(10, 20))

    runner = _FollowUpRunner()
    req = FollowUpRequest(user_text="tell me more")
    history = (Message(role="user", text="hello"), Message(role="assistant", text="hi"))
    worker = InferenceWorker.for_follow_up(
        runner, req, history,
        model_id="gpt-4o",
        input_preview="tell me more",
    )
    started: list[tuple[str, str]] = []
    records: list[CallRecord] = []
    worker.run_started.connect(lambda m, q: started.append((m, q)))
    worker.usage_recorded.connect(records.append)

    _drain(worker)

    assert started == [("gpt-4o", "tell me more")]
    assert len(records) == 1
    assert records[0].usage == TokenUsage(10, 20)
    assert records[0].output_preview == "follow-up response"
