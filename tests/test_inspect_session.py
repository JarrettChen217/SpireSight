# tests/test_inspect_session.py
import pytest
from PySide6.QtCore import QCoreApplication

from spiresight.core.inspect_session import InspectSession


@pytest.fixture(autouse=True)
def _qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def test_starts_empty():
    s = InspectSession()
    assert s.count == 0
    assert s.frames == []


def test_add_frame_appends_and_emits_changed():
    s = InspectSession()
    calls: list[int] = []
    s.changed.connect(lambda: calls.append(s.count))

    s.add_frame(b"PNG1")
    s.add_frame(b"PNG2")

    assert s.count == 2
    assert s.frames == [b"PNG1", b"PNG2"]
    assert calls == [1, 2]


def test_frames_returns_defensive_copy():
    s = InspectSession()
    s.add_frame(b"PNG1")
    snapshot = s.frames
    snapshot.append(b"MUTATED")
    assert s.count == 1
    assert s.frames == [b"PNG1"]


def test_remove_frame_drops_index_and_emits():
    s = InspectSession()
    s.add_frame(b"A")
    s.add_frame(b"B")
    s.add_frame(b"C")
    emitted: list[int] = []
    s.changed.connect(lambda: emitted.append(s.count))

    s.remove_frame(1)
    assert s.frames == [b"A", b"C"]
    assert emitted == [2]


def test_remove_frame_out_of_range_raises():
    s = InspectSession()
    s.add_frame(b"A")
    with pytest.raises(IndexError):
        s.remove_frame(5)


def test_clear_empties_and_emits():
    s = InspectSession()
    s.add_frame(b"A")
    s.add_frame(b"B")
    emitted: list[int] = []
    s.changed.connect(lambda: emitted.append(s.count))

    s.clear()
    assert s.count == 0
    assert s.frames == []
    assert emitted == [0]


def test_max_frames_cap_raises_runtime_error():
    s = InspectSession()
    for i in range(InspectSession.MAX_FRAMES):
        s.add_frame(f"P{i}".encode())
    assert s.count == InspectSession.MAX_FRAMES
    with pytest.raises(RuntimeError):
        s.add_frame(b"OVERFLOW")
    assert s.count == InspectSession.MAX_FRAMES  # rejection did not append
