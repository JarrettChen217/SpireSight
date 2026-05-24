from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

from spiresight.knowledge.models import (
    CardKnowledge,
    CardSearchHit,
    KnowledgeMetadata,
    KnowledgeStatus,
    normalize_query,
)

_log = logging.getLogger(__name__)

_FUZZY_THRESHOLD = 78
_KEYWORD_MIN_LEN = 3


class CardKnowledgeStore:
    def __init__(
        self,
        *,
        cards: tuple[CardKnowledge, ...],
        metadata: KnowledgeMetadata | None = None,
        status: KnowledgeStatus = "ready",
    ) -> None:
        self.cards = cards
        self.metadata = metadata or KnowledgeMetadata(card_count=len(cards))
        self.status: KnowledgeStatus = status
        self._name_index: dict[str, CardKnowledge] = {}
        self._alias_index: dict[str, CardKnowledge] = {}
        self._choices: dict[str, CardKnowledge] = {}
        for card in cards:
            name_norm = normalize_query(card.name_en)
            if name_norm:
                self._name_index[name_norm] = card
                self._choices[name_norm] = card
            for alias in card.aliases:
                alias_norm = normalize_query(alias)
                if alias_norm:
                    self._alias_index[alias_norm] = card
                    self._choices[alias_norm] = card

    @classmethod
    def from_dir(cls, path: Path) -> "CardKnowledgeStore":
        path = Path(path)
        cards_path = path / "cards.json"
        if not cards_path.exists():
            return cls(cards=(), status="missing_index")
        try:
            raw_cards = json.loads(cards_path.read_text(encoding="utf-8"))
            cards = tuple(CardKnowledge.model_validate(item) for item in raw_cards)
            metadata = _load_metadata(path / "metadata.json")
            aliases = _load_aliases(path / "zh_aliases.yaml")
            if aliases:
                cards = tuple(_with_extra_aliases(card, aliases.get(card.name_en, [])) for card in cards)
            return cls(cards=cards, metadata=metadata, status="ready")
        except Exception as exc:  # noqa: BLE001
            _log.warning("card knowledge index failed to load: %s", exc)
            return cls(cards=(), status="corrupt_index")

    def search_cards(self, query: str, *, limit: int = 5) -> list[CardSearchHit]:
        if self.status != "ready" or not self.cards:
            return []
        normalized = normalize_query(query)
        if not normalized:
            return []

        hits: list[CardSearchHit] = []
        seen: set[str] = set()

        for key, card in self._name_index.items():
            if _contains_term(normalized, key):
                hits.append(CardSearchHit(card=card, score=100, match_type="exact", matched=key))
                seen.add(card.id)
        for key, card in self._alias_index.items():
            if card.id not in seen and _contains_term(normalized, key):
                hits.append(CardSearchHit(card=card, score=98, match_type="alias", matched=key))
                seen.add(card.id)

        if len(hits) < limit:
            fuzzy_hits = process.extract(
                normalized,
                self._choices.keys(),
                scorer=fuzz.WRatio,
                limit=limit,
            )
            for matched, score, _ in fuzzy_hits:
                card = self._choices[matched]
                if score < _FUZZY_THRESHOLD or card.id in seen:
                    continue
                hits.append(
                    CardSearchHit(card=card, score=float(score), match_type="fuzzy", matched=matched)
                )
                seen.add(card.id)
                if len(hits) >= limit:
                    break

        if len(hits) < limit:
            for hit in self._keyword_hits(normalized):
                if hit.card.id in seen:
                    continue
                hits.append(hit)
                seen.add(hit.card.id)
                if len(hits) >= limit:
                    break

        return sorted(hits, key=lambda h: h.score, reverse=True)[:limit]

    def _keyword_hits(self, normalized: str) -> list[CardSearchHit]:
        terms = {t for t in normalized.split() if len(t) >= _KEYWORD_MIN_LEN}
        if not terms:
            return []
        hits: list[CardSearchHit] = []
        for card in self.cards:
            haystack = normalize_query(
                " ".join(
                    [
                        card.description,
                        card.upgraded_description or "",
                        " ".join(card.mechanics),
                        card.card_type or "",
                        card.rarity or "",
                    ]
                )
            )
            matched = terms.intersection(haystack.split())
            if matched:
                hits.append(
                    CardSearchHit(
                        card=card,
                        score=40 + len(matched),
                        match_type="keyword",
                        matched=", ".join(sorted(matched)),
                    )
                )
        return sorted(hits, key=lambda h: h.score, reverse=True)


def _load_metadata(path: Path) -> KnowledgeMetadata:
    if not path.exists():
        return KnowledgeMetadata()
    return KnowledgeMetadata.model_validate_json(path.read_text(encoding="utf-8"))


def _load_aliases(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): [str(a) for a in (v or [])] for k, v in raw.items()}


def _with_extra_aliases(card: CardKnowledge, aliases: list[str]) -> CardKnowledge:
    merged = list(dict.fromkeys([*card.aliases, *aliases]))
    return card.model_copy(update={"aliases": merged})


def _contains_term(query: str, term: str) -> bool:
    if not term:
        return False
    if term in query and (" " not in term or " " not in query):
        return True
    return query == term or f" {term} " in f" {query} "
