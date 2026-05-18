# src/spiresight/core/request.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuickActionRequest:
    prompt_id: str
    custom_text: str
    include_screenshot: bool


@dataclass(frozen=True)
class FollowUpRequest:
    user_text: str
    include_screenshot: bool = False
    recapture: bool = False
