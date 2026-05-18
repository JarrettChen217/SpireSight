# src/spiresight/ui/windows/settings_dialog.py
"""Settings dialog: API keys per provider, language, hotkey, always-on-top."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QLineEdit, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.llm import registry


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SpireSight — Settings")
        self._config = config
        self._key_inputs: dict[str, QLineEdit] = {}

        root = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_keys_tab(), "API Keys")
        tabs.addTab(self._build_general_tab(), "General")
        root.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._apply_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_keys_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        for name in registry.names():
            cfg = self._config.providers.get(name, ProviderConfig())
            edit = QLineEdit(cfg.api_key)
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setPlaceholderText(f"{name} API key")
            self._key_inputs[name] = edit
            form.addRow(name.capitalize(), edit)
        return page

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self._lang = QComboBox()
        self._lang.addItem("English", userData="en")
        self._lang.addItem("中文", userData="zh")
        idx = self._lang.findData(self._config.language)
        self._lang.setCurrentIndex(max(0, idx))

        self._hotkey = QLineEdit(self._config.hotkey)
        self._hotkey.setPlaceholderText("<ctrl>+<shift>+s")

        self._on_top = QCheckBox()
        self._on_top.setChecked(self._config.always_on_top)

        self._timeout = QSpinBox()
        self._timeout.setRange(30, 600)
        self._timeout.setSingleStep(30)
        self._timeout.setValue(self._config.request_timeout_seconds)

        form.addRow("Language", self._lang)
        form.addRow("Hotkey", self._hotkey)
        form.addRow("Always on top", self._on_top)
        # Settings dialog locale awareness is a follow-up; using English literal for now.
        form.addRow("Request timeout (seconds)", self._timeout)
        return page

    def _apply_and_accept(self) -> None:
        for name, edit in self._key_inputs.items():
            current = self._config.providers.get(name, ProviderConfig())
            self._config.providers[name] = ProviderConfig(
                api_key=edit.text().strip(),
                base_url=current.base_url,
            )
        self._config.language = self._lang.currentData()
        self._config.hotkey = self._hotkey.text().strip() or self._config.hotkey
        self._config.always_on_top = self._on_top.isChecked()
        self._config.request_timeout_seconds = self._timeout.value()
        self.accept()
