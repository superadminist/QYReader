"""Choose one stable composition path before Qt creates any web surface."""

from __future__ import annotations

import os
import shlex
import sys
from collections.abc import MutableMapping


def configure_rendering(environment: MutableMapping[str, str] | None = None,
                        platform: str | None = None) -> str:
    """Use software for the translucent Windows host, without machine settings.

    Qt Quick and Chromium must agree on software rendering: disabling just one
    still leaves GPU texture import in the layered-window paint path. The
    hardware override is only for a controlled diagnostic comparison.
    """
    environment = os.environ if environment is None else environment
    platform = sys.platform if platform is None else platform
    if platform != "win32" or environment.get("QYREADER_RENDER_MODE") == "hardware":
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
