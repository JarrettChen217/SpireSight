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


def test_expand_templates_preserves_keyword_labels():
    from tools.fetch_sts2_cards import expand_templates

    wikitext = (
        "{{C|Deflect||2}} is a 0 {{Icon|SE|2}} cost "
        "{{QueryLink|Cards|rarity:Common&color:Silent|Common|2}} "
        "{{QueryLink|Cards|type:Skill&color:Silent|Skill|2}} "
        "Card for the {{KW|Silent||2}}. It gives 4 (7 if upgraded) {{KW|Block||2}}."
    )
    out = expand_templates(wikitext)
    assert "Deflect" in out
    assert "Common" in out
    assert "Skill" in out
    assert "Silent" in out
    assert "Block" in out
    # Icon templates are dropped to empty
    assert "SE" not in out
    assert "Icon" not in out


def test_extract_lead_returns_text_before_first_section_header():
    from tools.fetch_sts2_cards import extract_lead

    wikitext = (
        "{{Sequel Disambiguation}}{{Card Infobox|Deflect||2}}\n"
        "Lead paragraph with {{KW|Block||2}}.\n"
        "== Update History ==\n"
        "* v0.98 added {{KW|Goopy||2}}.\n"
        "== Related Cards ==\n"
        "{{KW|Enchant||2}}\n"
    )
    lead = extract_lead(wikitext)
    assert "Block" in lead
    assert "Goopy" not in lead
    assert "Enchant" not in lead
    assert "Update History" not in lead


def test_extract_lead_returns_whole_wikitext_when_no_headers():
    from tools.fetch_sts2_cards import extract_lead

    wikitext = "Just a one-liner {{KW|Block||2}} with no section header."
    assert extract_lead(wikitext) == wikitext


def test_parse_structured_fields_extracts_rarity_type_character_cost():
    from tools.fetch_sts2_cards import parse_structured_fields

    wikitext = (
        "{{Sequel Disambiguation}}{{Card Infobox|Deflect||2}}\n"
        "{{C|Deflect||2}} is a 0 {{Icon|SE|2}} cost "
        "{{QueryLink|Cards|rarity:Common&color:Silent|Common|2}} "
        "{{QueryLink|Cards|type:Skill&color:Silent|Skill|2}} "
        "Card for the {{KW|Silent||2}}.\n"
        "== Update History ==\n"
        "{{KW|Goopy||2}}\n"
    )
    fields = parse_structured_fields(wikitext)
    assert fields == {
        "rarity": "Common",
        "card_type": "Skill",
        "character": "Silent",
        "cost": "0",
    }


def test_parse_structured_fields_handles_x_cost():
    from tools.fetch_sts2_cards import parse_structured_fields

    wikitext = (
        "{{C|Whirlwind||2}} is a X {{Icon|SE|2}} cost "
        "{{QueryLink|Cards|rarity:Uncommon&color:Ironclad|Uncommon|2}} "
        "{{QueryLink|Cards|type:Attack&color:Ironclad|Attack|2}} "
        "Card for the {{KW|Ironclad||2}}."
    )
    fields = parse_structured_fields(wikitext)
    assert fields["cost"] == "X"
    assert fields["character"] == "Ironclad"


def test_parse_structured_fields_ignores_post_lead_templates():
    from tools.fetch_sts2_cards import parse_structured_fields

    wikitext = (
        "{{C|Card||2}} is a 1 {{Icon|SE|2}} cost "
        "{{QueryLink|Cards|rarity:Common&color:Silent|Common|2}} "
        "{{QueryLink|Cards|type:Skill&color:Silent|Skill|2}} "
        "Card for the {{KW|Silent||2}}.\n"
        "== Related ==\n"
        # These post-lead templates must NOT override the lead values.
        "{{QueryLink|Cards|rarity:Rare&color:Silent|Rare|2}}\n"
        "{{KW|Ironclad||2}}\n"
    )
    fields = parse_structured_fields(wikitext)
    assert fields["rarity"] == "Common"
    assert fields["character"] == "Silent"


def test_extract_mechanics_keeps_lead_kw_keywords():
    from tools.fetch_sts2_cards import extract_mechanics

    wikitext = (
        "{{C|Deflect||2}} gives 4 {{KW|Block||2}} and applies {{KW|Weak||2}}.\n"
        "== Update History ==\n"
    )
    assert extract_mechanics(wikitext) == ["block", "weak"]


def test_extract_mechanics_ignores_post_lead_sections():
    from tools.fetch_sts2_cards import extract_mechanics

    wikitext = (
        "Lead with {{KW|Block||2}}.\n"
        "== Update History ==\n"
        "{{KW|Goopy||2}} {{KW|Enchant||2}}\n"
        "== Related Cards ==\n"
        "{{KW|Orobas||2}}\n"
    )
    assert extract_mechanics(wikitext) == ["block"]


def test_extract_mechanics_excludes_character_keywords():
    from tools.fetch_sts2_cards import extract_mechanics

    wikitext = "{{KW|Silent||2}} card with {{KW|Block||2}} and {{KW|Ironclad||2}}."
    assert extract_mechanics(wikitext) == ["block"]


def test_extract_mechanics_dedups_and_preserves_order():
    from tools.fetch_sts2_cards import extract_mechanics

    wikitext = "{{KW|Block||2}} {{KW|Weak||2}} {{KW|Block||2}}"
    assert extract_mechanics(wikitext) == ["block", "weak"]
