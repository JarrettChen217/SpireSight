"""Global hotkey registration via pynput, isolated for testability.

The pynput dependency is imported at module load but the listener
class is referenced by name so tests can monkeypatch it.
"""
from __future__ import annotations

from collections.abc import Callable

from pynput.keyboard import GlobalHotKeys  # re-exported for monkeypatching


class HotkeyRegistrationFailed(RuntimeError):
    """Raised when the OS refuses to register the global hotkey."""


class HotkeyManager:
    def __init__(self, combo: str, *, on_press: Callable[[], None]) -> None:
        self._combo = combo
        self._on_press = on_press
        self._listener: GlobalHotKeys | None = None

    def start(self) -> None:
        try:
            self._listener = GlobalHotKeys({self._combo: self._on_press})
            self._listener.start()
        except Exception as exc:
            raise HotkeyRegistrationFailed(str(exc)) from exc

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
