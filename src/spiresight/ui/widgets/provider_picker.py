# src/spiresight/ui/widgets/provider_picker.py
"""Provider + model dropdowns with capability badges.

Emits selection_changed(provider_name, model_id) when either changes.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from spiresight.llm import registry
from spiresight.llm.capabilities import Capability
from spiresight.config.schema import ProviderConfig


class ProviderPicker(QWidget):
    selection_changed = Signal(str, str)  # provider, model_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._provider_box = QComboBox()
        for name in registry.names():
            self._provider_box.addItem(name.capitalize(), userData=name)

        model_row = QHBoxLayout()
        self._model_box = QComboBox()
        self._badge = QLabel()
        self._badge.setProperty("role", "badge-vision")
        self._badge.setVisible(False)
        model_row.addWidget(self._model_box, stretch=1)
        model_row.addWidget(self._badge)

        provider_lbl = QLabel("Provider")
        provider_lbl.setProperty("role", "section-header")
        model_lbl = QLabel("Model")
        model_lbl.setProperty("role", "section-header")
        layout.addWidget(provider_lbl)
        layout.addWidget(self._provider_box)
        layout.addWidget(model_lbl)
        layout.addLayout(model_row)

        self._provider_box.currentIndexChanged.connect(self._reload_models)
        self._model_box.currentIndexChanged.connect(self._emit)

    def set_active(self, provider: str, model_id: str) -> None:
        idx = self._provider_box.findData(provider)
        if idx >= 0:
            self._provider_box.setCurrentIndex(idx)
        self._reload_models()
        midx = self._model_box.findData(model_id)
        if midx >= 0:
            self._model_box.setCurrentIndex(midx)

    def _reload_models(self) -> None:
        self._model_box.clear()
        name = self._provider_box.currentData()
        provider = registry.get(name, ProviderConfig())
        for m in provider.list_models():
            label = m.display_name
            if Capability.VISION in m.capabilities:
                label += "  (vision)"
            self._model_box.addItem(label, userData=m.id)
        self._update_badge()
        self._emit()

    def _update_badge(self) -> None:
        name = self._provider_box.currentData()
        model_id = self._model_box.currentData()
        if not name or not model_id:
            self._badge.setVisible(False)
            return
        provider = registry.get(name, ProviderConfig())
        for m in provider.list_models():
            if m.id == model_id:
                vision = Capability.VISION in m.capabilities
                self._badge.setText("vision" if vision else "no vision")
                self._badge.setVisible(True)
                return
        self._badge.setVisible(False)

    def _emit(self) -> None:
        self._update_badge()
        self.selection_changed.emit(
            self._provider_box.currentData() or "",
            self._model_box.currentData() or "",
        )
