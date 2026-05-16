"""YAML-backed UI string lookup. Emits changed when language switches."""
from __future__ import annotations

from pathlib import Path

import yaml
from PySide6.QtCore import QObject, Signal


class UILocale(QObject):
    changed = Signal()

    def __init__(
        self,
        locales_dir: Path,
        language: str = "en",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._locales_dir = Path(locales_dir)
        self._language = language
        self._strings: dict[str, str] = {}
        self._load()

    def set_language(self, language: str) -> None:
        if language == self._language:
            return
        self._language = language
        self._load()
        self.changed.emit()

    def get(self, key: str, **kwargs: object) -> str:
        try:
            template = self._strings[key]
        except KeyError:
            raise KeyError(
                f"UI string key '{key}' not found in locale '{self._language}'"
            ) from None
        if kwargs:
            return template.format(**{k: str(v) for k, v in kwargs.items()})
        return template

    def __repr__(self) -> str:
        return f"UILocale(language='{self._language}')"

    def _load(self) -> None:
        path = self._locales_dir / self._language / "ui_strings.yaml"
        if not path.exists():
            path = self._locales_dir / "en" / "ui_strings.yaml"
        raw: dict = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self._strings.clear()
        self._flatten(raw, prefix="")

    def _flatten(self, data: dict, prefix: str) -> None:
        for k, v in data.items():
            full_key = f"{prefix}{k}" if prefix else k
            if isinstance(v, dict):
                self._flatten(v, f"{full_key}.")
            else:
                self._strings[full_key] = str(v)
