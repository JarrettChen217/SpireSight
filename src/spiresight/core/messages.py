from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    text: str
    image_png: bytes | None = None
