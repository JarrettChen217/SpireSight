from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QCoreApplication

from spiresight.core.run_state import RunState, Card
from spiresight.ui.state.run_state_store import RunStateStore


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def _sample() -> RunState:
    return RunState(
        cards=[Card(name="Strike", count=4, rarity="starter", usefulness="skip")],
        relics=[], potions=[], archetype_candidates=[],
        overall_eval="", inspected_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
    )


def test_initial_state_is_none(qapp):
    store = RunStateStore()
    assert store.get() is None


def test_set_then_get(qapp):
    store = RunStateStore()
    state = _sample()
    store.set(state)
    assert store.get() == state


def test_clear_resets_to_none(qapp):
    store = RunStateStore()
    store.set(_sample())
    store.clear()
    assert store.get() is None


def test_changed_signal_emits_on_set(qapp):
    store = RunStateStore()
    emissions: list[RunState | None] = []
    store.changed.connect(lambda s: emissions.append(s))
    state = _sample()
    store.set(state)
    assert emissions == [state]


def test_changed_signal_emits_on_clear(qapp):
    store = RunStateStore()
    store.set(_sample())
    emissions: list[RunState | None] = []
    store.changed.connect(lambda s: emissions.append(s))
    store.clear()
    assert emissions == [None]
