# src/spiresight/ui/windows/permission_dialog.py
"""First-launch macOS Accessibility permission helper.

Shown when HotkeyRegistrationFailed is raised on darwin.
"""
from __future__ import annotations

import subprocess
import sys

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout


class PermissionDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Accessibility Permission Required")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "SpireSight needs Accessibility permission to register the\n"
            "global hotkey on macOS.\n\n"
            "Click below to open System Settings, find SpireSight under\n"
            "Privacy & Security → Accessibility, and toggle it on, then\n"
            "restart the app."
        ))
        open_btn = QPushButton("Open System Settings")
        open_btn.clicked.connect(self._open_settings)
        layout.addWidget(open_btn)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    @staticmethod
    def _open_settings() -> None:
        if sys.platform != "darwin":
            return
        subprocess.Popen([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        ])
