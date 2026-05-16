"""Primary-screen capture as PNG bytes."""
from __future__ import annotations

from io import BytesIO

import mss
from PIL import Image


class ScreenCaptureError(RuntimeError):
    """Raised when the OS refuses to provide a screen image."""


class ScreenCapture:
    def grab_primary(self) -> bytes:
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # 0 is "all monitors"; 1 is primary
                shot = sct.grab(monitor)
        except Exception as exc:
            raise ScreenCaptureError(str(exc)) from exc
        img = Image.frombytes("RGB", (shot.width, shot.height), shot.rgb)
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=False)
        return buf.getvalue()
