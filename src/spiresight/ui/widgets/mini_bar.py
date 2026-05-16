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


class MiniBar(QWidget):
    action_clicked = Signal(str)
    expand_requested = Signal()

    def __init__(self, loader: PromptLoader, hotkey_hint: str, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._drag_offset: QPoint | None = None

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

        self._pin_btn = QPushButton()
        self._pin_btn.setCheckable(True)
        self._pin_btn.setChecked(True)
        self._pin_btn.setIconSize(QSize(18, 18))
        self._pin_btn.setToolTip("Always on top")
        self._pin_btn.setFixedSize(28, 24)
        self._pin_btn.clicked.connect(self._toggle_pin)
        self._update_pin_icon()
        row.addWidget(self._pin_btn)

        expand = QPushButton("▭")
        expand.setToolTip("Expand to main window")
        expand.clicked.connect(self.expand_requested.emit)
        row.addWidget(expand)

    def _toggle_pin(self) -> None:
        flags = self.windowFlags()
        if flags & Qt.WindowType.WindowStaysOnTopHint:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        self._update_pin_icon()
        self.show()

    def _update_pin_icon(self) -> None:
        on_top = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        icon_name = "pin_filled" if on_top else "pin_outline"
        self._pin_btn.setIcon(QIcon(icon_path(icon_name)))

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._drag_offset = None
