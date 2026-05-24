from __future__ import annotations

import json


WIKITEXT = """
{{Card
|name=Deflect
|character=Silent
|rarity=Common
|type=Skill
|cost=0
|description=Gain 4 Block.
|upgrade=Gain 7 Block.
}}
"""

STS2_WIKITEXT = """
{{Sequel Disambiguation}}{{Card Infobox|Deflect||2}}
{{C|Deflect||2}} is a 0 {{Icon|SE|2}} cost {{QueryLink|Cards|rarity:Common&color:Silent|Common|2}} {{QueryLink|Cards|type:Skill&color:Silent|Skill|2}} Card for the {{KW|Silent||2}}. It gives 4 (7 if upgraded) {{KW|Block||2}}.
== Update History ==
* '''Early Access v0.98'''
"""

HTML = """
<html><body>
<aside class="portable-infobox">
  <h2 class="pi-title">Abyssal Wave</h2>
  <div data-source="character"><div class="pi-data-value">Silent</div></div>
  <div data-source="rarity"><div class="pi-data-value">Uncommon</div></div>
  <div data-source="type"><div class="pi-data-value">Skill</div></div>
  <div data-source="cost"><div class="pi-data-value">1</div></div>
</aside>
<p>Apply 6 Poison. Gain 1 Intangible next turn.</p>
</body></html>
"""


def test_parse_card_wikitext_extracts_upgrade_description():
    from tools.fetch_sts2_cards import parse_card_wikitext

    card = parse_card_wikitext(
        title="Deflect",
        wikitext=WIKITEXT,
        source_url="https://example.test/Deflect",
        fetched_at="2026-05-24T00:00:00+00:00",
    )
    assert card.name_en == "Deflect"
    assert card.rarity == "common"
    assert card.card_type == "skill"
    assert card.description == "Gain 4 Block."
    assert card.upgraded_description == "Gain 7 Block."


def test_parse_sts2_sentence_wikitext_extracts_description():
    from tools.fetch_sts2_cards import parse_card_wikitext

    card = parse_card_wikitext(
        title="Slay the Spire 2:Deflect",
        wikitext=STS2_WIKITEXT,
        source_url="https://example.test/Slay_the_Spire_2:Deflect",
        fetched_at="2026-05-24T00:00:00+00:00",
    )
    assert card.name_en == "Deflect"
    assert card.rarity == "common"
    assert card.card_type == "skill"
    assert card.cost == "0"
    assert "gives 4" in card.description
    assert "block" in card.mechanics


def test_parse_card_html_fallback_extracts_basic_fields():
    from tools.fetch_sts2_cards import parse_card_html

    card = parse_card_html(
        title="Abyssal Wave",
        html=HTML,
        source_url="https://example.test/Abyssal_Wave",
        fetched_at="2026-05-24T00:00:00+00:00",
    )
    assert card.name_en == "Abyssal Wave"
    assert card.rarity == "uncommon"
    assert card.cost == "1"
    assert "Poison" in card.description


def test_write_outputs_preserves_existing_alias_file(tmp_path):
    from tools.fetch_sts2_cards import write_outputs
    from spiresight.knowledge.models import CardKnowledge

    output = tmp_path / "sts2_cards"
    output.mkdir()
    alias_path = output / "zh_aliases.yaml"
    alias_path.write_text("Deflect:\n- 偏折\n", encoding="utf-8")

    card = CardKnowledge(
        id="deflect",
        name_en="Deflect",
        aliases=[],
        character="Silent",
        rarity="common",
        card_type="skill",
        cost="0",
        description="Gain 4 Block.",
        upgraded_description=None,
        mechanics=["block"],
        source_name="wiki.gg",
        source_url="https://example.test/Deflect",
        fetched_at="2026-05-24T00:00:00+00:00",
    )
    write_outputs(output, [card], warnings=["secondary skipped"])

    cards = json.loads((output / "cards.json").read_text(encoding="utf-8"))
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert cards[0]["id"] == "deflect"
    assert metadata["card_count"] == 1
    assert metadata["warnings"] == ["secondary skipped"]
    assert alias_path.read_text(encoding="utf-8") == "Deflect:\n- 偏折\n"


def test_filter_candidate_titles_keeps_sts2_cards_and_drops_mechanics():
    from tools.fetch_sts2_cards import filter_candidate_titles

    links = [
        {"ns": 3000, "*": "Slay the Spire 2:Deflect"},
        {"ns": 3000, "*": "Slay the Spire 2:Block"},
        {"ns": 0, "*": "Deflect"},
        {"ns": 3000, "*": "Slay the Spire 2:Cards List"},
    ]
    assert filter_candidate_titles(links) == ["Slay the Spire 2:Deflect"]
