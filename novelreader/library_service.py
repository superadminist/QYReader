# -*- coding: utf-8 -*-
"""Read-only content-library queries for the Qt frontend."""

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


class LibraryQueryService:
    """Project the legacy library schema into the Bridge v1 read model."""

    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = Path(path) if path is not None else default_library_path()

    def load_library(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"books": [], "total": 0}

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
        books.sort(key=lambda book: book["lastReadAt"] or 0, reverse=True)
        return {"books": books, "total": len(books)}


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
        }


class LibraryEditService:
    """Remove a book from the library without touching source or cache files."""

    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = Path(path) if path is not None else default_library_path()

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
