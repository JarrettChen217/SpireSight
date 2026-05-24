from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from spiresight.knowledge.card_store import CardKnowledgeStore
from spiresight.knowledge.models import CardSearchHit

KnowledgeGatewayMode = Literal["auto", "on", "off"]
KnowledgeGatewayStatus = Literal["disabled", "skipped", "missing_index", "hit", "no_hits"]

_CARD_ACTION_ID = "card_selection"
_PROMPT_BUDGET = 1800


class KnowledgeGatewayResult(BaseModel):
    injected: bool = False
    status: KnowledgeGatewayStatus
    prompt_block: str = ""
    hits: list[str] = Field(default_factory=list)


class KnowledgeGateway:
    def __init__(self, store: CardKnowledgeStore) -> None:
        self._store = store

    def evaluate(
        self,
        *,
        action_id: str,
        mode: KnowledgeGatewayMode,
        user_text: str,
        limit: int = 5,
    ) -> KnowledgeGatewayResult:
        if mode == "off":
            return KnowledgeGatewayResult(status="disabled")
        if action_id != _CARD_ACTION_ID:
            return KnowledgeGatewayResult(status="skipped")
        if self._store.status != "ready":
            return KnowledgeGatewayResult(status="missing_index")

        hits = self._store.search_cards(user_text, limit=limit)
        if not hits:
            return KnowledgeGatewayResult(status="no_hits")
        block = _format_prompt_block(hits)
        return KnowledgeGatewayResult(
            injected=bool(block),
            status="hit" if block else "no_hits",
            prompt_block=block,
            hits=[h.card.name_en for h in hits if h.card.name_en],
        )


def _format_prompt_block(hits: list[CardSearchHit]) -> str:
    lines = [
        "## Card Knowledge Context",
        "Use these cached card facts when evaluating the offered cards. "
        "Prefer the screenshot if it clearly shows a newer patch description.",
        "",
    ]
    for hit in hits:
        card = hit.card
        bits = [card.character, card.rarity, card.card_type]
        if card.cost:
            bits.append(f"cost {card.cost}")
        header = ", ".join(b for b in bits if b)
        entry = f"- {card.name_en}"
        if header:
            entry += f" [{header}]"
        entry += f": {card.description}"
        if card.upgraded_description:
            entry += f"\n  Upgrade: {card.upgraded_description}"
        source = card.source_name or "local cache"
        fetched = card.fetched_at.date().isoformat()
        entry += f"\n  Source: {source}, fetched {fetched}"
        candidate = "\n".join([*lines, entry])
        if len(candidate) > _PROMPT_BUDGET:
            break
        lines.append(entry)
    return "\n".join(lines).strip() if len(lines) > 3 else ""
