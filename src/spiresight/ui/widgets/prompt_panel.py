# src/spiresight/ui/widgets/prompt_panel.py
"""Vertical list of quick-action buttons.

Emits action_clicked(action_id).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from spiresight.prompts.loader import PromptLoader
from spiresight.ui.theme import icon_path


class PromptPanel(QWidget):
    action_clicked = Signal(str)

    def __init__(self, loader: PromptLoader, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("prompt-panel")
        self._loader = loader
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._header = QLabel("Quick Actions")
        self._layout.addWidget(self._header)
        self.rebuild()

    def rebuild(self) -> None:
        while self._layout.count() > 1:
            item = self._layout.takeAt(1)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for qa in self._loader.quick_actions():
            btn = QPushButton(f"  {qa.label}")
            btn.setProperty("role", "quick-action")
            btn.setIcon(QIcon(icon_path(qa.id)))
            btn.setIconSize(QSize(20, 20))
            btn.clicked.connect(lambda _=False, aid=qa.id: self.action_clicked.emit(aid))
            self._layout.addWidget(btn)
        self._layout.addStretch(1)
