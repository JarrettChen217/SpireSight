"""Thin wrapper around OutputView so it can live as a tab."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from spiresight.ui.widgets.output_view import OutputView


class ChatTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.output = OutputView()
        layout.addWidget(self.output)

    # convenience pass-throughs
    def reset(self) -> None:
        self.output.reset()

    def append_delta(self, text: str) -> None:
        self.output.append_delta(text)

    def finalize(self) -> None:
        self.output.finalize()

    def load_static(self, markdown: str) -> None:
        self.output.load_static(markdown)

    def current_markdown(self) -> str:
        return self.output.current_markdown()
