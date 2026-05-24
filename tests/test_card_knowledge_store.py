from __future__ import annotations

import json

import yaml


def _write_cards(root):
    data_dir = root / "sts2_cards"
    data_dir.mkdir()
    cards = [
        {
            "id": "abyssal_wave",
            "name_en": "Abyssal Wave",
            "aliases": ["Abyss Wave"],
            "character": "Silent",
            "rarity": "uncommon",
            "card_type": "skill",
            "cost": "1",
            "description": "Apply 6 Poison. Gain 1 Intangible next turn.",
            "upgraded_description": "Apply 8 Poison. Gain 1 Intangible next turn.",
            "mechanics": ["poison", "intangible"],
            "source_name": "wiki.gg",
            "source_url": "https://example.test/Abyssal_Wave",
            "fetched_at": "2026-05-24T00:00:00+00:00",
        },
        {
            "id": "deflect",
            "name_en": "Deflect",
            "aliases": [],
            "character": "Silent",
            "rarity": "common",
            "card_type": "skill",
            "cost": "0",
            "description": "Gain 4 Block.",
            "upgraded_description": "Gain 7 Block.",
            "mechanics": ["block"],
            "source_name": "wiki.gg",
            "source_url": "https://example.test/Deflect",
            "fetched_at": "2026-05-24T00:00:00+00:00",
        },
    ]
    (data_dir / "cards.json").write_text(json.dumps(cards), encoding="utf-8")
    (data_dir / "metadata.json").write_text(
        json.dumps({"source_name": "wiki.gg", "card_count": 2, "warnings": []}),
        encoding="utf-8",
    )
    (data_dir / "zh_aliases.yaml").write_text(
        yaml.safe_dump({"Abyssal Wave": ["深渊波浪"], "Deflect": ["偏折"]}, allow_unicode=True),
        encoding="utf-8",
    )
    return data_dir


def test_exact_english_name_match(tmp_path):
    from spiresight.knowledge.card_store import CardKnowledgeStore

    store = CardKnowledgeStore.from_dir(_write_cards(tmp_path))
    hits = store.search_cards("Abyssal Wave")
    assert store.status == "ready"
    assert hits[0].card.name_en == "Abyssal Wave"
    assert hits[0].match_type == "exact"


def test_chinese_alias_matches_english_card(tmp_path):
    from spiresight.knowledge.card_store import CardKnowledgeStore

    store = CardKnowledgeStore.from_dir(_write_cards(tmp_path))
    hits = store.search_cards("我应该拿深渊波浪吗")
    assert hits[0].card.name_en == "Abyssal Wave"
    assert hits[0].match_type == "alias"


def test_fuzzy_typo_matches_card_name(tmp_path):
    from spiresight.knowledge.card_store import CardKnowledgeStore

    store = CardKnowledgeStore.from_dir(_write_cards(tmp_path))
    hits = store.search_cards("Abyzal Wav")
    assert hits[0].card.name_en == "Abyssal Wave"
    assert hits[0].match_type == "fuzzy"


def test_keyword_fallback_matches_description(tmp_path):
    from spiresight.knowledge.card_store import CardKnowledgeStore

    store = CardKnowledgeStore.from_dir(_write_cards(tmp_path))
    hits = store.search_cards("Need more block")
    assert hits[0].card.name_en == "Deflect"
    assert hits[0].match_type == "keyword"


def test_missing_index_returns_no_hits(tmp_path):
    from spiresight.knowledge.card_store import CardKnowledgeStore

    store = CardKnowledgeStore.from_dir(tmp_path / "missing")
    assert store.status == "missing_index"
    assert store.search_cards("Abyssal Wave") == []
