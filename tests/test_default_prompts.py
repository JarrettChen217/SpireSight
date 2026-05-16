# tests/test_default_prompts.py
from pathlib import Path
from spiresight.prompts.loader import PromptLoader

REPO = Path(__file__).resolve().parents[1]
PROMPTS = REPO / "prompts"


def test_default_prompts_load_en():
    loader = PromptLoader(PROMPTS)
    loader.reload(language="en")
    ids = [qa.id for qa in loader.quick_actions()]
    for required in ("card_selection", "combat_strategy", "pathfinding", "relic_analysis"):
        assert required in ids


def test_default_prompts_load_zh():
    loader = PromptLoader(PROMPTS)
    loader.reload(language="zh")
    # zh must define the same ids
    assert {qa.id for qa in loader.quick_actions()} >= {
        "card_selection", "combat_strategy", "pathfinding", "relic_analysis",
    }


def test_sts_inspector_prompt_present_and_demands_json():
    loader = PromptLoader(PROMPTS)
    loader.reload(language="en")
    sp = loader.get_system_prompt("sts_inspector")
    assert "JSON" in sp.content
    assert "cards" in sp.content
    assert "archetype_candidates" in sp.content


def test_sts_expert_mentions_run_context():
    loader = PromptLoader(PROMPTS)
    loader.reload(language="en")
    sp = loader.get_system_prompt("sts_expert")
    assert "Current Run Context" in sp.content
