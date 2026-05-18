# src/spiresight/ui/widgets/mini_bar.py
"""Always-on-top compact bar with quick-action buttons.

Frameless, draggable. Emits the same action_clicked(action_id) signal
as the main PromptPanel so a single handler covers both.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from spiresight.prompts.loader import PromptLoader
from spiresight.ui.theme import icon_path
from spiresight.ui.widgets.pin_button import PinButton


class MiniBar(QWidget):
    action_clicked = Signal(str)
    expand_requested = Signal()
    moved = Signal(QPoint)          # NEW
    pin_toggled = Signal(bool)      # NEW

    def __init__(self, loader: PromptLoader, hotkey_hint: str, *,
                 pinned: bool = True, parent=None) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if pinned:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._drag_offset: QPoint | None = None
        self._pinned = pinned

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)
        for qa in loader.quick_actions():
            btn = QPushButton(qa.label)
            btn.setIcon(QIcon(icon_path(qa.id)))
            btn.setIconSize(QSize(18, 18))
            btn.clicked.connect(lambda _=False, aid=qa.id: self.action_clicked.emit(aid))
            row.addWidget(btn)
        row.addWidget(QLabel(hotkey_hint))

        self._pin_btn = PinButton(pinned=pinned)
        self._pin_btn.setToolTip("Always on top")
        self._pin_btn.toggled.connect(self._on_pin_toggled)
        row.addWidget(self._pin_btn)

        expand = QPushButton("▭")
        expand.setToolTip("Expand to main window")
        expand.clicked.connect(self.expand_requested.emit)
        row.addWidget(expand)

    @property
    def is_pinned(self) -> bool:
        return self._pin_btn.isChecked()

    def set_pinned(self, pinned: bool) -> None:
        self._pin_btn.setChecked(pinned)

    def _on_pin_toggled(self, pinned: bool) -> None:
        self._pinned = pinned
        geo = self.geometry()
        flags = self.windowFlags()
        if pinned:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setGeometry(geo)
        self.show()
        self.pin_toggled.emit(pinned)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            self.moved.emit(self.pos())

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._drag_offset = None
