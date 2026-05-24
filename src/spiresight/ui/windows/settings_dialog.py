# src/spiresight/ui/windows/settings_dialog.py
"""Settings dialog: per-provider config + general preferences."""
from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QLineEdit, QMessageBox, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from spiresight.config.schema import AppConfig, ProviderConfig
from spiresight.config.store import ConfigStore
from spiresight.llm import registry
from spiresight.llm.errors import MissingAPIKey, MissingBaseURL
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.openai_compat_provider import RELAY_PRESETS
from spiresight.llm.providers.pixel_api_provider import PIXEL_API_BASE_URL
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.widgets.provider_pane import ProviderPane
from spiresight.ui.workers.model_refresh_worker import ModelRefreshWorker

_log = logging.getLogger(__name__)

_IMAGE_POLICY_KEYS = ("full", "latest_only", "once_only", "never")
_KNOWLEDGE_GATEWAY_KEYS = ("auto", "on", "off")


def _presets_for(name: str) -> dict[str, str] | None:
    if name == "openai_compat":
        return RELAY_PRESETS
    if name == "pixel_api":
        return {"PixelAPI default": PIXEL_API_BASE_URL}
    return None


def _require_base_url(name: str) -> bool:
    return name == "openai_compat"


class SettingsDialog(QDialog):
    models_refreshed = Signal(str)              # provider_name
    models_refresh_failed = Signal(str, object) # provider_name, Exception

    def __init__(
        self,
        config: AppConfig,
        store: ConfigStore,
        locale: UILocale,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("SpireSight — Settings")
        self._config = config
        self._store = store
        self._locale = locale
        self._panes: dict[str, ProviderPane] = {}
        self._workers: dict[str, ModelRefreshWorker] = {}

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_providers_tab(), "Providers")
        tabs.addTab(self._build_general_tab(), "General")
        root.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._apply_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ---- Providers tab ----

    def _build_providers_tab(self) -> QWidget:
        nested = QTabWidget()
        for name in registry.names():
            cfg = self._config.providers.get(name, ProviderConfig())
            pane = ProviderPane(
                name, cfg,
                require_base_url=_require_base_url(name),
                base_url_presets=_presets_for(name),
                on_refresh=self.refresh_provider,
            )
            self._panes[name] = pane
            nested.addTab(pane, registry.display_name(name))
        return nested

    def refresh_provider(self, name: str) -> None:
        pane = self._panes[name]
        pane.set_busy(True)
        cur = self._config.providers.get(name, ProviderConfig())
        cfg_now = ProviderConfig(
            api_key=pane.api_key_value(),
            base_url=pane.base_url_value() or None,
            cached_models=cur.cached_models,
        )
        options = ProviderOptions(request_timeout_seconds=self._config.request_timeout_seconds)
        try:
            provider = registry.make_provider(name, cfg_now, options)
        except (MissingBaseURL, MissingAPIKey) as exc:
            QMessageBox.warning(self, "Refresh", str(exc))
            pane.set_busy(False)
            return

        worker = ModelRefreshWorker(name, provider, parent=self)
        worker.succeeded.connect(self._on_refresh_succeeded)
        worker.failed.connect(self._on_refresh_failed)
        worker.finished.connect(lambda n=name: self._panes[n].set_busy(False))
        worker.start()
        self._workers[name] = worker

    def _on_refresh_succeeded(self, name: str, models: list) -> None:
        cur = self._config.providers.get(name, ProviderConfig())
        new_cfg = ProviderConfig(
            api_key=cur.api_key,
            base_url=cur.base_url,
            cached_models=[m.to_dict() for m in models],
        )
        self._config.providers[name] = new_cfg
        self._store.save(self._config)
        self._panes[name].set_model_count(len(models))
        self.models_refreshed.emit(name)

    def _on_refresh_failed(self, name: str, exc: Exception) -> None:
        QMessageBox.warning(self, "Refresh failed", f"{name}: {exc}")
        self.models_refresh_failed.emit(name, exc)

    # ---- General tab ----

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        loc = self._locale

        self._lang_label = QLabel()
        self._lang = QComboBox()
        self._lang.addItem("English", userData="en")
        self._lang.addItem("中文", userData="zh")
        idx = self._lang.findData(self._config.language)
        self._lang.setCurrentIndex(max(0, idx))

        self._hotkey_label = QLabel()
        self._hotkey = QLineEdit(self._config.hotkey)
        self._hotkey.setPlaceholderText("<ctrl>+<shift>+s")

        self._on_top_label = QLabel()
        self._on_top = QCheckBox()
        self._on_top.setChecked(self._config.always_on_top)

        self._timeout_label = QLabel()
        self._timeout = QSpinBox()
        self._timeout.setRange(30, 600)
        self._timeout.setSingleStep(30)
        self._timeout.setValue(self._config.request_timeout_seconds)

        self._transcript_label = QLabel()
        self._transcript_mode = QComboBox()
        self._transcript_mode.addItem("", userData="compact")
        self._transcript_mode.addItem("", userData="expanded")
        idx = self._transcript_mode.findData(self._config.chat_transcript_mode)
        self._transcript_mode.setCurrentIndex(max(0, idx))

        self._image_policy_label = QLabel()
        self._image_policy = QComboBox()
        for key in _IMAGE_POLICY_KEYS:
            self._image_policy.addItem("", userData=key)
        idx = self._image_policy.findData(self._config.image_policy)
        self._image_policy.setCurrentIndex(max(0, idx))
        self._image_policy.setToolTip(loc.get("settings.image_policy_tip"))

        self._knowledge_gateway_label = QLabel()
        self._knowledge_gateway = QComboBox()
        for key in _KNOWLEDGE_GATEWAY_KEYS:
            self._knowledge_gateway.addItem("", userData=key)
        idx = self._knowledge_gateway.findData(self._config.knowledge_gateway_mode)
        self._knowledge_gateway.setCurrentIndex(max(0, idx))
        self._knowledge_gateway.setToolTip(loc.get("settings.knowledge_gateway_tip"))

        self._fill_general_labels()

        form.addRow(self._lang_label, self._lang)
        form.addRow(self._hotkey_label, self._hotkey)
        form.addRow(self._on_top_label, self._on_top)
        form.addRow(self._timeout_label, self._timeout)
        form.addRow(self._transcript_label, self._transcript_mode)
        form.addRow(self._image_policy_label, self._image_policy)
        form.addRow(self._knowledge_gateway_label, self._knowledge_gateway)
        return page

    def _fill_general_labels(self) -> None:
        loc = self._locale
        self._lang_label.setText("Language")
        self._hotkey_label.setText("Hotkey")
        self._on_top_label.setText("Always on top")
        self._timeout_label.setText(loc.get("settings.request_timeout_label"))
        self._transcript_label.setText(loc.get("settings.chat_transcript_mode"))
        self._transcript_mode.setItemText(
            0, loc.get("settings.chat_transcript_compact"),
        )
        self._transcript_mode.setItemText(
            1, loc.get("settings.chat_transcript_expanded"),
        )
        self._image_policy_label.setText(loc.get("settings.image_policy"))
        for i, key in enumerate(_IMAGE_POLICY_KEYS):
            self._image_policy.setItemText(i, loc.get(f"settings.image_policy_{key}"))
        self._image_policy.setToolTip(loc.get("settings.image_policy_tip"))
        self._knowledge_gateway_label.setText(loc.get("settings.knowledge_gateway"))
        for i, key in enumerate(_KNOWLEDGE_GATEWAY_KEYS):
            self._knowledge_gateway.setItemText(
                i, loc.get(f"settings.knowledge_gateway_{key}"),
            )
        self._knowledge_gateway.setToolTip(loc.get("settings.knowledge_gateway_tip"))

    # ---- accept / persistence ----

    def _apply_and_accept(self) -> None:
        for name, pane in self._panes.items():
            cur = self._config.providers.get(name, ProviderConfig())
            self._config.providers[name] = ProviderConfig(
                api_key=pane.api_key_value(),
                base_url=pane.base_url_value() or None,
                cached_models=cur.cached_models,
            )
        self._config.language = self._lang.currentData()
        self._config.hotkey = self._hotkey.text().strip() or self._config.hotkey
        self._config.always_on_top = self._on_top.isChecked()
        self._config.request_timeout_seconds = self._timeout.value()
        self._config.chat_transcript_mode = self._transcript_mode.currentData()
        policy = self._image_policy.currentData()
        if policy in _IMAGE_POLICY_KEYS:
            self._config.image_policy = policy
        gateway_mode = self._knowledge_gateway.currentData()
        if gateway_mode in _KNOWLEDGE_GATEWAY_KEYS:
            self._config.knowledge_gateway_mode = gateway_mode
        self.accept()
