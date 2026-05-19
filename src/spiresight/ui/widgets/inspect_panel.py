"""Sidebar input widget for the multi-frame inspect flow.

Owns: the thumbnail strip showing currently-captured (but not yet
submitted) frames + the three buttons that drive the InspectSession
state machine. Emits the same three signals MainWindow already wires
(capture_requested / done_requested / clear_requested).

The previous RunStatePanel embedded both these controls AND the
state rendering; in the tabbed layout the rendering moves to
RunStateTab and only this input piece stays in the sidebar.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from spiresight.core.inspect_session import InspectSession
from spiresight.prompts.ui_locale import UILocale


class _Thumbnail(QFrame):
    remove_clicked = Signal(int)

    def __init__(
        self, png: bytes, index: int, tooltip: str, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._index = index
        self.setFixedSize(64, 36)
        self.setFrameShape(QFrame.Shape.Box)
        self.setStyleSheet("background-color: #2a2a2a; border: 1px solid #444;")

        pix = QPixmap()
        pix.loadFromData(png)
        scaled = pix.scaled(
            QSize(64, 36),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        img_label = QLabel(self)
        img_label.setPixmap(scaled)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_label.setGeometry(0, 0, 64, 36)

        x_btn = QPushButton("×", self)
        x_btn.setFixedSize(14, 14)
        x_btn.setStyleSheet(
            "QPushButton {background: rgba(0,0,0,0.7); color: white; "
            "border: none; font-weight: bold; font-size: 10px;} "
            "QPushButton:hover {background: #c84a4a;}"
        )
        x_btn.move(64 - 14, 0)
        x_btn.clicked.connect(lambda: self.remove_clicked.emit(self._index))

        self.setToolTip(tooltip)


class InspectPanel(QWidget):
    capture_requested = Signal()
    done_requested    = Signal()
    clear_requested   = Signal()

    def __init__(
        self,
        session: InspectSession,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._locale = locale
        self._capability_ok = True
        self._capability_tooltip = ""
        self._busy = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self._header_label = QLabel("Inspect")
        self._header_label.setProperty("role", "section-header")
        outer.addWidget(self._header_label)

        # thumbnail strip
        self._strip_scroll = QScrollArea()
        self._strip_scroll.setWidgetResizable(True)
        self._strip_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._strip_scroll.setFixedHeight(0)
        self._strip_host = QWidget()
        self._strip_layout = QHBoxLayout(self._strip_host)
        self._strip_layout.setContentsMargins(0, 0, 0, 0)
        self._strip_layout.setSpacing(4)
        self._strip_layout.addStretch(1)
        self._strip_scroll.setWidget(self._strip_host)
        outer.addWidget(self._strip_scroll)

        # buttons
        button_row = QHBoxLayout()
        self._capture_btn = QPushButton(locale.get("panel.capture"))
        self._capture_btn.setObjectName("primary")
        self._done_btn = QPushButton(locale.get("panel.done"))
        self._clear_btn = QPushButton(locale.get("panel.clear"))
        button_row.addWidget(self._capture_btn)
        button_row.addWidget(self._done_btn)
        button_row.addWidget(self._clear_btn)
        outer.addLayout(button_row)

        from spiresight.ui.widgets.inspect_controls import InspectButtonsController
        self._ctrl = InspectButtonsController(
            session, locale, self._capture_btn, self._done_btn, self._clear_btn, self,
        )
        self._ctrl.capture_clicked.connect(self.capture_requested.emit)
        self._ctrl.done_clicked.connect(self.done_requested.emit)
        self._ctrl.clear_clicked.connect(self.clear_requested.emit)

        session.changed.connect(self._refresh_thumbnails)
        locale.changed.connect(self._retranslate)
        self._refresh_thumbnails()

    # ── public control API ──
    def set_capture_enabled(self, enabled: bool, tooltip: str = "") -> None:
        self._capability_ok = enabled
        self._capability_tooltip = tooltip
        self._ctrl.set_capability(enabled, tooltip)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._ctrl.set_busy(busy)

    # ── internals ──
    def _refresh_thumbnails(self) -> None:
        while self._strip_layout.count():
            item = self._strip_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()

        frames = self._session.frames
        if not frames:
            self._strip_scroll.setFixedHeight(0)
            self._strip_layout.addStretch(1)
            return

        self._strip_scroll.setFixedHeight(44)
        for i, png in enumerate(frames):
            tip = self._locale.get("panel.frame_tooltip", n=i + 1)
            thumb = _Thumbnail(png, i, tip, parent=self._strip_host)
            thumb.remove_clicked.connect(self._session.remove_frame)
            self._strip_layout.addWidget(thumb)
        self._strip_layout.addStretch(1)

    def _retranslate(self) -> None:
        self._refresh_thumbnails()
