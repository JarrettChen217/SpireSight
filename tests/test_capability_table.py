from spiresight.llm.capabilities import Capability
from spiresight.llm.capability_table import (
    ASSUME_ALL_CAPS, KNOWN_MODEL_CAPS, infer_capabilities,
)


def test_known_model_table_only_valid_capabilities():
    valid = set(Capability)
    for mid, caps in KNOWN_MODEL_CAPS.items():
        assert caps.issubset(valid), f"{mid} has invalid capability"


def test_infer_capabilities_table_hit():
    caps, inferred = infer_capabilities("gpt-4o")
    assert Capability.VISION in caps
    assert inferred is False


def test_infer_capabilities_prefix_hit():
    caps, inferred = infer_capabilities("gpt-4o-2024-08-06")
    assert Capability.VISION in caps
    assert inferred is False


def test_infer_capabilities_miss_returns_assume_all():
    caps, inferred = infer_capabilities("totally-new-model-xyz")
    assert caps == ASSUME_ALL_CAPS
    assert inferred is True


def test_assume_all_caps_contains_every_capability():
    assert ASSUME_ALL_CAPS == frozenset(Capability)
