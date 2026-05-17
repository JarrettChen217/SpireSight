from datetime import datetime, timezone

from spiresight.ui.state.screenshot_store import ScreenshotBundle, ScreenshotStore


PNG_A = b"\x89PNG\r\n\x1a\nA"
PNG_B = b"\x89PNG\r\n\x1a\nB"


def test_initial_get_is_none(qapp):
    store = ScreenshotStore()
    assert store.get() is None


def test_set_then_get(qapp):
    store = ScreenshotStore()
    bundle = ScreenshotBundle(
        frames=(PNG_A,),
        timestamp=datetime(2026, 5, 17, tzinfo=timezone.utc),
        width=1920, height=1080,
    )
    store.set(bundle)
    assert store.get() == bundle


def test_set_emits_changed_when_frames_differ(qapp):
    store = ScreenshotStore()
    fired: list[int] = []
    store.changed.connect(lambda: fired.append(1))
    ts = datetime(2026, 5, 17, tzinfo=timezone.utc)
    store.set(ScreenshotBundle(frames=(PNG_A,), timestamp=ts, width=10, height=10))
    store.set(ScreenshotBundle(frames=(PNG_B,), timestamp=ts, width=10, height=10))
    assert fired == [1, 1]


def test_set_skips_emit_when_frames_identical(qapp):
    store = ScreenshotStore()
    ts = datetime(2026, 5, 17, tzinfo=timezone.utc)
    store.set(ScreenshotBundle(frames=(PNG_A,), timestamp=ts, width=10, height=10))
    fired: list[int] = []
    store.changed.connect(lambda: fired.append(1))
    # Same bytes again — no emit.
    store.set(ScreenshotBundle(frames=(PNG_A,), timestamp=ts, width=10, height=10))
    assert fired == []
