"""Set the macOS Dock icon via AppKit (dev runs are not a signed .app bundle)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def apply_dock_icon(icon_path: str | None) -> bool:
    """Use NSApplication icon so Dock gets the same squircle treatment as native apps."""
    if sys.platform != "darwin" or not icon_path:
        return False
    path = str(Path(icon_path).resolve())
    try:
        from AppKit import NSApplication, NSImage  # type: ignore[import-untyped]
    except ImportError:
        log.debug("PyObjC AppKit not installed; Dock icon relies on QIcon(%s)", path)
        return False
    image = NSImage.alloc().initWithContentsOfFile_(path)
    if image is None:
        log.warning("NSImage could not load dock icon: %s", path)
        return False
    NSApplication.sharedApplication().setApplicationIconImage_(image)
    return True
