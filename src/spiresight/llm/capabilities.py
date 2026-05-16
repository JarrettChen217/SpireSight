# src/spiresight/llm/capabilities.py
from __future__ import annotations
from enum import StrEnum


class Capability(StrEnum):
    VISION = "vision"
    TOOL_USE = "tool_use"
    JSON_MODE = "json_mode"
    THINKING = "thinking"
