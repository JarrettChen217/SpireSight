from __future__ import annotations

from datetime import datetime, timezone

from spiresight.knowledge.card_store import CardKnowledgeStore
from spiresight.knowledge.models import CardKnowledge


def _store() -> CardKnowledgeStore:
    return CardKnowledgeStore(
        cards=(
            CardKnowledge(
                id="deflect",
                name_en="Deflect",
                aliases=["偏折"],
                character="Silent",
                rarity="common",
                card_type="skill",
                cost="0",
                description="Gain 4 Block.",
                upgraded_description="Gain 7 Block.",
                mechanics=["block"],
                source_name="wiki.gg",
                source_url="https://example.test/Deflect",
                fetched_at=datetime(2026, 5, 24, tzinfo=timezone.utc),
            ),
        )
    )


def test_off_mode_never_injects():
    from spiresight.knowledge.gateway import KnowledgeGateway

    result = KnowledgeGateway(_store()).evaluate(
        action_id="card_selection",
        mode="off",
        user_text="Deflect",
    )
    assert result.injected is False
    assert result.status == "disabled"
    assert result.prompt_block == ""


def test_auto_injects_for_card_selection():
    from spiresight.knowledge.gateway import KnowledgeGateway

    result = KnowledgeGateway(_store()).evaluate(
        action_id="card_selection",
        mode="auto",
        user_text="Deflect",
    )
    assert result.injected is True
    assert result.status == "hit"
    assert result.hits == ["Deflect"]
    assert "## Card Knowledge Context" in result.prompt_block
    assert "Gain 4 Block." in result.prompt_block
    assert "Prefer the screenshot" in result.prompt_block


def test_auto_skips_other_actions():
    from spiresight.knowledge.gateway import KnowledgeGateway

    result = KnowledgeGateway(_store()).evaluate(
        action_id="combat_strategy",
        mode="auto",
        user_text="Deflect",
    )
    assert result.injected is False
    assert result.status == "skipped"


def test_on_records_missing_index_without_prompt():
    from spiresight.knowledge.gateway import KnowledgeGateway

    result = KnowledgeGateway(CardKnowledgeStore(cards=(), status="missing_index")).evaluate(
        action_id="card_selection",
        mode="on",
        user_text="Deflect",
    )
    assert result.injected is False
    assert result.status == "missing_index"
    assert result.prompt_block == ""
