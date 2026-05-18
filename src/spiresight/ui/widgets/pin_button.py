# src/spiresight/ui/widgets/pin_button.py
"""Reusable pin / always-on-top toggle button.

Extracted from the inline pin logic in mini_bar.py so that the main
window and any future floating panel can share a single implementation.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QToolButton

from spiresight.ui.theme import icon_path


class PinButton(QToolButton):
    """Checkable tool button that toggles between pin_filled / pin_outline icons."""

    toggled = Signal(bool)

    def __init__(self, pinned: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(pinned)
        self.setIconSize(QSize(18, 18))
        self.setObjectName("pin-button")
        self._update_icon()
        self.clicked.connect(lambda: self.toggled.emit(self.isChecked()))
        self.clicked.connect(self._update_icon)

    def _update_icon(self) -> None:
        name = "pin_filled" if self.isChecked() else "pin_outline"
        self.setIcon(QIcon(icon_path(name)))
