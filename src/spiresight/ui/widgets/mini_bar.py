# src/spiresight/ui/widgets/mini_bar.py
"""Always-on-top compact bar with quick-action buttons, inspect group,
hotkey hint, and bubble/pin/expand controls."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from spiresight.core.inspect_session import InspectSession
from spiresight.prompts.loader import PromptLoader
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.theme import icon_path
from spiresight.ui.widgets.bubble_toggle_button import BubbleToggleButton
from spiresight.ui.widgets.inspect_controls import MiniInspectControls
from spiresight.ui.widgets.pin_button import PinButton


def _vsep() -> QFrame:
    s = QFrame()
    s.setObjectName("mini-bar-sep")
    s.setFrameShape(QFrame.Shape.VLine)
    s.setFixedWidth(1)
    return s


class MiniBar(QWidget):
    action_clicked            = Signal(str)
    expand_requested          = Signal()
    moved                     = Signal(QPoint)
    pin_toggled               = Signal(bool)
    bubble_toggle_requested   = Signal(bool)
    inspect_capture_requested = Signal()
    inspect_done_requested    = Signal()
    inspect_clear_requested   = Signal()

    def __init__(
        self,
        loader: PromptLoader,
        hotkey_hint: str,
        *,
        inspect_session: InspectSession,
        locale: UILocale,
        pinned: bool = True,
        bubble_visible: bool = False,
        parent=None,
    ) -> None:
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

        row.addWidget(_vsep())

        self._inspect = MiniInspectControls(inspect_session, locale, self)
        self._inspect.capture_requested.connect(self.inspect_capture_requested.emit)
        self._inspect.done_requested.connect(self.inspect_done_requested.emit)
        self._inspect.clear_requested.connect(self.inspect_clear_requested.emit)
        row.addWidget(self._inspect)

        row.addWidget(_vsep())
        row.addWidget(QLabel(hotkey_hint))
        row.addStretch(1)

        self._bubble_btn = BubbleToggleButton(visible=bubble_visible)
        self._bubble_btn.toggled.connect(self.bubble_toggle_requested.emit)
        row.addWidget(self._bubble_btn)

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

    def set_bubble_visible(self, visible: bool) -> None:
        self._bubble_btn.set_visible_state(visible)

    def set_inspect_capability(self, ok: bool, tooltip: str = "") -> None:
        self._inspect.set_capability(ok, tooltip)

    def set_inspect_busy(self, busy: bool) -> None:
        self._inspect.set_busy(busy)

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
