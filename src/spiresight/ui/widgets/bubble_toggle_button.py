"""Checkable mini-bar button mirroring the InfoBubble's visibility."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QToolButton

from spiresight.ui.theme import icon_path


class BubbleToggleButton(QToolButton):
    # Uses QAbstractButton's inherited toggled(bool) signal — fires automatically
    # on checked-state changes; no need for a custom signal or manual emit.

    def __init__(self, visible: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(visible)
        self.setObjectName("bubble-toggle")
        self.setIconSize(QSize(18, 18))
        self.setFixedSize(28, 28)
        self.setToolTip("Toggle response bubble")
        self._update_icon()
        self.clicked.connect(self._update_icon)

    def set_visible_state(self, visible: bool) -> None:
        if self.isChecked() == visible:
            return
        self.blockSignals(True)
        self.setChecked(visible)
        self.blockSignals(False)
        self._update_icon()

    def _update_icon(self) -> None:
        name = "bubble_filled" if self.isChecked() else "bubble_outline"
        path = Path(icon_path(name))
        if not path.is_file():
            self.setIcon(QIcon())
            self.setText("\U0001f4ac")  # 💬 fallback while SVG assets are absent
            return
        self.setText("")
        self.setIcon(QIcon(str(path)))
