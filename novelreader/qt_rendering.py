"""Choose one stable composition path before Qt creates any web surface."""

from __future__ import annotations

import os
import shlex
import sys
from collections.abc import MutableMapping


def configure_rendering(environment: MutableMapping[str, str] | None = None,
                        platform: str | None = None) -> str:
    """Let Qt select acceleration; opt into software for driver compatibility.

    Forced software composition stalls even cached transform/opacity animations
    in the translucent Windows host. The native alpha guard now preserves the
    rounded surface on the accelerated path too. An explicit software override
    still disables both composition layers, without changing machine settings.
    """
    environment = os.environ if environment is None else environment
    platform = sys.platform if platform is None else platform
    if platform != "win32" or environment.get("QYREADER_RENDER_MODE") != "software":
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
