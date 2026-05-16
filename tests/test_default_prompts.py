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
