from datetime import datetime, timezone

from spiresight.ui.state.history_store import HistoryEntry, HistoryStore


def _entry(prompt_id: str = "hand_eval", ts: datetime | None = None) -> HistoryEntry:
    return HistoryEntry(
        timestamp=ts or datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
        prompt_id=prompt_id,
        custom_text="",
        model_id="gpt-4o",
        include_screenshot=True,
        screenshot_png=b"\x89PNG\r\n\x1a\n",
        markdown="**hi**",
    )


def test_initial_entries_empty(qapp):
    store = HistoryStore()
    assert store.entries() == []


def test_append_emits_changed(qapp):
    store = HistoryStore()
    fired: list[int] = []
    store.changed.connect(lambda: fired.append(1))
    store.append(_entry())
    assert fired == [1]


def test_entries_returns_newest_first(qapp):
    store = HistoryStore()
    older = _entry(ts=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc))
    newer = _entry(ts=datetime(2026, 5, 17, 12, 1, tzinfo=timezone.utc))
    store.append(older)
    store.append(newer)
    assert store.entries()[0] is newer
    assert store.entries()[1] is older


def test_capacity_caps_at_20(qapp):
    store = HistoryStore()
    for i in range(25):
        store.append(_entry(prompt_id=f"p{i}"))
    assert len(store.entries()) == 20
    # Newest appended is at index 0; oldest five (p0..p4) evicted.
    assert store.entries()[0].prompt_id == "p24"
    assert all(e.prompt_id != "p0" for e in store.entries())


def test_clear_empties_and_emits(qapp):
    store = HistoryStore()
    store.append(_entry())
    fired: list[int] = []
    store.changed.connect(lambda: fired.append(1))
    store.clear()
    assert store.entries() == []
    assert fired == [1]


def test_entry_is_frozen():
    e = _entry()
    import pytest
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        e.prompt_id = "x"  # type: ignore[misc]
