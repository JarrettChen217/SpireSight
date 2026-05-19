# src/spiresight/ui/theme.py
"""QSS loader, color tokens, and icon paths.

Tokens here must match the values in resources/qss/dark_fantasy.qss.
"""
from __future__ import annotations

import sys
from importlib import resources
from pathlib import Path

COLORS = {
    "bg": "#090c12",
    "panel": "#0d1018",
    "border": "#1d2233",
    "text": "#d5cebf",
    "muted": "#6e7a89",
    "accent": "#d4a54a",
    "ember": "#d4743a",
}

# Color tokens for the UsageBar status light and LogsTab cost rows.
# The current QSS is dark-themed only, so we ship one palette. If a
# light theme is ever added, swap these via a theme-aware lookup.
USAGE_COLORS = {
    "cost_tag": "#7ee2a8",        # green-300, used for "[cost]" prefix in LogsTab
    "light_idle": "#6b7280",      # gray-500
    "light_running": "#fbbf24",   # amber-400
    "light_ok": "#4ade80",        # green-400
    "light_error": "#f87171",     # red-400
    "log_sent": "#888888",
    "log_ok": "",
    "log_error": "#d65a5a",
    "log_cancelled": "#666666",
}


def load_qss(name: str = "dark_fantasy") -> str:
    return resources.files("spiresight.resources.qss").joinpath(f"{name}.qss").read_text(
        encoding="utf-8"
    )


def icon_path(name: str) -> str:
    """Absolute path to a named SVG icon in resources/icons/."""
    return str(
        resources.files("spiresight.resources.icons").joinpath(f"{name}.svg")
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def app_icon_path() -> str | None:
    """RGBA PNG for QIcon / NSApplication (squircle baked in). Bundled .app on macOS: None."""
    icons_dir = _repo_root() / "packaging" / "icons"

    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            return None
        base = Path(getattr(sys, "_MEIPASS", ""))
        for name in ("app_icon_512.png", "icon.ico"):
            candidate = base / "spiresight" / "resources" / name
            if candidate.is_file():
                return str(candidate)
        return None

    dock_png = icons_dir / "app_icon_512.png"
    if dock_png.is_file():
        return str(dock_png)
    return None
