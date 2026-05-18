from unittest.mock import MagicMock

from spiresight.core.runner import RequestSnapshot
from spiresight.core.messages import Message
from spiresight.core.usage import RequestLog
from spiresight.ui.workers.inspect_worker import InspectWorker


def test_inspect_worker_emits_request_logged(qtbot, monkeypatch):
    runner = MagicMock()
    runner.snapshot_inspect.return_value = RequestSnapshot(
        provider="openai", model="gpt-4o",
        system="INSPECT-SYS",
        messages=(Message(role="user", text="Extract.", image_png=b"\x89PNG"),),
        params={"json_mode": True, "has_images": True, "image_count": 1},
    )
    runner.inspect.return_value = MagicMock()

    w = InspectWorker(runner=runner, frames=[b"\x89PNG"])
    with qtbot.waitSignal(w.request_logged, timeout=2000) as blocker:
        w.run()
    rec: RequestLog = blocker.args[0]
    assert rec.system == "INSPECT-SYS"
    assert rec.params["json_mode"] is True
