import sys
import types
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# ---------------------------------------------------------------------------
# Headless-CI shim: pynput probes for an X/display connection at import time,
# which fails on ubuntu-latest runners with no DISPLAY set.  Inject a minimal
# stub so the package can be imported; actual GlobalHotKeys behaviour is
# exercised via monkeypatch in test_hotkey_manager.py.
# ---------------------------------------------------------------------------
if "pynput" not in sys.modules:
    _pynput = types.ModuleType("pynput")
    _pynput_kb = types.ModuleType("pynput.keyboard")

    class _StubGlobalHotKeys:  # noqa: N801
        """Stub replaced by monkeypatch in tests that exercise hotkeys."""

        def __init__(self, hotkeys=None):
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    _pynput_kb.GlobalHotKeys = _StubGlobalHotKeys  # type: ignore[attr-defined]
    _pynput.keyboard = _pynput_kb  # type: ignore[attr-defined]
    sys.modules["pynput"] = _pynput
    sys.modules["pynput.keyboard"] = _pynput_kb
