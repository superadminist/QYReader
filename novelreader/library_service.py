# -*- coding: utf-8 -*-
"""Content-library queries and atomic management operations for the Qt frontend."""

from __future__ import annotations

import json
import hashlib
import math
import os
from pathlib import Path
from typing import Any

from .library_lock import library_write_lock
from .paths import default_data_dir


DEFAULT_COVER_URLS = (
    "covers/library-indigo.jpg",
    "covers/library-sage.jpg",
    "covers/library-amber.jpg",
    "covers/library-night.jpg",
)
DEFAULT_COVER_URL = DEFAULT_COVER_URLS[0]


class LibraryDataError(Exception):
    """Raised when an existing library file cannot be read safely."""

    code = "LIBRARY_INVALID"
    user_message = "书架数据读取失败，请检查 library.json 是否完整。"


class LibraryRemoveError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.retryable = retryable


def default_library_path() -> Path:
    """Resolve the existing library path without creating any directories."""
    return default_data_dir() / "library.json"


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integer(value: Any, default: int = 0) -> int:
    number = _finite_number(value)
    return int(number) if number is not None else default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _default_cover_url(book_id: Any) -> str:
    """Choose a stable cover without relying on Python's randomized hash()."""
    digest = hashlib.blake2s(_text(book_id).encode("utf-8"), digest_size=1).digest()[0]
    return DEFAULT_COVER_URLS[digest % len(DEFAULT_COVER_URLS)]


def _manual_order(payload: dict[str, Any]) -> list[str]:
    books = payload.get("books") or {}
    settings = payload.get("settings", {})
    saved = settings.get("library_manual_order") if isinstance(settings, dict) else None
    if not isinstance(saved, list):
        saved = []
    order = list(dict.fromkeys(item for item in saved if isinstance(item, str) and isinstance(books.get(item), dict)))
    # Seed once from recent reading. Subsequent imports append in insertion order.
    ordered_ids = set(order)
    remaining = [item for item, meta in books.items() if isinstance(meta, dict) and item not in ordered_ids]
    if not order:
        remaining.sort(key=lambda item: _finite_number(books[item].get("last_read_at")) or 0, reverse=True)
    return order + remaining


class LibraryQueryService:
    """Project stored books and sorting preferences into the bridge read model."""

    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = Path(path) if path is not None else default_library_path()

    def load_library(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"books": [], "total": 0, "sortMode": "recent"}

        try:
            with self.path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LibraryDataError() from exc

        if not isinstance(payload, dict):
            raise LibraryDataError()

        raw_books = payload.get("books", {})
        if raw_books is None:
            raw_books = {}
        if not isinstance(raw_books, dict):
            raise LibraryDataError()

        books = [
            self._book_summary(book_id, metadata)
            for book_id, metadata in raw_books.items()
            if isinstance(metadata, dict)
        ]
        settings = payload.get("settings", {})
        mode = settings.get("library_sort_mode", "recent") if isinstance(settings, dict) else "recent"
        mode = mode if isinstance(mode, str) and mode in {"recent", "manual"} else "recent"
        if mode == "manual":
            positions = {book_id: index for index, book_id in enumerate(_manual_order(payload))}
            books.sort(key=lambda book: positions.get(book["id"], len(positions)))
        else:
            books.sort(key=lambda book: book["lastReadAt"] or 0, reverse=True)
        return {"books": books, "total": len(books), "sortMode": mode}


    @staticmethod
    def _book_summary(book_id: Any, metadata: dict[str, Any]) -> dict[str, Any]:
        resolved_book_id = _text(metadata.get("id") or book_id)
        progress = metadata.get("progress")
        if not isinstance(progress, dict):
            progress = {}

        chapter_index = _integer(progress.get("chapter_idx"), 0)
        chapter_titles = metadata.get("chapter_titles")
        if not isinstance(chapter_titles, list):
            chapter_titles = []
        current_chapter = ""
        if 0 <= chapter_index < len(chapter_titles):
            current_chapter = _text(chapter_titles[chapter_index])

        percent = _finite_number(progress.get("percent"))
        percent = min(100.0, max(0.0, percent if percent is not None else 0.0))
        progress_percent: int | float = round(percent, 1)
        if progress_percent == int(progress_percent):
            progress_percent = int(progress_percent)

        last_read_at = _finite_number(metadata.get("last_read_at"))
        total_chars = max(0, _integer(metadata.get("total_chars"), 0))

        return {
            "id": resolved_book_id,
            "title": _text(metadata.get("title"), "未命名内容") or "未命名内容",
            "author": _text(metadata.get("author")),
            "format": _text(metadata.get("format")).lstrip(".").upper(),
            "progressPercent": progress_percent,
            "chapterIndex": chapter_index,
            "chapterCount": len(chapter_titles),
            "currentChapterTitle": current_chapter,
            "lastReadAt": last_read_at,
            "totalChars": total_chars,
            "coverUrl": _default_cover_url(resolved_book_id),
            "canRevealSource": isinstance(metadata.get("path"), str) and bool(metadata["path"].strip()),
        }


