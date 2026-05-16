# src/spiresight/core/request.py
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class InferenceRequest:
    prompt_id: str
    custom_text: str
    include_screenshot: bool
