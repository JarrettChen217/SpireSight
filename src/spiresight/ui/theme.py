# src/spiresight/ui/theme.py
"""QSS loader and color tokens.

Tokens here must match the values in resources/qss/dark_fantasy.qss.
"""
from __future__ import annotations

from importlib import resources

COLORS = {
    "bg": "#1a1410",
    "panel": "#15100c",
    "border": "#4a3422",
    "text": "#d9b885",
    "muted": "#88715a",
    "accent": "#c8a878",
    "ember": "#a87838",
}


def load_qss(name: str = "dark_fantasy") -> str:
    return resources.files("spiresight.resources.qss").joinpath(f"{name}.qss").read_text(
        encoding="utf-8"
    )
