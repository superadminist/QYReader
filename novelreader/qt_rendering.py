"""Choose one stable composition path before Qt creates any web surface."""

from __future__ import annotations

import os
import shlex
import sys
from collections.abc import MutableMapping


def configure_rendering(environment: MutableMapping[str, str] | None = None,
                        platform: str | None = None) -> str:
    """Select a stable composition path before any Qt web surface is created.

    Hardware acceleration is the default (smooth hover/scroll); the translucent
    Windows host keeps its rounded corners through the CSS surface and the
    native alpha guard. An explicit ``QYREADER_RENDER_MODE=software`` (set by
    the entry point from the persisted preference) falls back to raster
    composition for machines whose driver cannot hold the accelerated path.
    All settings apply to this process before QApplication is constructed.
    """
    environment = os.environ if environment is None else environment
    platform = sys.platform if platform is None else platform
    mode = environment.get("QYREADER_RENDER_MODE", "").strip().lower()
    if platform != "win32" or mode != "software":
        # Hardware acceleration is the default. Non-Windows platforms and any
        # mode other than an explicit "software" keep the accelerated path.
        return "system"
    environment["QT_QUICK_BACKEND"] = "software"
    flags = environment.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    try:
        arguments = shlex.split(flags)
    except ValueError:
        arguments = flags.split()
    if "--disable-gpu" not in arguments:
        environment["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --disable-gpu").strip()
    return "software"
