from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from spiresight.core.inspect_session import InspectSession
from spiresight.core.run_state import RunState
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.run_state_store import RunStateStore

_USEFULNESS_COLORS = {
    "key":         "#d4a54a",
    "good":        "#6bb5e8",
    "situational": "#d5cebf",
    "skip":        "#6e7a89",
}

_RARITY_GLYPHS = {
    "starter":  "○",
    "common":   "●",
    "uncommon": "◆",
    "rare":     "◆",
}


class _Thumbnail(QFrame):
    """A small framed thumbnail with an × removal button overlay."""
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


class RunStatePanel(QWidget):
    capture_requested = Signal()
    done_requested    = Signal()
    clear_requested   = Signal()

    def __init__(
        self,
        store: RunStateStore,
        session: InspectSession,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._session = session
        self._locale = locale
        self._capability_ok = True
        self._capability_tooltip = ""
        self._busy = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self._header_label = QLabel(locale.get("panel.header"))
        self._header_label.setProperty("role", "section-header")
        outer.addWidget(self._header_label)

        # ── thumbnail strip (horizontally scrollable) ────────────
        self._strip_scroll = QScrollArea()
        self._strip_scroll.setWidgetResizable(True)
        self._strip_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._strip_scroll.setFixedHeight(0)  # hidden when empty
        self._strip_host = QWidget()
        self._strip_layout = QHBoxLayout(self._strip_host)
        self._strip_layout.setContentsMargins(0, 0, 0, 0)
        self._strip_layout.setSpacing(4)
        self._strip_layout.addStretch(1)
        self._strip_scroll.setWidget(self._strip_host)
        outer.addWidget(self._strip_scroll)

        # ── button row ──────────────────────────────────────────
        button_row = QHBoxLayout()
        self._capture_btn = QPushButton(locale.get("panel.capture"))
        self._capture_btn.setObjectName("primary")
        self._capture_btn.clicked.connect(self.capture_requested.emit)
        self._done_btn = QPushButton(locale.get("panel.done"))
        self._done_btn.clicked.connect(self.done_requested.emit)
        self._clear_btn = QPushButton(locale.get("panel.clear"))
        self._clear_btn.clicked.connect(self.clear_requested.emit)
        button_row.addWidget(self._capture_btn)
        button_row.addWidget(self._done_btn)
        button_row.addWidget(self._clear_btn)
        outer.addLayout(button_row)

        # ── state content (existing rendering, scrollable) ──────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._content_host = QWidget()
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(4)
        self._scroll.setWidget(self._content_host)
        outer.addWidget(self._scroll, stretch=1)

        store.changed.connect(self._render)
        session.changed.connect(self._refresh_thumbnails)
        locale.changed.connect(self._retranslate)
        self._refresh_thumbnails()
        self._retranslate()

    # ── public control API ──────────────────────────────────────

    def set_capture_enabled(self, enabled: bool, tooltip: str = "") -> None:
        self._capability_ok = enabled
        self._capability_tooltip = tooltip
        self._update_button_states()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_button_states()

    # ── thumbnail strip ─────────────────────────────────────────

    def _refresh_thumbnails(self) -> None:
        # clear existing
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
            self._update_button_states()
            return

        self._strip_scroll.setFixedHeight(44)
        for i, png in enumerate(frames):
            tip = self._locale.get("panel.frame_tooltip", n=i + 1)
            thumb = _Thumbnail(png, i, tip, parent=self._strip_host)
            thumb.remove_clicked.connect(self._session.remove_frame)
            self._strip_layout.addWidget(thumb)
        self._strip_layout.addStretch(1)
        self._update_button_states()

    # ── button state machine ────────────────────────────────────

    def _update_button_states(self) -> None:
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

    # ── state rendering (unchanged behavior) ────────────────────

    def _clear_content(self) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()

    def _retranslate(self) -> None:
        loc = self._locale
        self._header_label.setText(loc.get("panel.header"))
        self._capture_btn.setText(loc.get("panel.capture"))
        self._done_btn.setText(
            loc.get("panel.done_busy") if self._busy else loc.get("panel.done")
        )
        self._clear_btn.setText(loc.get("panel.clear"))
        self._re_render()
        self._refresh_thumbnails()
        self._update_button_states()

    def _re_render(self) -> None:
        self._render(self._store.get())

    def _render(self, state: RunState | None) -> None:
        self._clear_content()
        loc = self._locale
        if state is None:
            empty = QLabel(loc.get("panel.empty_hint"))
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #6e7a89;")
            self._content_layout.addWidget(empty)
            self._content_layout.addStretch(1)
            return

        if state.archetype_candidates:
            self._content_layout.addWidget(self._subheader(loc.get("panel.archetype")))
            for a in state.archetype_candidates:
                self._content_layout.addWidget(
                    self._line(f"● {a.name} ({a.confidence})",
                               color=_USEFULNESS_COLORS["key"]
                               if a.confidence == "high" else None)
                )

        if state.cards:
            total = sum(c.count for c in state.cards)
            self._content_layout.addWidget(
                self._subheader(loc.get("panel.cards", total=total))
            )
            ordered = sorted(
                state.cards,
                key=lambda c: ("key", "good", "situational", "skip").index(c.usefulness),
            )
            for c in ordered:
                glyph = _RARITY_GLYPHS.get(c.rarity, "●")
                label = c.name if c.count == 1 else f"{c.name} x{c.count}"
                text = f"{glyph} {label}"
                if c.note:
                    text += f"  — {c.note}"
                self._content_layout.addWidget(
                    self._line(text, color=_USEFULNESS_COLORS.get(c.usefulness))
                )

        if state.relics:
            self._content_layout.addWidget(self._subheader(loc.get("panel.relics")))
            relic_text = " · ".join(r.name for r in state.relics)
            relic_label = QLabel(relic_text)
            relic_label.setWordWrap(True)
            self._content_layout.addWidget(relic_label)

        if state.potions:
            self._content_layout.addWidget(self._subheader(loc.get("panel.potions")))
            self._content_layout.addWidget(QLabel(" · ".join(state.potions)))

        if state.overall_eval.strip():
            self._content_layout.addWidget(self._subheader(loc.get("panel.eval")))
            eval_label = QLabel(state.overall_eval.strip())
            eval_label.setWordWrap(True)
            eval_label.setStyleSheet("color: #d5cebf;")
            self._content_layout.addWidget(eval_label)

        self._content_layout.addStretch(1)

    @staticmethod
    def _subheader(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #6e7a89; font-size: 10px; "
                          "text-transform: uppercase; margin-top: 4px;")
        return lbl

    @staticmethod
    def _line(text: str, color: str | None = None) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        if color:
            lbl.setStyleSheet(f"color: {color};")
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        return lbl
