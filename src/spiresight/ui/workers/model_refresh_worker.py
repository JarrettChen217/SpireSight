"""Fetches a provider's remote model list off the UI thread."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from spiresight.llm.provider import LLMProvider


class ModelRefreshWorker(QThread):
    """Fetches `provider.fetch_remote_models()` and emits the result.

    Always emits exactly one of `succeeded` or `failed`. UI consumers
    should also connect to `finished` for "set busy back to false".
    """

    succeeded = Signal(str, list)      # provider_name, list[ModelInfo]
    failed = Signal(str, object)        # provider_name, Exception

    def __init__(self, provider_name: str, provider: LLMProvider, parent=None) -> None:
        super().__init__(parent)
        self._name = provider_name
        self._provider = provider

    def run(self) -> None:
        try:
            models = self._provider.fetch_remote_models()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self._name, exc)
            return
        self.succeeded.emit(self._name, models)
