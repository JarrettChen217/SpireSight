from io import BytesIO
import pytest
from PIL import Image

from spiresight.capture.screen import ScreenCapture, ScreenCaptureError


class _FakeMonitor:
    width = 4
    height = 2


class _FakeShot:
    width = 4
    height = 2
    rgb = b"\xff\x00\x00" * 8  # solid red, 4x2


class _FakeMSS:
    def __init__(self):
        self.monitors = [None, {"left": 0, "top": 0, "width": 4, "height": 2}]
    def grab(self, region):
        return _FakeShot()
    def __enter__(self): return self
    def __exit__(self, *a): pass


def test_capture_returns_png_bytes(monkeypatch):
    monkeypatch.setattr("spiresight.capture.screen.mss.mss", _FakeMSS)
    data = ScreenCapture().grab_primary()
    img = Image.open(BytesIO(data))
    assert img.format == "PNG"
    assert img.size == (4, 2)


def test_capture_wraps_errors(monkeypatch):
    class _Broken(_FakeMSS):
        def grab(self, region):
            raise RuntimeError("display unavailable")
    monkeypatch.setattr("spiresight.capture.screen.mss.mss", _Broken)
    with pytest.raises(ScreenCaptureError):
        ScreenCapture().grab_primary()
