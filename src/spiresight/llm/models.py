# src/spiresight/llm/models.py
from __future__ import annotations
from dataclasses import dataclass

from .capabilities import Capability


@dataclass(frozen=True)
class ModelInfo:
    id: str
    display_name: str
    capabilities: frozenset[Capability]
    context_window: int

    def has(self, cap: Capability) -> bool:
        return cap in self.capabilities

    @classmethod
    def from_dict(cls, d) -> "ModelInfo":
        from spiresight.config.schema import ModelInfoDict   # lazy import
        if not isinstance(d, ModelInfoDict):
            raise TypeError(f"expected ModelInfoDict, got {type(d).__name__}")
        return cls(
            id=d.id,
            display_name=d.display_name,
            capabilities=frozenset(Capability(c) for c in d.capabilities),
            context_window=d.context_window,
        )

    def to_dict(self):
        from spiresight.config.schema import ModelInfoDict   # lazy import
        return ModelInfoDict(
            id=self.id,
            display_name=self.display_name,
            capabilities=[c.value for c in self.capabilities],
            context_window=self.context_window,
        )
