"""Per-provider configuration pane: api_key + (optional) base_url + Refresh."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from spiresight.config.schema import ProviderConfig


class ProviderPane(QWidget):
    """One provider's config: api_key + (optional base_url) + refresh + model count."""

    def __init__(
        self,
        provider_name: str,
        config: ProviderConfig,
        *,
        require_base_url: bool,
        base_url_presets: dict[str, str] | None,
        on_refresh: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider_name = provider_name
        self._on_refresh = on_refresh
        self._show_base_url = require_base_url or bool(config.base_url) or bool(base_url_presets)

        outer = QVBoxLayout(self)
        form = QFormLayout()

        self._api_key_edit = QLineEdit(config.api_key)
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText(f"{provider_name} API key")
        form.addRow("API key", self._api_key_edit)

        self._preset_combo = QComboBox()
        self._base_url_edit = QLineEdit(config.base_url or "")
        self._base_url_edit.setPlaceholderText("https://api.example.com/v1")
        if base_url_presets:
            self._preset_combo.addItem("Custom…", userData="")
            for label, url in base_url_presets.items():
                self._preset_combo.addItem(label, userData=url)
            self._preset_combo.activated.connect(self._on_preset_selected)
            form.addRow("Preset", self._preset_combo)
        form.addRow("Base URL", self._base_url_edit)
        self._preset_combo.setVisible(self._show_base_url and bool(base_url_presets))
        self._base_url_edit.setVisible(self._show_base_url)
        # Hide the form-row labels for hidden controls by hiding their buddies.
        for control in (self._preset_combo, self._base_url_edit):
            label_widget = form.labelForField(control)  # type: ignore[assignment]
            if label_widget is not None:
                label_widget.setVisible(control.isVisible())

        bottom = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh models")
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        self._count_label = QLabel(self._count_text(len(config.cached_models)))
        bottom.addWidget(self._refresh_btn)
        bottom.addWidget(self._count_label, stretch=1)

        outer.addLayout(form)
        outer.addLayout(bottom)
        outer.addStretch(1)

    # ---- public API ----

    def api_key_value(self) -> str:
        return self._api_key_edit.text().strip()

    def base_url_value(self) -> str:
        return self._base_url_edit.text().strip()

    def set_busy(self, busy: bool) -> None:
        self._refresh_btn.setEnabled(not busy)
        self._refresh_btn.setText("Refreshing…" if busy else "Refresh models")

    def set_model_count(self, n: int) -> None:
        self._count_label.setText(self._count_text(n))

    # ---- internal ----

    @staticmethod
    def _count_text(n: int) -> str:
        if n == 0:
            return "using built-in defaults"
        return f"{n} models cached"

    def _on_preset_selected(self, index: int) -> None:
        url = self._preset_combo.itemData(index)
        if url:
            self._base_url_edit.setText(url)

    def _on_refresh_clicked(self) -> None:
        self._on_refresh(self._provider_name)
