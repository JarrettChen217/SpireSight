from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


KnowledgeStatus = Literal["ready", "missing_index", "corrupt_index"]
MatchType = Literal["exact", "alias", "fuzzy", "keyword"]


def normalize_query(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


class CardKnowledge(BaseModel):
    id: str
    name_en: str
    aliases: list[str] = Field(default_factory=list)
    character: str | None = None
    rarity: str | None = None
    card_type: str | None = None
    cost: str | None = None
    description: str
    upgraded_description: str | None = None
    mechanics: list[str] = Field(default_factory=list)
    source_name: str = ""
    source_url: str = ""
    fetched_at: datetime


class KnowledgeMetadata(BaseModel):
    source_name: str = ""
    source_urls: list[str] = Field(default_factory=list)
    fetched_at: datetime | None = None
    script_version: str = ""
    card_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class CardSearchHit(BaseModel):
    card: CardKnowledge
    score: float
    match_type: MatchType
    matched: str = ""
