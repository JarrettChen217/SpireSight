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
