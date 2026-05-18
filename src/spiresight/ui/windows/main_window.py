"""Primary application window — tabbed layout.

Sidebar: Provider / Quick Actions / Inspect.
Right pane: TabWidget [Chat | Run State | History | Screenshot | Logs | Help]
            with a persistent ComposeDock anchored at the bottom.
"""
from __future__ import annotations

from datetime import datetime, timezone

from PIL import Image
import io

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout, QMainWindow, QMessageBox, QPushButton, QStatusBar,
    QVBoxLayout, QWidget,
)

from spiresight.capture.screen import ScreenCapture
from spiresight.config.schema import AppConfig
from spiresight.config.store import ConfigStore
from spiresight.core.inspect_session import InspectSession
from spiresight.core.request import InferenceRequest
from spiresight.core.run_state import RunState
from spiresight.core.runner import InferenceRunner
from spiresight.llm import registry
from spiresight.llm.capabilities import Capability
from spiresight.llm.errors import (
    AuthError, MissingAPIKey, MissingCapabilityError, NetworkError, RateLimitError,
)
from spiresight.prompts.loader import PromptLoader
from spiresight.prompts.ui_locale import UILocale
from spiresight.ui.state.history_store import HistoryEntry, HistoryStore
from spiresight.ui.state.run_state_store import RunStateStore
from spiresight.ui.state.screenshot_store import ScreenshotBundle, ScreenshotStore
from spiresight.ui.tabs.chat_tab import ChatTab
from spiresight.ui.tabs.help_tab import HelpTab
from spiresight.ui.tabs.history_tab import HistoryTab
from spiresight.core.usage import CallRecord, PricingTable, UsageTracker
from spiresight.ui.tabs.logs_tab import LogsTab
from spiresight.ui.tabs.run_state_tab import RunStateTab
from spiresight.ui.tabs.screenshot_tab import ScreenshotTab
from spiresight.ui.tabs.tab_widget import TabWidget
from spiresight.ui.theme import icon_path
from spiresight.ui.widgets.compose_dock import ComposeDock
from spiresight.ui.widgets.inspect_panel import InspectPanel
from spiresight.ui.widgets.mini_bar import MiniBar
from spiresight.ui.widgets.usage_bar import UsageBar
from spiresight.ui.widgets.prompt_panel import PromptPanel
from spiresight.ui.widgets.provider_picker import ProviderPicker
from spiresight.ui.windows.settings_dialog import SettingsDialog
from spiresight.ui.workers.inference_worker import InferenceWorker
from spiresight.ui.workers.inspect_worker import InspectWorker


_TAB_CHAT, _TAB_RUN, _TAB_HISTORY, _TAB_SHOT, _TAB_LOGS, _TAB_HELP = range(6)


