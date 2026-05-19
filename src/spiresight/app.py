"""QApplication wiring: load config, prompts, theme, hotkey, main window."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from spiresight.config import paths
from spiresight.config.store import ConfigStore
from spiresight.core.conversation import ConversationStore
from spiresight.hotkey.manager import HotkeyManager, HotkeyRegistrationFailed
from spiresight.logging_setup import configure_logging
from spiresight.prompts.loader import PromptLoader
from spiresight.ui.theme import app_icon_path, load_qss

if sys.platform == "darwin":
    from spiresight.ui.macos_dock_icon import apply_dock_icon
else:
    def apply_dock_icon(_path: str | None) -> bool:
        return False
from spiresight.ui.windows.main_window import MainWindow
from spiresight.ui.windows.permission_dialog import PermissionDialog

log = logging.getLogger(__name__)


def _prompts_root() -> Path:
    """Locate the prompts/ directory whether running from source or bundle."""
    here = Path(__file__).resolve()
    # source layout: <repo>/src/spiresight/app.py → <repo>/prompts/
    for parent in here.parents:
        candidate = parent / "prompts"
        if (candidate / "system_prompts.yaml").exists():
            return candidate
    raise FileNotFoundError("Could not locate prompts/ directory")


def _prices_path() -> Path:
    """Locate config/prices.yaml whether running from source or bundle."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "prices.yaml"
        if candidate.exists():
            return candidate
    # Fall through — caller's PricingTable.load handles missing file.
    return Path(__file__).resolve().parent / "config" / "prices.yaml"


def run() -> int:
    configure_logging()
    paths.ensure_dirs()

    store = ConfigStore()
    config = store.load()

    loader = PromptLoader(_prompts_root())
    loader.reload(language=config.language)

    from spiresight.core.usage import PricingTable
    pricing = PricingTable.load(_prices_path())

    qt_app = QApplication(sys.argv)
    qt_app.setStyleSheet(load_qss(config.theme))
    icon_file = app_icon_path()
    if icon_file is not None:
        qt_app.setWindowIcon(QIcon(icon_file))
        apply_dock_icon(icon_file)

    window = MainWindow(config, store, loader, pricing=pricing, conversation_store=ConversationStore())
    window.show()

    hotkey_mgr: HotkeyManager | None = None
    try:
        hotkey_mgr = HotkeyManager(config.hotkey, on_press=window.fire_action_signal.emit)
        hotkey_mgr.start()
    except HotkeyRegistrationFailed as exc:
        log.warning("Hotkey registration failed: %s", exc)
        if sys.platform == "darwin":
            PermissionDialog(window).exec()

    try:
        return qt_app.exec()
    finally:
        if hotkey_mgr is not None:
            hotkey_mgr.stop()
