"""Single place to configure logging for the app and CLI entry."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from spiresight.config import paths


def configure_logging(level: int = logging.INFO) -> None:
    paths.ensure_dirs()
    root = logging.getLogger()
    root.setLevel(level)
    # avoid duplicate handlers on hot-reload
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s")
    file_h = RotatingFileHandler(
        paths.log_dir() / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8",
    )
    file_h.setFormatter(fmt)
    root.addHandler(file_h)
    stream_h = logging.StreamHandler()
    stream_h.setFormatter(fmt)
    root.addHandler(stream_h)
