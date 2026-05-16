# tests/test_capabilities.py
from spiresight.llm.capabilities import Capability
from spiresight.llm.models import ModelInfo


def test_capability_string_values():
    assert Capability.VISION == "vision"
    assert Capability.TOOL_USE == "tool_use"
    assert Capability.JSON_MODE == "json_mode"
    assert Capability.THINKING == "thinking"


def test_modelinfo_is_hashable_and_frozen():
    m = ModelInfo(
        id="gpt-4o",
        display_name="GPT-4o",
        capabilities=frozenset({Capability.VISION, Capability.TOOL_USE}),
        context_window=128_000,
    )
    assert hash(m)
    assert Capability.VISION in m.capabilities


def test_modelinfo_has_capability_helper():
    m = ModelInfo(
        id="gpt-3.5",
        display_name="GPT-3.5",
        capabilities=frozenset(),
        context_window=16_000,
    )
    assert not m.has(Capability.VISION)
