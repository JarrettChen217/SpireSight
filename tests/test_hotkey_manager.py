import pytest
from spiresight.hotkey.manager import HotkeyManager, HotkeyRegistrationFailed


class _FakeListener:
    instances: list["_FakeListener"] = []

    def __init__(self, hotkeys=None):
        self.hotkeys = hotkeys
        self.started = False
        self.stopped = False
        _FakeListener.instances.append(self)

    def start(self): self.started = True
    def stop(self): self.stopped = True


class _BrokenListener:
    def __init__(self, hotkeys=None): raise RuntimeError("no permission")


def test_start_registers_hotkey(monkeypatch):
    _FakeListener.instances.clear()
    monkeypatch.setattr("spiresight.hotkey.manager.GlobalHotKeys", _FakeListener)
    hits: list[bool] = []
    mgr = HotkeyManager("<ctrl>+<shift>+s", on_press=lambda: hits.append(True))
    mgr.start()
    assert _FakeListener.instances[0].started
    # invoke the registered callback
    cb = next(iter(_FakeListener.instances[0].hotkeys.values()))
    cb()
    assert hits == [True]
    mgr.stop()
    assert _FakeListener.instances[0].stopped


def test_start_raises_friendly_error_on_permission_failure(monkeypatch):
    monkeypatch.setattr("spiresight.hotkey.manager.GlobalHotKeys", _BrokenListener)
    mgr = HotkeyManager("<ctrl>+<shift>+s", on_press=lambda: None)
    with pytest.raises(HotkeyRegistrationFailed):
        mgr.start()
