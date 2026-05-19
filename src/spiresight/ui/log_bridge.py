"""Pipe Python `logging` records into LogsTab via a Qt signal.

This lets any module in the app call `_log.info(...)` and have the message
appear in the in-app Logs tab, alongside the existing request/cost rows.
Use sparingly — LogsTab caps at 200 rows.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal


class LogBridge(QObject):
    """Single instance owned by MainWindow. Emits formatted log records."""
    record_emitted = Signal(str)


class BridgeHandler(logging.Handler):
    """Pushes each log record onto the bridge's signal. Thread-safe because
    Qt queues cross-thread signal emissions automatically."""
    def __init__(self, bridge: LogBridge, level: int = logging.INFO) -> None:
        super().__init__(level=level)
        self._bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._bridge.record_emitted.emit(self.format(record))
        except Exception:
            self.handleError(record)


def install_bridge(bridge: LogBridge, *, logger_name: str = "spiresight",
                   level: int = logging.INFO) -> BridgeHandler:
    """Attach a BridgeHandler to the named logger. Returns the handler."""
    handler = BridgeHandler(bridge, level=level)
    # Short format — LogsTab adds its own timestamp prefix
    handler.setFormatter(logging.Formatter("%(name)s — %(message)s"))
    logging.getLogger(logger_name).addHandler(handler)
    return handler
