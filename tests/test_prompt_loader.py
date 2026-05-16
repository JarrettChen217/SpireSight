import pytest
from spiresight.llm.capabilities import Capability
from spiresight.prompts.loader import PromptLoader, PromptReferenceError


def _write(p, name, text):
    f = p / name
    f.write_text(text, encoding="utf-8")
    return f


def test_loads_system_prompts(tmp_path):
    _write(tmp_path, "system_prompts.yaml", """
- id: sts_expert
  description: Expert
  content: |
    You are an expert.
""")
    (tmp_path / "locales" / "en").mkdir(parents=True)
    _write(tmp_path / "locales" / "en", "quick_actions.yaml", """
- id: card
  label: Cards
  system_prompt_id: sts_expert
  user_template: "Pick the card. {custom_text}"
  requires_screenshot: true
  required_capabilities: [VISION]
""")
    loader = PromptLoader(tmp_path)
    loader.reload(language="en")
    sp = loader.get_system_prompt("sts_expert")
    assert "expert" in sp.content.lower()
    qa = loader.get_quick_action("card")
    assert qa.label == "Cards"
    assert qa.required_capabilities == [Capability.VISION]
    assert "{custom_text}" in qa.user_template


def test_quick_actions_listed_in_order(tmp_path):
    _write(tmp_path, "system_prompts.yaml", "- id: s\n  description: ''\n  content: x\n")
    (tmp_path / "locales" / "en").mkdir(parents=True)
    _write(tmp_path / "locales" / "en", "quick_actions.yaml", """
- {id: a, label: A, system_prompt_id: s, user_template: "{custom_text}", required_capabilities: []}
- {id: b, label: B, system_prompt_id: s, user_template: "{custom_text}", required_capabilities: []}
""")
    loader = PromptLoader(tmp_path)
    loader.reload(language="en")
    assert [q.id for q in loader.quick_actions()] == ["a", "b"]


def test_dangling_system_prompt_reference_raises(tmp_path):
    _write(tmp_path, "system_prompts.yaml", "- id: s\n  description: ''\n  content: x\n")
    (tmp_path / "locales" / "en").mkdir(parents=True)
    _write(tmp_path / "locales" / "en", "quick_actions.yaml", """
- {id: a, label: A, system_prompt_id: missing, user_template: "{custom_text}", required_capabilities: []}
""")
    loader = PromptLoader(tmp_path)
    with pytest.raises(PromptReferenceError):
        loader.reload(language="en")


def test_locale_fallback_to_english(tmp_path):
    _write(tmp_path, "system_prompts.yaml", "- id: s\n  description: ''\n  content: x\n")
    (tmp_path / "locales" / "en").mkdir(parents=True)
    _write(tmp_path / "locales" / "en", "quick_actions.yaml", """
- {id: a, label: A, system_prompt_id: s, user_template: "{custom_text}", required_capabilities: []}
""")
    loader = PromptLoader(tmp_path)
    loader.reload(language="zh")  # zh dir doesn't exist
    assert loader.get_quick_action("a").label == "A"
