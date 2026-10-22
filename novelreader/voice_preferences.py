"""Stable voice favorites, independent of the currently installed voice catalog."""
from .feature_store import FeatureError, read_library, save_library
from .library_lock import library_write_lock

class VoicePreferences:
    def __init__(self, path):
        self.path = path

    def favorites(self):
        values = read_library(self.path).get("settings", {}).get("voice_favorites", [])
        return list(dict.fromkeys(x for x in values if isinstance(x, str))) if isinstance(values, list) else []

    def set_favorite(self, voice_id, favorite):
        if not isinstance(voice_id, str) or len(voice_id) > 2048 or type(favorite) is not bool:
            raise FeatureError("INVALID_REQUEST", "音色收藏参数无效。")
        with library_write_lock(self.path):
            data = read_library(self.path)
            values = data.setdefault("settings", {}).get("voice_favorites", [])
            values = list(dict.fromkeys(x for x in values if isinstance(x, str))) if isinstance(values, list) else []
            if favorite and voice_id not in values: values.append(voice_id)
            if not favorite: values = [x for x in values if x != voice_id]
            data["settings"]["voice_favorites"] = values
            save_library(self.path, data)
        return values
