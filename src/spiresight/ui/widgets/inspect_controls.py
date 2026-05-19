"""Inspect button group widgets + shared state controller.

`InspectButtonsController` owns the busy/capability/count state machine
for a triplet of buttons. `MiniInspectControls` is a compact widget for
the mini-bar (added in a later task). `_CountBadge` is a paint-event
overlay (added in a later task).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from spiresight.core.inspect_session import InspectSession
from spiresight.prompts.ui_locale import UILocale


class InspectButtonsController(QObject):
    """Owns enable/tooltip/text state for a (capture, done, clear) trio.

    Both `InspectPanel` (sidebar) and `MiniInspectControls` (mini-bar)
    construct one of these and inject their own button widgets.
    """

    capture_clicked = Signal()
    done_clicked    = Signal()
    clear_clicked   = Signal()

    def __init__(
        self,
        session: InspectSession,
        locale: UILocale,
        capture_btn: QAbstractButton,
        done_btn: QAbstractButton,
        clear_btn: QAbstractButton,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._locale = locale
        self._capture_btn = capture_btn
        self._done_btn = done_btn
        self._clear_btn = clear_btn
        self._capability_ok = True
        self._capability_tooltip = ""
        self._busy = False

        capture_btn.clicked.connect(self.capture_clicked.emit)
        done_btn.clicked.connect(self.done_clicked.emit)
        clear_btn.clicked.connect(self.clear_clicked.emit)

        # Store lambdas as attributes so PySide6 holds strong refs to them,
        # keeping this controller alive even without an external Python reference.
        self._on_session_changed = lambda: self.refresh()
        self._on_locale_changed = lambda: self.retranslate()
        session.changed.connect(self._on_session_changed)
        locale.changed.connect(self._on_locale_changed)
        self.retranslate()
        self.refresh()

    def set_capability(self, ok: bool, tooltip: str = "") -> None:
        self._capability_ok = ok
        self._capability_tooltip = tooltip
        self.refresh()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.refresh()

    def count(self) -> int:
        return self._session.count

    def refresh(self) -> None:
        loc = self._locale
        count = self._session.count
        at_cap = count >= InspectSession.MAX_FRAMES

        if self._busy:
            self._capture_btn.setEnabled(False)
            self._capture_btn.setToolTip("")
            self._done_btn.setEnabled(False)
            self._done_btn.setText(loc.get("panel.done_busy"))
            self._done_btn.setToolTip("")
            return

        self._done_btn.setText(loc.get("panel.done"))

        if not self._capability_ok:
            self._capture_btn.setEnabled(False)
            self._capture_btn.setToolTip(self._capability_tooltip)
            self._done_btn.setEnabled(False)
            self._done_btn.setToolTip(self._capability_tooltip)
            return

        if at_cap:
            self._capture_btn.setEnabled(False)
            self._capture_btn.setToolTip(
                loc.get("panel.max_frames", max=InspectSession.MAX_FRAMES)
            )
        else:
            self._capture_btn.setEnabled(True)
            self._capture_btn.setToolTip("")

        if count == 0:
            self._done_btn.setEnabled(False)
            self._done_btn.setToolTip(loc.get("panel.no_frames"))
        else:
            self._done_btn.setEnabled(True)
            self._done_btn.setToolTip("")

    def retranslate(self) -> None:
        loc = self._locale
        self._capture_btn.setText(loc.get("panel.capture"))
        self._done_btn.setText(
            loc.get("panel.done_busy") if self._busy else loc.get("panel.done")
        )
        self._clear_btn.setText(loc.get("panel.clear"))
        self.refresh()


class _CountBadge(QWidget):
    """Small numeric badge overlay painted on the top-right of its parent."""

    SIZE = 14

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._count = 0
        parent.installEventFilter(self)
        self._reposition()

    def set_count(self, n: int) -> None:
        if n != self._count:
            self._count = n
            self.update()

    def count(self) -> int:
        return self._count

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._reposition()
        return False

    def _reposition(self) -> None:
        p = self.parentWidget()
        if p is None:
            return
        self.move(p.width() - self.SIZE + 2, -2)
        self.raise_()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor("#d4a54a")))
        painter.setPen(QPen(QColor("#1a1408"), 1))
        painter.drawEllipse(0, 0, self.SIZE - 1, self.SIZE - 1)
        painter.setPen(QPen(QColor("#1a1408")))
        font = painter.font()
        font.setPixelSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self._count))


from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QHBoxLayout, QToolButton  # noqa: E402

from spiresight.ui.theme import icon_path  # noqa: E402


class MiniInspectControls(QWidget):
    """Compact 3-button inspect group for the mini-bar.

    Same semantics as `InspectPanel`'s button row, plus a numeric badge
    on the capture button reflecting `InspectSession.count`.
    """

    capture_requested = Signal()
    done_requested    = Signal()
    clear_requested   = Signal()

    def __init__(
        self, session: InspectSession, locale: UILocale, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("mini-inspect")

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        def _mk(obj_name: str, icon_name: str, fallback_text: str) -> QToolButton:
            b = QToolButton()
            b.setObjectName(obj_name)
            b.setFixedSize(28, 28)
            b.setIconSize(QSize(18, 18))
            icon = QIcon(icon_path(icon_name))
            if icon.isNull():
                b.setText(fallback_text)
            else:
                b.setIcon(icon)
            return b

        self._capture_btn = _mk("mini-inspect-capture", "inspect_capture", "\U0001f4f7")
        self._done_btn    = _mk("mini-inspect-done",    "inspect_done",    "✓")
        self._clear_btn   = _mk("mini-inspect-clear",   "inspect_clear",   "×")

        row.addWidget(self._capture_btn)
        row.addWidget(self._done_btn)
        row.addWidget(self._clear_btn)

        self._badge = _CountBadge(self._capture_btn)

        self._ctrl = InspectButtonsController(
            session, locale, self._capture_btn, self._done_btn, self._clear_btn, self,
        )
        self._ctrl.capture_clicked.connect(self.capture_requested.emit)
        self._ctrl.done_clicked.connect(self.done_requested.emit)
        self._ctrl.clear_clicked.connect(self.clear_requested.emit)

        session.changed.connect(self._refresh_badge)
        self._refresh_badge()

    def set_capability(self, ok: bool, tooltip: str = "") -> None:
        self._ctrl.set_capability(ok, tooltip)

    def set_busy(self, busy: bool) -> None:
        self._ctrl.set_busy(busy)

    def _refresh_badge(self) -> None:
        n = self._ctrl.count()
        self._badge.set_count(n)
        self._badge.setVisible(n > 0)
