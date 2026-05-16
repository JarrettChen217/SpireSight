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


def ensure_dirs() -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    log_dir().mkdir(parents=True, exist_ok=True)