class LibraryEditService:
    """Manage books and ordering without changing source or cache files."""

    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = Path(path) if path is not None else default_library_path()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"books": {}, "settings": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LibraryRemoveError("LIBRARY_INVALID", "内容库数据无法读取。") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("books"), dict):
            raise LibraryRemoveError("LIBRARY_INVALID", "内容库数据格式不正确。")
        payload.setdefault("settings", {})
        if not isinstance(payload["settings"], dict):
            raise LibraryRemoveError("LIBRARY_INVALID", "内容库设置格式不正确。")
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise LibraryRemoveError("LIBRARY_WRITE_FAILED", "内容库保存失败，请检查数据目录是否可写。", True) from exc

    def set_sort_mode(self, mode: str) -> dict[str, Any]:
        if not isinstance(mode, str) or mode not in {"recent", "manual"}:
            raise LibraryRemoveError("INVALID_REQUEST", "排序方式不正确。")
        with library_write_lock(self.path):
            payload = self._load()
            if mode == "manual":
                payload["settings"]["library_manual_order"] = _manual_order(payload)
            payload["settings"]["library_sort_mode"] = mode
            self._save(payload)
            return LibraryQueryService(self.path).load_library()

    def move_book(self, book_id: str, before_book_id: str | None) -> dict[str, Any]:
        if not isinstance(book_id, str) or not book_id or (before_book_id is not None and not isinstance(before_book_id, str)):
            raise LibraryRemoveError("INVALID_REQUEST", "排序请求不正确。")
        with library_write_lock(self.path):
            payload = self._load()
            if payload["settings"].get("library_sort_mode") != "manual":
                raise LibraryRemoveError("SORT_MODE_REQUIRED", "请先切换到自定义排序。")
            order = _manual_order(payload)
            if book_id not in order or (before_book_id is not None and before_book_id not in order):
                raise LibraryRemoveError("BOOK_NOT_FOUND", "排序的内容已不在内容库中，请刷新后重试。")
            if book_id != before_book_id:
                order.remove(book_id)
                order.insert(order.index(before_book_id) if before_book_id is not None else len(order), book_id)
            payload["settings"]["library_manual_order"] = order
            self._save(payload)
            return LibraryQueryService(self.path).load_library()

    def source_file(self, book_id: str) -> Path:
        if not isinstance(book_id, str) or not book_id:
            raise LibraryRemoveError("INVALID_REQUEST", "书籍编号不能为空。")
        payload = self._load()
        metadata = payload["books"].get(book_id)
        if not isinstance(metadata, dict):
            raise LibraryRemoveError("BOOK_NOT_FOUND", "这项内容已不在内容库中。")
        source = metadata.get("path")
        if not isinstance(source, str) or not source.strip():
            raise LibraryRemoveError("SOURCE_UNAVAILABLE", "这项内容没有可定位的源文件。")
        path = Path(source)
        if not path.is_file():
            raise LibraryRemoveError("SOURCE_NOT_FOUND", "源文件已移动或删除，无法打开其位置。")
        return path.resolve()

    def remove_book(self, book_id: str) -> dict[str, Any]:
        if not isinstance(book_id, str) or not book_id:
            raise LibraryRemoveError("INVALID_REQUEST", "书籍编号不能为空。")
        with library_write_lock(self.path):
            try:
                with self.path.open("r", encoding="utf-8") as stream:
                    payload = json.load(stream)
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise LibraryRemoveError("LIBRARY_INVALID", "内容库数据无法读取。") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("books"), dict):
                raise LibraryRemoveError("LIBRARY_INVALID", "内容库数据格式不正确。")
            if book_id not in payload["books"]:
                raise LibraryRemoveError("BOOK_NOT_FOUND", "这项内容已不在内容库中。")
            payload["books"].pop(book_id)
            settings = payload.get("settings")
            if isinstance(settings, dict) and isinstance(settings.get("library_manual_order"), list):
                settings["library_manual_order"] = [item for item in settings["library_manual_order"] if item != book_id]
            if isinstance(settings, dict) and settings.get("last_book") == book_id:
                settings["last_book"] = ""
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            try:
                with temporary.open("w", encoding="utf-8") as stream:
                    json.dump(payload, stream, ensure_ascii=False, indent=1)
                os.replace(temporary, self.path)
            except OSError as exc:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                raise LibraryRemoveError("LIBRARY_WRITE_FAILED", "移除失败，请检查数据目录是否可写。", True) from exc
        return {"bookId": book_id, "removed": True}
