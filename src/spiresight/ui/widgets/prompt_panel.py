# src/spiresight/ui/widgets/prompt_panel.py
"""Vertical list of quick-action buttons.

Emits action_clicked(action_id).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton, QVBoxLayout, QWidget

from spiresight.prompts.loader import PromptLoader
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.theme import icon_path


class PromptPanel(QWidget):
    action_clicked = Signal(str)
    clear_context_toggled = Signal(bool)

    def __init__(
        self,
        loader: PromptLoader,
        locale: UILocale,
        *,
        clear_context: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("prompt-panel")
        self._loader = loader
        self._locale = locale
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._header = QLabel("Quick Actions")
        self._layout.addWidget(self._header)
        self._layout.addSpacing(6)

        self._clear_ctx_chk = QCheckBox()
        self._clear_ctx_chk.setObjectName("quick-action-clear-context")
        self._clear_ctx_chk.setChecked(clear_context)
        self._clear_ctx_chk.toggled.connect(self.clear_context_toggled.emit)
        chk_wrap = QWidget()
        chk_wrap.setObjectName("quick-action-clear-context-wrap")
        chk_row = QVBoxLayout(chk_wrap)
        chk_row.setContentsMargins(0, 2, 0, 10)
        chk_row.setSpacing(0)
        chk_row.addWidget(self._clear_ctx_chk)
        self._layout.addWidget(chk_wrap)
        self._layout.addSpacing(8)
        self._prefix_count = self._layout.count()

        locale.changed.connect(self._retranslate)
        self._retranslate()
        self.rebuild()

    def set_clear_context(self, value: bool) -> None:
        self._clear_ctx_chk.blockSignals(True)
        self._clear_ctx_chk.setChecked(value)
        self._clear_ctx_chk.blockSignals(False)

    def rebuild(self) -> None:
        while self._layout.count() > self._prefix_count:
            item = self._layout.takeAt(self._prefix_count)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        for qa in self._loader.quick_actions():
            btn = QPushButton(f"  {qa.label}")
            btn.setProperty("role", "quick-action")
            btn.setIcon(QIcon(icon_path(qa.id)))
            btn.setIconSize(QSize(20, 20))
            btn.clicked.connect(lambda _=False, aid=qa.id: self.action_clicked.emit(aid))
            self._layout.addWidget(btn)
        self._layout.addStretch(1)

    def _retranslate(self) -> None:
        loc = self._locale
        self._clear_ctx_chk.setText(loc.get("quick_action.clear_context"))
        self._clear_ctx_chk.setToolTip(loc.get("quick_action.clear_context_tip"))
