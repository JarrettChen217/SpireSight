# src/spiresight/ui/windows/main_window.py
"""Primary application window.

Wires PromptPanel + ProviderPicker + custom text + Send button +
OutputView. Owns the InferenceWorker lifecycle, the MiniBar toggle,
and the SettingsDialog. Catches MissingCapabilityError / MissingAPIKey
and renders the appropriate modal.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QStatusBar, QVBoxLayout, QWidget,
)

from spiresight.capture.screen import ScreenCapture
from spiresight.config.schema import AppConfig
from spiresight.config.store import ConfigStore
from spiresight.core.request import InferenceRequest
from spiresight.core.runner import InferenceRunner
from spiresight.llm import registry
from spiresight.llm.errors import (
    AuthError, MissingAPIKey, MissingCapabilityError, NetworkError, RateLimitError,
)
from spiresight.prompts.loader import PromptLoader
from spiresight.ui.theme import icon_path
from spiresight.ui.widgets.mini_bar import MiniBar
from spiresight.ui.widgets.output_view import OutputView
from spiresight.ui.widgets.prompt_panel import PromptPanel
from spiresight.ui.widgets.provider_picker import ProviderPicker
from spiresight.ui.windows.settings_dialog import SettingsDialog
from spiresight.ui.workers.inference_worker import InferenceWorker


class MainWindow(QMainWindow):

    fire_action_signal = Signal()

    def __init__(self, config: AppConfig, store: ConfigStore, loader: PromptLoader) -> None:
        super().__init__()
        self.setWindowTitle("SpireSight")
        self.resize(880, 520)
        self._config = config
        self._store = store
        self._loader = loader
        self._capture = ScreenCapture()
        self._worker: InferenceWorker | None = None
        self._mini_bar: MiniBar | None = None

        self.fire_action_signal.connect(self.fire_last_action)

        self._apply_always_on_top()

        # left sidebar
        self._picker = ProviderPicker()
        self._picker.set_active(config.active_provider, config.active_model)
        self._picker.selection_changed.connect(self._on_picker_changed)

        self._prompt_panel = PromptPanel(loader)
        self._prompt_panel.action_clicked.connect(self._on_action)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(12, 12, 12, 12)
        sb_layout.addWidget(self._picker)
        sb_layout.addSpacing(12)
        sb_layout.addWidget(self._prompt_panel)
        sb_layout.addStretch(1)
        sidebar.setFixedWidth(240)

        # right pane header — pin + mini-mode buttons in top-right corner
        self._pin_btn = QPushButton()
        self._pin_btn.setCheckable(True)
        self._pin_btn.setObjectName("corner-pin")
        self._pin_btn.setChecked(config.always_on_top)
        self._pin_btn.setIconSize(QSize(18, 18))
        self._pin_btn.setToolTip("Always on top")
        self._pin_btn.setFixedSize(28, 28)
        self._pin_btn.clicked.connect(self._toggle_pin)
        self._update_pin_icon()

        self._mini_mode_btn = QPushButton()
        self._mini_mode_btn.setObjectName("corner-pin")
        self._mini_mode_btn.setIcon(QIcon(icon_path("mini_mode")))
        self._mini_mode_btn.setIconSize(QSize(18, 18))
        self._mini_mode_btn.setToolTip("Switch to mini-bar mode")
        self._mini_mode_btn.setFixedSize(28, 28)
        self._mini_mode_btn.clicked.connect(self._toggle_mini_bar)

        pin_row = QHBoxLayout()
        pin_row.setContentsMargins(0, 0, 0, 0)
        pin_row.addStretch(1)
        pin_row.addWidget(self._mini_mode_btn)
        pin_row.addWidget(self._pin_btn)

        self._custom_text = QPlainTextEdit()
        self._custom_text.setPlaceholderText("Optional context for this query…")
        self._custom_text.setMaximumHeight(80)

        self._include_screenshot = QCheckBox("Include screenshot")
        self._include_screenshot.setChecked(True)

        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("primary")
        self._send_btn.clicked.connect(self._on_send_last)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        controls = QHBoxLayout()
        controls.addWidget(self._include_screenshot)
        controls.addStretch(1)
        controls.addWidget(self._cancel_btn)
        controls.addWidget(self._send_btn)

        self._output = OutputView()

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 8, 8, 12)
        right_layout.addLayout(pin_row)
        right_layout.addWidget(QLabel("Custom (optional)"))
        right_layout.addWidget(self._custom_text)
        right_layout.addLayout(controls)
        right_layout.addWidget(self._output, stretch=1)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.addWidget(sidebar)
        body_layout.addWidget(right, stretch=1)
        self.setCentralWidget(body)

        # menubar (Settings, Mini-bar)
        menu = self.menuBar().addMenu("&App")
        menu.addAction("Settings…", self._open_settings)
        menu.addAction("Mini-bar mode", self._toggle_mini_bar)
        menu.addSeparator()
        menu.addAction("Quit", self.close)

        self.setStatusBar(QStatusBar())

    # ─── lifecycle helpers ───────────────────────────────────────

    def _toggle_pin(self) -> None:
        pinned = self._pin_btn.isChecked()
        self._config.always_on_top = pinned
        self._store.save(self._config)
        self._apply_always_on_top()
        self._update_pin_icon()

    def _update_pin_icon(self) -> None:
        icon_name = "pin_filled" if self._config.always_on_top else "pin_outline"
        self._pin_btn.setIcon(QIcon(icon_path(icon_name)))

    def _apply_always_on_top(self) -> None:
        handle = self.windowHandle()
        if handle is not None:
            handle.setFlag(Qt.WindowType.WindowStaysOnTopHint, self._config.always_on_top)
        else:
            flags = self.windowFlags()
            if self._config.always_on_top:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            else:
                flags &= ~Qt.WindowType.WindowStaysOnTopHint
            self.setWindowFlags(flags)

    def _on_picker_changed(self, provider: str, model_id: str) -> None:
        if provider:
            self._config.active_provider = provider
        if model_id:
            self._config.active_model = model_id
        self._store.save(self._config)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._config, self)
        if dlg.exec():
            self._store.save(self._config)
            self._loader.reload(language=self._config.language)
            self._prompt_panel.rebuild()
            self._apply_always_on_top()
            self.show()  # re-apply flags

    def _toggle_mini_bar(self) -> None:
        if self._mini_bar is None:
            self._mini_bar = MiniBar(self._loader, hotkey_hint=self._config.hotkey,
                                      pinned=self._config.always_on_top)
            self._mini_bar.action_clicked.connect(self._on_action)
            self._mini_bar.expand_requested.connect(self._exit_mini_bar)
        elif self._mini_bar.is_pinned != self._config.always_on_top:
            self._mini_bar._toggle_pin()
        self.hide()
        self._mini_bar.show()
        self._config.mini_bar_mode = True
        self._store.save(self._config)

    def _exit_mini_bar(self) -> None:
        if self._mini_bar is not None:
            self._config.always_on_top = self._mini_bar.is_pinned
            self._store.save(self._config)
            self._apply_always_on_top()
            self._update_pin_icon()
            self._pin_btn.setChecked(self._config.always_on_top)
            self._mini_bar.hide()
        self.show()
        self._config.mini_bar_mode = False
        self._store.save(self._config)

    # ─── inference flow ──────────────────────────────────────────

    def fire_last_action(self) -> None:
        """Called by the global hotkey."""
        if self._config.last_used_prompt_id:
            self._on_action(self._config.last_used_prompt_id)

    def _on_send_last(self) -> None:
        # If no previously-clicked action, default to the first quick action.
        actions = self._loader.quick_actions()
        if not actions:
            return
        action_id = self._config.last_used_prompt_id or actions[0].id
        self._on_action(action_id)

    def _on_action(self, action_id: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            return  # one at a time
        self._config.last_used_prompt_id = action_id
        self._store.save(self._config)

        runner = InferenceRunner(
            config=self._config,
            prompt_loader=self._loader,
            provider_factory=registry.get,
            screen_capture=self._capture,
        )
        request = InferenceRequest(
            prompt_id=action_id,
            custom_text=self._custom_text.toPlainText().strip(),
            include_screenshot=self._include_screenshot.isChecked(),
        )
        self._output.reset()
        self._send_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self.statusBar().showMessage("Streaming…")

        self._worker = InferenceWorker(runner, request, self)
        self._worker.chunk.connect(self._output.append_delta)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _on_finished(self) -> None:
        self._output.finalize()
        self._reset_buttons()
        self.statusBar().showMessage("Done.", 3000)

    def _on_failed(self, exc: Exception) -> None:
        self._output.finalize()
        self._reset_buttons()
        if isinstance(exc, MissingAPIKey):
            QMessageBox.warning(self, "API key required",
                                "Add your API key under App → Settings → API Keys.")
        elif isinstance(exc, MissingCapabilityError):
            missing = ", ".join(sorted(c.value for c in exc.missing))
            QMessageBox.warning(self, "Model can't do that",
                                f"Model '{exc.model}' lacks: {missing}.\n"
                                f"Switch model or uncheck 'Include screenshot'.")
        elif isinstance(exc, AuthError):
            QMessageBox.warning(self, "Authentication failed",
                                "The API key was rejected. Check it in Settings.")
        elif isinstance(exc, RateLimitError):
            retry = f" Retry in {exc.retry_after:.0f}s." if exc.retry_after else ""
            self.statusBar().showMessage(f"Rate limited.{retry}", 8000)
        elif isinstance(exc, NetworkError):
            self.statusBar().showMessage(f"Network error: {exc}", 8000)
        else:
            self.statusBar().showMessage(f"Error: {exc}", 8000)

    def _reset_buttons(self) -> None:
        self._send_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