class MainWindow(QMainWindow):

    fire_action_signal = Signal()

    def __init__(self, config: AppConfig, store: ConfigStore, loader: PromptLoader, *, pricing: PricingTable) -> None:
        super().__init__()
        self.setWindowTitle("SpireSight")
        self.resize(1080, 640)
        self._config = config
        self._store = store
        self._loader = loader
        self._capture = ScreenCapture()
        self._worker: InferenceWorker | None = None
        self._mini_bar: MiniBar | None = None

        # stores
        self._run_state_store = RunStateStore(self)
        self._history_store = HistoryStore(self)
        self._screenshot_store = ScreenshotStore(self)
        self._inspect_session = InspectSession(self)
        self._ui_locale = UILocale(
            self._loader._root / "locales", self._config.language, parent=self
        )
        self._inspect_worker: InspectWorker | None = None

        # streaming-state bookkeeping for HistoryEntry assembly
        self._last_screenshot_png: bytes | None = None
        self._last_request: InferenceRequest | None = None
        self._stream_buffer: list[str] = []

        self.fire_action_signal.connect(self.fire_last_action)
        self._apply_always_on_top()

        # ── sidebar ──
        self._picker = ProviderPicker()
        self._picker.set_active(config.active_provider, config.active_model)
        self._picker.selection_changed.connect(self._on_picker_changed)

        self._prompt_panel = PromptPanel(loader)
        self._prompt_panel.action_clicked.connect(self._on_action)

        self._inspect_panel = InspectPanel(self._inspect_session, self._ui_locale)
        self._inspect_panel.capture_requested.connect(self._on_capture_requested)
        self._inspect_panel.done_requested.connect(self._on_done_requested)
        self._inspect_panel.clear_requested.connect(self._on_clear_requested)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(12, 12, 12, 12)
        sb_layout.addWidget(self._picker)
        sb_layout.addSpacing(12)
        sb_layout.addWidget(self._prompt_panel)
        sb_layout.addSpacing(12)
        sb_layout.addWidget(self._inspect_panel, stretch=1)
        sidebar.setFixedWidth(280)

        # ── right pane: corner buttons + tabs + compose ──
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

        corner_row = QHBoxLayout()
        corner_row.setContentsMargins(0, 0, 0, 0)
        corner_row.addStretch(1)
        corner_row.addWidget(self._mini_mode_btn)
        corner_row.addWidget(self._pin_btn)

        # tabs
        self._tabs = TabWidget()
        self._chat_tab = ChatTab()
        self._run_state_tab = RunStateTab(self._run_state_store, self._ui_locale)
        self._history_tab = HistoryTab(self._history_store, self._ui_locale)
        self._history_tab.resend_requested.connect(self._on_resend)
        self._screenshot_tab = ScreenshotTab(self._screenshot_store, self._ui_locale)
        self._logs_tab = LogsTab(self._ui_locale)
        self._help_tab = HelpTab(self._loader._root / "locales", self._ui_locale)

        loc = self._ui_locale
        self._tabs.addTab(self._chat_tab,       loc.get("tab.chat"))
        self._tabs.addTab(self._run_state_tab,  loc.get("tab.run_state"))
        self._tabs.addTab(self._history_tab,    loc.get("tab.history"))
        self._tabs.addTab(self._screenshot_tab, loc.get("tab.screenshot"))
        self._tabs.addTab(self._logs_tab,       loc.get("tab.logs"))
        self._tabs.addTab(self._help_tab,       loc.get("tab.help"))

        # mark tabs dirty on store updates (when not the current tab)
        self._run_state_store.changed.connect(
            lambda _s: self._tabs.mark_dirty(_TAB_RUN)
        )
        self._history_store.changed.connect(
            lambda: self._tabs.mark_dirty(_TAB_HISTORY)
        )
        self._screenshot_store.changed.connect(
            lambda: self._tabs.mark_dirty(_TAB_SHOT)
        )

        # compose dock
        self._compose = ComposeDock(self._ui_locale, config.include_screenshot_default)
        self._compose.send_clicked.connect(self._on_compose_send)
        self._compose.cancel_clicked.connect(self._on_cancel)
        self._compose.include_screenshot_toggled.connect(self._on_screenshot_toggled)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(6)
        right_layout.addLayout(corner_row)
        right_layout.addWidget(self._tabs, stretch=1)
        right_layout.addWidget(self._compose)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.addWidget(sidebar)
        body_layout.addWidget(right, stretch=1)
        self.setCentralWidget(body)

        # menubar
        menu = self.menuBar().addMenu("&App")
        menu.addAction("Settings…", self._open_settings)
        menu.addAction("Mini-bar mode", self._toggle_mini_bar)
        menu.addSeparator()
        menu.addAction("Quit", self.close)

        self.setStatusBar(QStatusBar())

        # --- usage tracking ---
        self._pricing = pricing
        self._tracker = UsageTracker(self)
        self._usage_bar = UsageBar(self._tracker, model_label=self._config.active_model)
        self.statusBar().addPermanentWidget(self._usage_bar)
        self._tracker.call_recorded.connect(self._logs_tab.log_cost)

        self._refresh_inspect_availability()
        self._ui_locale.changed.connect(self._retranslate)

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
            self._usage_bar.set_model_label(model_id)
        self._store.save(self._config)
        self._refresh_inspect_availability()

    def _on_screenshot_toggled(self, value: bool) -> None:
        self._config.include_screenshot_default = value
        self._store.save(self._config)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._config, self)
        if dlg.exec():
            self._store.save(self._config)
            self._loader.reload(language=self._config.language)
            self._ui_locale.set_language(self._config.language)
            self._prompt_panel.rebuild()
            self._apply_always_on_top()
            self.show()

    def _toggle_mini_bar(self) -> None:
        if self._mini_bar is None:
            self._mini_bar = MiniBar(self._loader, hotkey_hint=self._config.hotkey,
                                      pinned=self._config.always_on_top)
            self._mini_bar.action_clicked.connect(self._on_action)
            self._mini_bar.expand_requested.connect(self._exit_mini_bar)
        elif self._mini_bar.is_pinned != self._config.always_on_top:
            self._mini_bar.set_pinned(self._config.always_on_top)
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

    def _retranslate(self) -> None:
        loc = self._ui_locale
        self._tabs.set_label(_TAB_CHAT,    loc.get("tab.chat"))
        self._tabs.set_label(_TAB_RUN,     loc.get("tab.run_state"))
        self._tabs.set_label(_TAB_HISTORY, loc.get("tab.history"))
        self._tabs.set_label(_TAB_SHOT,    loc.get("tab.screenshot"))
        self._tabs.set_label(_TAB_LOGS,    loc.get("tab.logs"))
        self._tabs.set_label(_TAB_HELP,    loc.get("tab.help"))
        self._refresh_inspect_availability()

    # ─── inference flow ──────────────────────────────────────────

    def fire_last_action(self) -> None:
        if self._config.last_used_prompt_id:
            self._on_action(self._config.last_used_prompt_id)

    def _on_compose_send(self, text: str, include_screenshot: bool) -> None:
        actions = self._loader.quick_actions()
        if not actions:
            return
        action_id = self._config.last_used_prompt_id or actions[0].id
        self._on_action(
            action_id,
            custom_text_override=text,
            include_screenshot_override=include_screenshot,
        )

    def _on_action(
        self,
        action_id: str,
        *,
        custom_text_override: str | None = None,
        include_screenshot_override: bool | None = None,
    ) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._config.last_used_prompt_id = action_id
        self._store.save(self._config)

        custom_text = (
            custom_text_override if custom_text_override is not None
            else self._compose.text()
        )
        include_screenshot = (
            include_screenshot_override if include_screenshot_override is not None
            else self._compose.include_screenshot()
        )

        request = InferenceRequest(
            prompt_id=action_id,
            custom_text=custom_text,
            include_screenshot=include_screenshot,
        )

        screenshot_png: bytes | None = None
        if include_screenshot:
            try:
                screenshot_png = self._capture.grab_primary()
            except Exception as exc:  # noqa: BLE001
                self._log(f"capture failed: {exc}")
                screenshot_png = None

        if screenshot_png is not None:
            w, h = _png_dims(screenshot_png)
            self._screenshot_store.set(ScreenshotBundle(
                frames=(screenshot_png,),
                timestamp=datetime.now(tz=timezone.utc),
                width=w, height=h,
            ))

        self._last_screenshot_png = screenshot_png
        self._last_request = request
        self._stream_buffer = []

        runner = InferenceRunner(
            config=self._config,
            prompt_loader=self._loader,
            provider_factory=registry.get,
            screen_capture=_PrecapturedScreen(screenshot_png) if screenshot_png else self._capture,
            run_state_store=self._run_state_store,
        )

        self._tabs.setCurrentIndex(_TAB_CHAT)
        self._chat_tab.reset()
        self._compose.set_streaming(True)
        self.statusBar().showMessage("Streaming…")

        input_preview = self._compose_input_preview(request)
        self._worker = InferenceWorker(
            runner, request,
            model_id=self._config.active_model,
            input_preview=input_preview,
            parent=self,
        )
        self._worker.chunk.connect(self._on_chunk)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.run_started.connect(self._tracker.call_started)
        self._worker.usage_recorded.connect(self._on_usage_recorded)
        self._worker.cancelled.connect(self._tracker.call_cancelled)
        self._worker.start()

    def _on_chunk(self, text: str) -> None:
        self._stream_buffer.append(text)
        self._chat_tab.append_delta(text)

    def _compose_input_preview(self, request: InferenceRequest) -> str:
        """Build the 'input preview' text that the UsageBar / LogsTab show.

        Prefer the user's typed custom_text, since that's what they
        actually want to see attributed to a call. Fall back to the
        quick-action label so quick-fire prompts still get a meaningful
        line in Logs.
        """
        if request.custom_text:
            return request.custom_text
        try:
            qa = self._loader.get_quick_action(request.prompt_id)
            return qa.label
        except Exception:  # noqa: BLE001  — preview is best-effort
            return request.prompt_id

    def _on_usage_recorded(self, record: CallRecord) -> None:
        """Worker emits CallRecord with cost_usd=None; attach a price here, then forward."""
        priced_cost = (
            self._pricing.compute(record.model, record.usage)
            if record.usage_known
            else None
        )
        priced_record = CallRecord(
            timestamp=record.timestamp,
            model=record.model,
            usage=record.usage,
            usage_known=record.usage_known,
            cost_usd=priced_cost,
            input_preview=record.input_preview,
            output_preview=record.output_preview,
        )
        self._tracker.call_completed_ok(priced_record)

    def _on_resend(self, entry: HistoryEntry) -> None:
        screenshot_png = entry.screenshot_png
        if entry.include_screenshot and screenshot_png is None:
            try:
                screenshot_png = self._capture.grab_primary()
            except Exception as exc:  # noqa: BLE001
                self._log(f"resend capture failed: {exc}")
                screenshot_png = None

        request = InferenceRequest(
            prompt_id=entry.prompt_id,
            custom_text=entry.custom_text,
            include_screenshot=entry.include_screenshot and screenshot_png is not None,
        )

        if screenshot_png is not None:
            w, h = _png_dims(screenshot_png)
            self._screenshot_store.set(ScreenshotBundle(
                frames=(screenshot_png,),
                timestamp=datetime.now(tz=timezone.utc),
                width=w, height=h,
            ))

        self._last_screenshot_png = screenshot_png
        self._last_request = request
        self._stream_buffer = []

        runner = InferenceRunner(
            config=self._config,
            prompt_loader=self._loader,
            provider_factory=registry.get,
            screen_capture=_PrecapturedScreen(screenshot_png) if screenshot_png else self._capture,
            run_state_store=self._run_state_store,
        )
        self._tabs.setCurrentIndex(_TAB_CHAT)
        self._chat_tab.reset()
        self._compose.set_streaming(True)
        self.statusBar().showMessage("Streaming…")

        input_preview = self._compose_input_preview(request)
        self._worker = InferenceWorker(
            runner, request,
            model_id=self._config.active_model,
            input_preview=input_preview,
            parent=self,
        )
        self._worker.chunk.connect(self._on_chunk)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.run_started.connect(self._tracker.call_started)
        self._worker.usage_recorded.connect(self._on_usage_recorded)
        self._worker.cancelled.connect(self._tracker.call_cancelled)
        self._worker.start()

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _on_finished(self) -> None:
        self._chat_tab.finalize()
        self._compose.set_streaming(False)
        self.statusBar().showMessage("Done.", 3000)

        if self._last_request is not None:
            entry = HistoryEntry(
                timestamp=datetime.now(tz=timezone.utc),
                prompt_id=self._last_request.prompt_id,
                custom_text=self._last_request.custom_text,
                model_id=self._config.active_model,
                include_screenshot=self._last_request.include_screenshot,
                screenshot_png=self._last_screenshot_png,
                markdown="".join(self._stream_buffer),
            )
            self._history_store.append(entry)

        self._last_request = None
        self._last_screenshot_png = None
        self._stream_buffer = []

    def _on_failed(self, exc: Exception) -> None:
        self._tracker.call_failed(str(exc))
        self._chat_tab.finalize()
        self._compose.set_streaming(False)
        msg = str(exc) or exc.__class__.__name__
        self._log(f"{exc.__class__.__name__}: {msg}")
        if isinstance(exc, MissingAPIKey):
            QMessageBox.warning(self, "API key required",
                                "Add your API key under App → Settings → API Keys.")
        elif isinstance(exc, MissingCapabilityError):
            missing = ", ".join(sorted(c.value for c in exc.missing))
            QMessageBox.warning(self, "Model can't do that",
                                f"Model '{exc.model}' lacks: {missing}.")
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

        self._last_request = None
        self._last_screenshot_png = None
        self._stream_buffer = []

    def _log(self, message: str) -> None:
        self._logs_tab.log(message)

    # ─── inspect flow ────────────────────────────────────────────

    def _on_capture_requested(self) -> None:
        loc = self._ui_locale
        try:
            png = self._capture.grab_primary()
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(loc.get("main.capture_failed", error=str(exc)), 5000)
            self._log(f"capture failed: {exc}")
            return
        try:
            self._inspect_session.add_frame(png)
        except RuntimeError as exc:
            self.statusBar().showMessage(str(exc), 5000)
            return
        self.statusBar().showMessage(
            loc.get("main.captured_frame", count=self._inspect_session.count), 2000
        )

    def _on_done_requested(self) -> None:
        loc = self._ui_locale
        if self._inspect_worker is not None and self._inspect_worker.isRunning():
            return
        frames = self._inspect_session.frames
        if not frames:
            return
        runner = InferenceRunner(
            config=self._config,
            prompt_loader=self._loader,
            provider_factory=registry.get,
            screen_capture=self._capture,
            run_state_store=self._run_state_store,
        )
        self._inspect_panel.set_busy(True)
        self.statusBar().showMessage(loc.get("main.inspecting", count=len(frames)))

        self._inspect_worker = InspectWorker(runner, frames, self)
        self._inspect_worker.ready.connect(self._on_inspect_ready)
        self._inspect_worker.failed.connect(self._on_inspect_failed)
        self._inspect_worker.start()

    def _on_clear_requested(self) -> None:
        self._inspect_session.clear()
        self._run_state_store.clear()
        self.statusBar().showMessage(self._ui_locale.get("main.run_state_cleared"), 2000)

    def _on_inspect_ready(self, state: RunState) -> None:
        self._run_state_store.set(state)
        self._inspect_session.clear()
        self._inspect_panel.set_busy(False)
        self.statusBar().showMessage(self._ui_locale.get("main.run_state_captured"), 3000)
        self._inspect_worker = None

    def _on_inspect_failed(self, exc: Exception) -> None:
        loc = self._ui_locale
        self._inspect_panel.set_busy(False)
        self._log(f"inspect failed: {exc.__class__.__name__}: {exc}")
        if isinstance(exc, MissingCapabilityError):
            missing = ", ".join(sorted(c.value for c in exc.missing))
            self.statusBar().showMessage(loc.get("main.inspect_needs", missing=missing), 8000)
        elif isinstance(exc, ValueError):
            self.statusBar().showMessage(loc.get("main.inspect_malformed"), 8000)
        else:
            self.statusBar().showMessage(loc.get("main.inspect_failed", error=str(exc)), 8000)
        self._inspect_worker = None

    def _refresh_inspect_availability(self) -> None:
        loc = self._ui_locale
        try:
            provider_cfg = self._config.providers.get(self._config.active_provider)
            if provider_cfg is None:
                self._inspect_panel.set_capture_enabled(False, loc.get("main.no_provider"))
                return
            provider = registry.get(self._config.active_provider, provider_cfg)
            model = next(
                (m for m in provider.list_models() if m.id == self._config.active_model), None
            )
            if model is None:
                self._inspect_panel.set_capture_enabled(False, loc.get("main.no_model"))
                return
            needed = {Capability.VISION, Capability.JSON_MODE}
            missing = needed - set(model.capabilities)
            if missing:
                names = ", ".join(sorted(c.value for c in missing))
                self._inspect_panel.set_capture_enabled(False, loc.get("main.lacks_caps", caps=names))
            else:
                self._inspect_panel.set_capture_enabled(True)
        except Exception:  # noqa: BLE001
            self._inspect_panel.set_capture_enabled(True)


# ── helpers ──

def _png_dims(png: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(png)) as im:
        return im.width, im.height


class _PrecapturedScreen:
    """Adapter so InferenceRunner sees a pre-captured PNG instead of grabbing again."""

    def __init__(self, png: bytes) -> None:
        self._png = png

    def grab_primary(self) -> bytes:
        return self._png
