from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from spiresight.core.run_state import RunState
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


class RunStatePanel(QWidget):
    inspect_requested = Signal()
    clear_requested = Signal()

    def __init__(self, store: RunStateStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        header = QLabel("Run State")
        header.setProperty("role", "section-header")
        outer.addWidget(header)

        button_row = QHBoxLayout()
        self._inspect_btn = QPushButton("Inspect Now")
        self._inspect_btn.setObjectName("primary")
        self._inspect_btn.clicked.connect(self.inspect_requested.emit)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self.clear_requested.emit)
        button_row.addWidget(self._inspect_btn)
        button_row.addWidget(self._clear_btn)
        outer.addLayout(button_row)

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
        self._render(store.get())

    def set_inspect_enabled(self, enabled: bool, tooltip: str = "") -> None:
        self._inspect_btn.setEnabled(enabled)
        self._inspect_btn.setToolTip(tooltip)

    def _clear_content(self) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render(self, state: RunState | None) -> None:
        self._clear_content()
        if state is None:
            empty = QLabel("Click Inspect Now to capture your current run.")
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #6e7a89;")
            self._content_layout.addWidget(empty)
            self._content_layout.addStretch(1)
            return

        if state.archetype_candidates:
            self._content_layout.addWidget(self._subheader("Archetype"))
            for a in state.archetype_candidates:
                self._content_layout.addWidget(
                    self._line(f"● {a.name} ({a.confidence})",
                               color=_USEFULNESS_COLORS["key"]
                               if a.confidence == "high" else None)
                )

        if state.cards:
            total = sum(c.count for c in state.cards)
            self._content_layout.addWidget(self._subheader(f"Cards ({total})"))
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
            self._content_layout.addWidget(self._subheader("Relics"))
            relic_text = " · ".join(r.name for r in state.relics)
            relic_label = QLabel(relic_text)
            relic_label.setWordWrap(True)
            self._content_layout.addWidget(relic_label)

        if state.potions:
            self._content_layout.addWidget(self._subheader("Potions"))
            self._content_layout.addWidget(QLabel(" · ".join(state.potions)))

        if state.overall_eval.strip():
            self._content_layout.addWidget(self._subheader("Eval"))
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
