# src/spiresight/config/paths.py
"""Cross-platform config and log directory resolution.

Resolution order:
  1. SPIRESIGHT_CONFIG_DIR env var (dev override)
  2. macOS:   ~/Library/Application Support/SpireSight
  3. Windows: %APPDATA%/SpireSight
  4. Linux:   $XDG_CONFIG_HOME/SpireSight or ~/.config/SpireSight
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "SpireSight"


def _platform() -> str:
    return sys.platform


def config_dir() -> Path:
    override = os.environ.get("SPIRESIGHT_CONFIG_DIR")
    if override:
        return Path(override)
    plat = _platform()
    if plat == "darwin":
        return Path(os.environ["HOME"]) / "Library" / "Application Support" / APP_NAME
    if plat == "win32":
        return Path(os.environ["APPDATA"]) / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path(os.environ["HOME"]) / ".config"
    return base / APP_NAME


def config_file() -> Path:
    return config_dir() / "config.json"


def log_dir() -> Path:
    return config_dir() / "logs"


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return here.parents[3]


def card_knowledge_dir() -> Path:
    override = os.environ.get("SPIRESIGHT_CARD_KNOWLEDGE_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "data" / "sts2_cards"
    return repo_root() / "data" / "sts2_cards"


def ensure_dirs() -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    log_dir().mkdir(parents=True, exist_ok=True)
