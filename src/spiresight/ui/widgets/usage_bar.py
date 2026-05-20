"""Bottom-bar widget showing current model, status light, and session totals.

Mounted via `QStatusBar.addPermanentWidget`. Subscribes to a UsageTracker's
signals and re-renders on `status_changed` / `totals_changed`. Session
state lives on the tracker; this widget is a pure view.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from spiresight.core.usage import UsageTracker
from spiresight.ui.theme import USAGE_COLORS


_STATUS_COLOR = {
    "idle":    USAGE_COLORS["light_idle"],
    "running": USAGE_COLORS["light_running"],
    "ok":      USAGE_COLORS["light_ok"],
    "error":   USAGE_COLORS["light_error"],
}


def _format_k(n: int) -> str:
    """Render token counts compactly. Examples:
        312        → "312"
        1_500      → "1.5k"
        12_345     → "12.3k"
        100_000    → "100k"   (no decimal once we're at or above 100k)
        1_500_000  → "1500k"
    """
    if n < 1000:
        return f"{n}"
    if n < 100_000:
        return f"{n / 1000:.1f}k"
    return f"{n // 1000}k"


def _dot_stylesheet(status: str) -> str:
    color = _STATUS_COLOR.get(status, _STATUS_COLOR["idle"])
    return (
        f"background-color: {color};"
        " border-radius: 5px;"
        " min-width: 10px; max-width: 10px;"
        " min-height: 10px; max-height: 10px;"
    )


class UsageBar(QWidget):
    def __init__(
        self,
        tracker: UsageTracker,
        *,
        model_label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tracker = tracker
        self._model_label = model_label

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(8)

        self._dot = QLabel()
        self._dot.setStyleSheet(_dot_stylesheet("idle"))
        layout.addWidget(self._dot, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._label = QLabel()
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._label, alignment=Qt.AlignmentFlag.AlignVCenter)

        tracker.totals_changed.connect(self._refresh_text)
        tracker.status_changed.connect(self._on_status_changed)

        self._refresh_text()

    # ---- public ----

    def set_model_label(self, model: str) -> None:
        self._model_label = model
        self._refresh_text()

    # ---- internals ----

    def _on_status_changed(self, status: str) -> None:
        self._dot.setStyleSheet(_dot_stylesheet(status))

    def _refresh_text(self) -> None:
        totals = self._tracker.totals
        cost = self._tracker.total_cost_usd
        cost_text = f"~${cost:.2f}" if cost is not None else "~$—"
        self._label.setText(
            f"{self._model_label}  "
            f"↑ {_format_k(totals.input_tokens)}  "
            f"⚡ {_format_k(totals.cached_tokens)}  "
            f"↓ {_format_k(totals.output_tokens)}  "
            f"{cost_text}"
        )
        self._refresh_tooltip()

    def _refresh_tooltip(self) -> None:
        totals = self._tracker.totals
        cost = self._tracker.total_cost_usd
        cost_line = f"cost: ${cost:.4f}" if cost is not None else "cost: —"
        unpriced = ""
        if self._tracker.has_unpriced_calls:
            unpriced = "\n(some calls unpriced)"
        self.setToolTip(
            f"input: {totals.input_tokens:,} tokens\n"
            f"cached: {totals.cached_tokens:,} tokens\n"
            f"output: {totals.output_tokens:,} tokens\n"
            f"{cost_line}{unpriced}"
        )

    # ---- test hooks ----

    def text_for_test(self) -> str:
        return self._label.text()

    def dot_stylesheet_for_test(self) -> str:
        return self._dot.styleSheet()
