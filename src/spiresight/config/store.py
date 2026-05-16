# src/spiresight/config/store.py
"""Atomic JSON-backed config store.

NOTE(security): keys are plaintext in MVP. See schema.py docstring.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import ValidationError

from . import paths
from .schema import AppConfig

log = logging.getLogger(__name__)


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or paths.config_file()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AppConfig:
        if not self._path.exists():
            return AppConfig()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("config.json is corrupt; using defaults")
            return AppConfig()
        try:
            return AppConfig(**raw)
        except ValidationError as exc:
            log.warning("config.json failed validation (%s); using defaults", exc)
            return AppConfig()

    def save(self, cfg: AppConfig) -> None:
        paths.ensure_dirs()
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self._path)
