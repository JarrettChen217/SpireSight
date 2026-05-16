from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Usefulness = Literal["skip", "situational", "good", "key"]
Rarity = Literal["starter", "common", "uncommon", "rare"]
Confidence = Literal["low", "medium", "high"]

_USEFULNESS_ORDER: tuple[Usefulness, ...] = ("key", "good", "situational", "skip")


class Card(BaseModel):
    name: str
    count: int = 1
    rarity: Rarity
    usefulness: Usefulness
    note: str = ""


class Relic(BaseModel):
    name: str
    synergy_tags: list[str] = Field(default_factory=list)


class ArchetypeCandidate(BaseModel):
    name: str
    confidence: Confidence
    rationale: str = ""


class RunState(BaseModel):
    cards: list[Card]
    relics: list[Relic]
    potions: list[str]
    archetype_candidates: list[ArchetypeCandidate]
    overall_eval: str
    inspected_at: datetime

    def to_prompt_block(self) -> str:
        lines: list[str] = ["## Current Run Context"]

        if self.archetype_candidates:
            arches = " / ".join(
                f"{a.name} ({a.confidence})" for a in self.archetype_candidates
            )
            lines.append(f"Archetype: {arches}")

        if self.cards:
            grouped: dict[str, list[str]] = {u: [] for u in _USEFULNESS_ORDER}
            for c in self.cards:
                label = c.name if c.count == 1 else f"{c.name} x{c.count}"
                grouped[c.usefulness].append(label)
            for tier in _USEFULNESS_ORDER:
                if not grouped[tier]:
                    continue
                heading = {
                    "key": "Key cards",
                    "good": "Solid",
                    "situational": "Situational",
                    "skip": "Filler",
                }[tier]
                lines.append(f"{heading}: {', '.join(grouped[tier])}")

        if self.relics:
            relic_strs = [
                f"{r.name} ({', '.join(r.synergy_tags)})" if r.synergy_tags else r.name
                for r in self.relics
            ]
            lines.append(f"Relics: {', '.join(relic_strs)}")

        if self.potions:
            lines.append(f"Potions: {', '.join(self.potions)}")

        if self.overall_eval.strip():
            lines.append(f"Eval: {self.overall_eval.strip()}")

        return "\n".join(lines)
