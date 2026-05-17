"""Read-only tab that displays the latest RunState via RunStatePanel."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.run_state_store import RunStateStore
from spiresight.ui.widgets.run_state_panel import RunStatePanel


class RunStateTab(QWidget):
    def __init__(
        self,
        store: RunStateStore,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._panel = RunStatePanel(store, locale)
        layout.addWidget(self._panel)
