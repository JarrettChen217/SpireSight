"""Help tab. Renders prompts/locales/<lang>/help.md via the markdown pipeline."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget

from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.markdown.renderer import render as render_markdown


class HelpTab(QWidget):
    def __init__(
        self,
        locales_dir: Path,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._locales_dir = Path(locales_dir)
        self._locale = locale

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._view = QTextBrowser()
        self._view.setOpenExternalLinks(True)
        layout.addWidget(self._view)

        locale.changed.connect(self._reload)
        self._reload()

    def _reload(self) -> None:
        lang = self._locale._language  # private, but stable in this codebase
        candidate = self._locales_dir / lang / "help.md"
        if not candidate.exists():
            candidate = self._locales_dir / "en" / "help.md"
        try:
            md = candidate.read_text(encoding="utf-8")
        except FileNotFoundError:
            md = "# Help\n\nNo help content available."
        self._view.setHtml(render_markdown(md))
