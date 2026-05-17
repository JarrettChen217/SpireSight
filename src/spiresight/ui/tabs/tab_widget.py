"""QTabWidget subclass that supports per-tab "unread" badge dots.

The dot appears in the tab label as a trailing " ●" when a store
update targets a tab that is not currently active. Switching to the
tab clears its dot. This is intentionally simple — no animation, no
counts, just a binary marker.
"""
from __future__ import annotations

from PySide6.QtWidgets import QTabWidget


_DOT = " ●"


class TabWidget(QTabWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._base_labels: list[str] = []
        self.currentChanged.connect(self._on_current_changed)

    def addTab(self, widget, label):  # type: ignore[override]
        idx = super().addTab(widget, label)
        self._base_labels.append(label)
        return idx

    def mark_dirty(self, index: int) -> None:
        if index == self.currentIndex():
            return
        if 0 <= index < self.count():
            base = self._base_labels[index]
            if not self.tabText(index).endswith(_DOT):
                self.setTabText(index, base + _DOT)

    def set_label(self, index: int, label: str) -> None:
        """Update a tab's base label (e.g., on locale change)."""
        if 0 <= index < self.count():
            self._base_labels[index] = label
            dirty = self.tabText(index).endswith(_DOT)
            self.setTabText(index, label + (_DOT if dirty else ""))

    def _on_current_changed(self, idx: int) -> None:
        if 0 <= idx < len(self._base_labels):
            self.setTabText(idx, self._base_labels[idx])
