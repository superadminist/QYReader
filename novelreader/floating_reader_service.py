# -*- coding: utf-8 -*-
"""State and persistence for the Qt floating reader window."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from .library_lock import library_write_lock
from .library_service import default_library_path


DEFAULT_FLOATING_SETTINGS = {
    "geometry": "",
    "topmost": True,
    "backgroundOpacity": 0.92,
    "fontSize": 22,
    "followReaderFont": True,
    "background": "light",
    "bilingual": False,
    "textColor": "auto",
    "hoverDisplayEnabled": True,
    "progressSeekEnabled": False,
}

_STORAGE_KEYS = {
    "geometry": "floating_reader_geometry",
    "topmost": "floating_reader_topmost",
    "backgroundOpacity": "floating_reader_background_opacity",
    "fontSize": "floating_reader_font_size",
    "followReaderFont": "floating_reader_follow_font",
    "background": "floating_reader_background",
    "bilingual": "floating_reader_bilingual",
    "textColor": "floating_reader_text_color",
    "hoverDisplayEnabled": "floating_reader_hover_display",
    "progressSeekEnabled": "floating_reader_progress_seek",
}
_PATCH_KEYS = set(DEFAULT_FLOATING_SETTINGS) - {"geometry"}


class FloatingReaderError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.retryable = retryable

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.user_message,
            "retryable": self.retryable,
        }


class FloatingReaderService:
    """Own normalized settings while reusing the one playback service."""

    def __init__(self, playback, library_path: str | os.PathLike[str] | None = None):
        self._playback = playback
        self.library_path = Path(library_path) if library_path else default_library_path()
        self._visible = False
        self._settings = self._load_settings()

    def state(self) -> dict[str, Any]:
        identity_factory = getattr(self._playback, "session_identity", None)
        identity = identity_factory() if callable(identity_factory) else {
            "sessionId": "",
            "bookId": "",
        }
        context_factory = getattr(self._playback, "floating_context", None)
        context = context_factory() if callable(context_factory) else {
            "chapterIndex": 0,
            "chapterTitle": "",
            "previous": None,
            "current": None,
            "next": None,
        }
        return {
            **identity,
            "visible": self._visible,
            "settings": dict(self._settings),
            "playback": self._playback.snapshot(),
            "context": context,
        }

    @property
    def visible(self) -> bool:
        return self._visible

    def show(self) -> dict[str, Any]:
        self._visible = True
        return self.state()

    def close(self) -> bool:
        changed = self._visible
        self._visible = False
        return changed

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict) or set(patch) - _PATCH_KEYS:
            raise FloatingReaderError("INVALID_REQUEST", "悬浮窗设置参数不正确。")
        clean = dict(self._settings)
        for key, value in patch.items():
            if key in {"topmost", "followReaderFont", "bilingual", "hoverDisplayEnabled", "progressSeekEnabled"}:
                if not isinstance(value, bool):
                    raise FloatingReaderError("INVALID_REQUEST", "悬浮窗开关设置不正确。")
                clean[key] = value
            elif key == "backgroundOpacity":
                number = _finite_number(value)
                if number is None or number < 0.0 or number > 1.0:
                    raise FloatingReaderError("INVALID_REQUEST", "悬浮窗背景透明度超出允许范围。")
                clean[key] = number
            elif key == "fontSize":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
                    raise FloatingReaderError("INVALID_REQUEST", "悬浮窗字号不正确。")
                if int(value) < 14 or int(value) > 40:
                    raise FloatingReaderError("INVALID_REQUEST", "悬浮窗字号超出允许范围。")
                clean[key] = int(value)
            elif key == "background":
                if value not in {"light", "sepia", "dark"}:
                    raise FloatingReaderError("INVALID_REQUEST", "悬浮窗背景设置不正确。")
                clean[key] = value
            elif key == "textColor":
                if value != "auto" and not _is_hex_color(value):
                    raise FloatingReaderError("INVALID_REQUEST", "悬浮窗字体颜色不正确。")
                clean[key] = value.upper() if value != "auto" else "auto"
        previous = self._settings
        self._settings = clean
        try:
            self._persist()
        except Exception:
            self._settings = previous
            raise
        return self.state()

    def update_geometry(self, geometry: str) -> bool:
        geometry = str(geometry or "")
        if geometry == self._settings["geometry"]:
            return False
        previous = self._settings["geometry"]
        self._settings["geometry"] = geometry
        try:
            self._persist()
        except Exception:
            self._settings["geometry"] = previous
            raise
        return True

    def _load_settings(self) -> dict[str, Any]:
        raw: dict[str, Any] = {}
        if self.library_path.is_file():
            try:
                with self.library_path.open("r", encoding="utf-8") as stream:
                    payload = json.load(stream)
                if isinstance(payload, dict) and isinstance(payload.get("settings"), dict):
                    raw = payload["settings"]
            except (OSError, UnicodeError, json.JSONDecodeError):
                raw = {}
        projected = {
            public: raw.get(storage, DEFAULT_FLOATING_SETTINGS[public])
            for public, storage in _STORAGE_KEYS.items()
        }
        if "floating_reader_background_opacity" not in raw:
            projected["backgroundOpacity"] = raw.get(
                "floating_reader_opacity", DEFAULT_FLOATING_SETTINGS["backgroundOpacity"]
            )
        return normalize_floating_settings(projected)

    def _persist(self) -> None:
        with library_write_lock(self.library_path):
            payload: dict[str, Any] = {"books": {}, "settings": {}}
            if self.library_path.is_file():
                try:
                    with self.library_path.open("r", encoding="utf-8") as stream:
                        loaded = json.load(stream)
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise FloatingReaderError(
                        "LIBRARY_INVALID", "悬浮窗设置无法保存，书架数据格式不正确。"
                    ) from exc
                if not isinstance(loaded, dict):
                    raise FloatingReaderError(
                        "LIBRARY_INVALID", "悬浮窗设置无法保存，书架数据格式不正确。"
                    )
                payload = loaded
            settings = payload.setdefault("settings", {})
            if not isinstance(settings, dict):
                raise FloatingReaderError(
                    "LIBRARY_INVALID", "悬浮窗设置无法保存，书架设置格式不正确。"
                )
            for public_key, storage_key in _STORAGE_KEYS.items():
                settings[storage_key] = self._settings[public_key]
            self.library_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.library_path.with_suffix(self.library_path.suffix + ".tmp")
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=1)
            os.replace(temporary, self.library_path)


def normalize_floating_settings(settings: dict[str, Any]) -> dict[str, Any]:
    clean = dict(DEFAULT_FLOATING_SETTINGS)
    geometry = settings.get("geometry")
    clean["geometry"] = str(geometry) if isinstance(geometry, str) else ""
    for key in ("topmost", "followReaderFont", "bilingual", "hoverDisplayEnabled", "progressSeekEnabled"):
        value = settings.get(key)
        clean[key] = value if isinstance(value, bool) else DEFAULT_FLOATING_SETTINGS[key]
    opacity = _finite_number(settings.get("backgroundOpacity"))
    clean["backgroundOpacity"] = min(1.0, max(0.0, opacity)) if opacity is not None else 0.92
    font_size = settings.get("fontSize")
    if isinstance(font_size, bool):
        font_size = None
    try:
        font_size = int(font_size)
    except (TypeError, ValueError):
        font_size = 22
    clean["fontSize"] = min(40, max(14, font_size))
    background = settings.get("background")
    if background == "beige":
        background = "sepia"
    clean["background"] = background if background in {"light", "sepia", "dark"} else "light"
    text_color = settings.get("textColor")
    clean["textColor"] = (
        text_color.upper() if _is_hex_color(text_color) else "auto"
    )
    return clean


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_hex_color(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        return False
    return all(character in "0123456789abcdefABCDEF" for character in value[1:])
