from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from spiresight.core.run_state import (
    ArchetypeCandidate, Card, Relic, RunState,
)


def _sample_state() -> RunState:
    return RunState(
        cards=[
            Card(name="Strike", count=4, rarity="starter", usefulness="skip", note="filler"),
            Card(name="Heavy Blade+", count=1, rarity="uncommon", usefulness="key",
                 note="main scaler"),
            Card(name="Pommel Strike", count=2, rarity="common", usefulness="good"),
        ],
        relics=[
            Relic(name="Akabeko", synergy_tags=["strength"]),
            Relic(name="Vajra", synergy_tags=["strength"]),
        ],
        potions=["Energy Potion"],
        archetype_candidates=[
            ArchetypeCandidate(name="Strength", confidence="high",
                               rationale="Akabeko + Heavy Blade"),
            ArchetypeCandidate(name="Exhaust", confidence="low",
                               rationale="no pickups yet"),
        ],
        overall_eval="Strong strength curve. Next pick should scale.",
        inspected_at=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )


def test_run_state_json_roundtrip():
    state = _sample_state()
    blob = state.model_dump_json()
    again = RunState.model_validate_json(blob)
    assert again == state


def test_to_prompt_block_contains_archetype_cards_relics_eval():
    state = _sample_state()
    block = state.to_prompt_block()
    assert block.startswith("## Current Run Context")
    assert "Strength (high)" in block
    assert "Exhaust (low)" in block
    assert "Heavy Blade+" in block
    assert "Strike x4" in block
    assert "Akabeko" in block and "Vajra" in block
    assert "Strong strength curve" in block


def test_to_prompt_block_groups_cards_by_usefulness():
    state = _sample_state()
    block = state.to_prompt_block()
    # key cards listed before filler
    key_idx = block.index("Heavy Blade+")
    skip_idx = block.index("Strike x4")
    assert key_idx < skip_idx


def test_to_prompt_block_omits_empty_sections():
    minimal = RunState(
        cards=[Card(name="Strike", count=4, rarity="starter", usefulness="skip")],
        relics=[],
        potions=[],
        archetype_candidates=[],
        overall_eval="",
        inspected_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
    )
    block = minimal.to_prompt_block()
    assert "Relics" not in block
    assert "Eval" not in block
    assert "Archetype" not in block


def test_rejects_bad_usefulness():
    with pytest.raises(ValidationError):
        Card(name="X", rarity="common", usefulness="amazing")


def test_rejects_bad_rarity():
    with pytest.raises(ValidationError):
        Card(name="X", rarity="legendary", usefulness="good")


def test_rejects_bad_confidence():
    with pytest.raises(ValidationError):
        ArchetypeCandidate(name="X", confidence="certain", rationale="hi")
