"""Display-only widget that renders a parsed RunState.

The capture/done/clear buttons and the in-progress thumbnail strip
have moved to InspectPanel; this widget now only renders the latest
state from RunStateStore, grouped by card usefulness.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from spiresight.core.run_state import RunState
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.run_state_store import RunStateStore


_USEFULNESS_ORDER = ("key", "good", "situational", "skip")

_GROUP_STYLE = {
    "key":         ("#fdf4dc", "#f0d68e", "#8a5a00"),
    "good":        ("#e8f1f8", "#c3d9eb", "#2d5a85"),
    "situational": ("#f4f2ed", "#e0dcd2", "#7a715f"),
    "skip":        ("#f0f0f0", "#d8d8d8", "#888888"),
}

_RARITY_GLYPHS = {
    "starter":  "○",
    "common":   "●",
    "uncommon": "◆",
    "rare":     "◆",
}


class RunStatePanel(QWidget):
    """Pure display. Subscribes to RunStateStore.changed."""

    def __init__(
        self,
        store: RunStateStore,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._locale = locale

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

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
        locale.changed.connect(self._re_render)
        self._render(store.get())

    # ── rendering ──
    def _clear_content(self) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()

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
                tag = QLabel(f"{a.name} ({a.confidence})")
                if a.confidence == "high":
                    tag.setStyleSheet(
                        "background:#fef3d8; color:#8a5a00; padding:3px 9px;"
                        "border-radius:11px; border:1px solid #f0d68e; font-weight:600;"
                    )
                else:
                    tag.setStyleSheet(
                        "background:#f4f4f4; color:#666; padding:3px 9px;"
                        "border-radius:11px; border:1px solid #e0e0e0;"
                    )
                tag.setMaximumHeight(22)
                self._content_layout.addWidget(tag)

        if state.cards:
            total = sum(c.count for c in state.cards)
            self._content_layout.addWidget(
                self._subheader(loc.get("panel.cards", total=total))
            )
            buckets: dict[str, list] = {u: [] for u in _USEFULNESS_ORDER}
            for c in state.cards:
                bucket = c.usefulness if c.usefulness in buckets else "situational"
                buckets[bucket].append(c)
            for u in _USEFULNESS_ORDER:
                items = buckets[u]
                if not items:
                    continue
                self._content_layout.addWidget(self._cards_group(u, items))

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

    def _cards_group(self, usefulness: str, items: list) -> QWidget:
        loc = self._locale
        bg, border, header_color = _GROUP_STYLE[usefulness]
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        wrapper.setStyleSheet(
            f"background:{bg}; border:1px solid {border}; border-radius:6px;"
        )

        header_key = f"panel.cards_group.{usefulness}"
        header = QLabel(loc.get(header_key))
        header.setStyleSheet(
            f"color:{header_color}; font-size:10.5px; font-weight:700;"
            f"text-transform:uppercase; letter-spacing:0.5px;"
        )
        layout.addWidget(header)

        for c in items:
            glyph = _RARITY_GLYPHS.get(c.rarity, "●")
            label_text = c.name if c.count == 1 else f"{c.name} ×{c.count}"
            row = QLabel(f"{glyph}  {label_text}")
            row.setStyleSheet(f"color:{header_color};")
            layout.addWidget(row)
            if c.note:
                note = QLabel(f"    {c.note}")
                note.setWordWrap(True)
                note.setStyleSheet("color:#666; font-size:11px; font-style:italic;")
                layout.addWidget(note)
        return wrapper

    @staticmethod
    def _subheader(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #6e7a89; font-size: 10px; "
                          "text-transform: uppercase; margin-top: 4px;")
        return lbl
