"""Choose one stable composition path before Qt creates any web surface."""

from __future__ import annotations

import os
import shlex
import sys
from collections.abc import MutableMapping


def configure_rendering(environment: MutableMapping[str, str] | None = None,
                        platform: str | None = None) -> str:
    """Use raster Qt composition for the translucent Windows widget host.

    Accelerated Quick composition can lose entire content frames even while
    Chromium's rAF timings look healthy. The alpha corner guard does not fix
    that widget/backing-store handoff. Default only the Qt composition layer to
    software; leave Chromium's own GPU policy alone. Explicit software mode
    additionally disables Chromium GPU use, and hardware mode remains opt-in.
    All settings apply to this process before QApplication is constructed.
    """
    environment = os.environ if environment is None else environment
    platform = sys.platform if platform is None else platform
    mode = environment.get("QYREADER_RENDER_MODE", "").strip().lower()
    if platform != "win32" or mode == "hardware":
        return "system"
    if mode != "software":
        backend = environment.setdefault("QT_QUICK_BACKEND", "software")
        return "software-composition" if backend == "software" else "system"
    environment["QT_QUICK_BACKEND"] = "software"
    flags = environment.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    try:
        arguments = shlex.split(flags)
    except ValueError:
        arguments = flags.split()
    if "--disable-gpu" not in arguments:
        environment["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --disable-gpu").strip()
    return "software"
