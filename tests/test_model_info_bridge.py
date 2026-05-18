from spiresight.config.schema import ModelInfoDict
from spiresight.llm.capabilities import Capability
from spiresight.llm.models import ModelInfo


def test_to_dict_then_from_dict_roundtrip():
    info = ModelInfo(
        id="gpt-4o",
        display_name="GPT-4o",
        capabilities=frozenset({Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE}),
        context_window=128_000,
    )
    d = info.to_dict()
    assert isinstance(d, ModelInfoDict)
    assert set(d.capabilities) == {"vision", "tool_use", "json_mode"}
    info2 = ModelInfo.from_dict(d)
    assert info2 == info


def test_from_dict_empty_capabilities():
    d = ModelInfoDict(id="x", display_name="X")
    info = ModelInfo.from_dict(d)
    assert info.capabilities == frozenset()
    assert info.context_window == 0
