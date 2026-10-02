# -*- coding: utf-8 -*-
"""UI-independent reader sessions, windowed content, search, and bookmarks."""

from __future__ import annotations

import bisect
import json
import math
import os
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import book_loader
from .library_lock import library_write_lock
from .library_service import default_library_path
from .storage import Storage
from .progress_writer import ProgressWriter


WINDOW_CHAR_LIMIT = 20_000
WINDOW_BLOCK_LIMIT = 120
BLOCK_CHAR_LIMIT = 2_048
SEARCH_RESULT_LIMIT = 500
SEARCH_PAGE_SIZE = 50
BOOKMARK_PAGE_SIZE = 100

_SETTING_KEYS = {
    "fontFamily": "font_family",
    "fontSize": "font_size",
    "lineSpacing": "line_spacing",
    "paragraphMode": "paragraph_mode",
    "firstLineIndent": "first_line_indent",
    "ttsRate": "tts_rate",
    "ttsVoiceId": "tts_voice",
    "volume": "volume",
    "sentenceGapSeconds": "tts_sentence_gap",
}


class ReaderServiceError(Exception):
    """A safe reader failure that can cross the Bridge boundary."""

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


@dataclass
class _SearchState:
    token: str
    session_id: str
    query: str
    results: list[dict[str, Any]]


@dataclass
class _ReaderSession:
    session_id: str
    book_id: str
    content: book_loader.BookContent
    position: dict[str, Any]
    settings: dict[str, Any]
    block_cache: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    searches: dict[str, _SearchState] = field(default_factory=dict)


SearchProgress = Callable[[int, int], None]


class ReaderService:
    """Serve one active real-book session without exposing source paths."""

    def __init__(self, library_path: str | os.PathLike[str] | None = None, *, deferred_progress: bool = False):
        self.library_path = Path(library_path) if library_path is not None else default_library_path()
        self._session_lock = threading.RLock()
        self._session: _ReaderSession | None = None
        self._deferred_progress = deferred_progress
        self._progress_writer: ProgressWriter | None = None

    def open_book(self, book_id: str) -> dict[str, Any]:
        self.flush_progress()
        safe_book_id = str(book_id or "")
        if not safe_book_id:
            raise ReaderServiceError("INVALID_REQUEST", "书籍编号不能为空。")

        with library_write_lock(self.library_path):
            payload = self._validate_library()
            metadata = payload["books"].get(safe_book_id)
            if not isinstance(metadata, dict):
                raise ReaderServiceError("BOOK_NOT_FOUND", "内容库中不存在该书籍。")
            storage = Storage(os.fspath(self.library_path))

        content = self._load_content(storage, safe_book_id, metadata)
        if content is None:
            raise ReaderServiceError(
                "BOOK_CONTENT_UNAVAILABLE",
                "无法读取该书籍的正文内容。",
            )
        if not content.chapters or content.total_chars <= 0:
            raise ReaderServiceError("BOOK_CONTENT_EMPTY", "该书籍没有可阅读的正文内容。")

        self._ensure_source_backup(storage, safe_book_id, metadata)
        position = self._stored_position(metadata, content)
        settings = self._reader_settings(storage.settings())
        session = _ReaderSession(
            session_id=uuid.uuid4().hex,
            book_id=safe_book_id,
            content=content,
            position=position,
            settings=settings,
        )
        with self._session_lock:
            self._session = session
            window = self._content_window(
                session,
                position["chapterIndex"],
                position["charOffset"],
            )

        return {
            "sessionId": session.session_id,
            "book": {
                "id": safe_book_id,
                "title": str(content.title or "未命名"),
                "author": str(content.author or ""),
                "format": str(content.format or "").lstrip(".").upper(),
                "totalChars": content.total_chars,
                "chapters": [
                    {
                        "index": index,
                        "title": str(chapter.title or f"第 {index + 1} 章"),
                        "charCount": len(chapter.content),
                    }
                    for index, chapter in enumerate(content.chapters)
                ],
            },
            "position": dict(position),
            "window": window,
            "settings": dict(settings),
            "bookmarkCount": len(storage.get_bookmarks(safe_book_id)),
        }

    def get_window(
        self,
        session_id: str,
        chapter_index: int,
        anchor_offset: int,
    ) -> dict[str, Any]:
        with self._session_lock:
            session = self._require_session(session_id)
            chapter_index = self._chapter_index(session.content, chapter_index)
            content = session.content.chapters[chapter_index].content
            anchor_offset = self._clamp_integer(anchor_offset, 0, len(content))
            return self._content_window(session, chapter_index, anchor_offset)

    def navigate(self, session_id: str, target: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(target, dict):
            raise ReaderServiceError("INVALID_REQUEST", "阅读位置参数不正确。")
        with self._session_lock:
            session = self._require_session(session_id)
            kind = target.get("kind")
            if kind == "position":
                position = self._normalized_position(
                    session.content,
                    target.get("chapterIndex"),
                    target.get("charOffset"),
                )
            elif kind == "percent":
                percent = self._finite_number(target.get("percent"))
                if percent is None:
                    raise ReaderServiceError("INVALID_REQUEST", "阅读百分比不正确。")
                position = self._position_for_percent(session.content, percent)
            else:
                raise ReaderServiceError("INVALID_REQUEST", "不支持该阅读导航方式。")
            session.position = position
            if self._deferred_progress:
                self._queue_progress(session.book_id, position)
            window = self._content_window(
                session,
                position["chapterIndex"],
                position["charOffset"],
            )
            return {"position": dict(position), "window": window}

    def update_position(
        self,
        session_id: str,
        chapter_index: int,
        char_offset: int,
    ) -> dict[str, Any]:
        with self._session_lock:
            session = self._require_session(session_id)
            position = self._normalized_position(session.content, chapter_index, char_offset)
            if self._deferred_progress and position == session.position:
                return {"updated": False, "position": dict(position)}
            if self._deferred_progress:
                self._queue_progress(session.book_id, position)
            else:
                self._save_position(session.book_id, position)
            session.position = position
            return {"updated": True, "position": dict(position)}

    def _save_position(self, book_id, position):
        with library_write_lock(self.library_path):
            self._validate_library()
            storage = Storage(os.fspath(self.library_path))
            if not storage.get_book(book_id):
                raise ReaderServiceError("BOOK_NOT_FOUND", "内容库中不存在该书籍。")
            try:
                storage.update_reading_state(book_id, {
                    "chapter_idx": position["chapterIndex"],
                    "char_offset": position["charOffset"],
                    "percent": round(position["progressPercent"], 3),
                })
            except Exception as exc:
                raise ReaderServiceError("LIBRARY_WRITE_FAILED", "无法保存阅读进度，请检查数据目录是否可写。", retryable=True) from exc

    def _queue_progress(self, book_id, position):
        if self._progress_writer is None:
            self._progress_writer = ProgressWriter(self._save_position)
        self._progress_writer.submit(book_id, position)

    def flush_progress(self, *, wait=True):
        if self._progress_writer is not None:
            if wait:
                self._progress_writer.flush()
            else:
                self._progress_writer.request_flush()

    def progress_errors(self):
        return self._progress_writer.drain_errors() if self._progress_writer else []

    def shutdown(self):
        if self._progress_writer is not None:
            self._progress_writer.close()

    def update_settings(self, session_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Validate and persist the reader-facing subset of legacy settings."""
        updates = self._validated_settings_patch(patch)
        with self._session_lock:
            session = self._require_session(session_id)
            settings = self._persist_settings(updates)
            session.settings = self._reader_settings(settings)
            return dict(session.settings)

    def settings_state(self) -> dict[str, Any]:
        """Return global reader/TTS preferences without requiring an open book."""
        with self._session_lock:
            if self._session is not None:
                return dict(self._session.settings)
            if not self.library_path.exists():
                return self._reader_settings({})
            self._validate_library()
            storage = Storage(os.fspath(self.library_path))
            return self._reader_settings(storage.settings())

    def update_global_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Persist global preferences and synchronize the active reader session."""
        updates = self._validated_settings_patch(patch)
        with self._session_lock:
            settings = self._persist_settings(updates)
            normalized = self._reader_settings(settings)
            if self._session is not None:
                self._session.settings = dict(normalized)
            return normalized

    def _persist_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        with library_write_lock(self.library_path):
            if self.library_path.exists():
                self._validate_library()
            else:
                self.library_path.parent.mkdir(parents=True, exist_ok=True)
            storage = Storage(os.fspath(self.library_path))
            settings = storage.settings()
            settings.update(updates)
            try:
                storage.save()
            except Exception as exc:
                raise ReaderServiceError(
                    "LIBRARY_WRITE_FAILED",
                    "无法保存阅读设置，请检查数据目录是否可写。",
                    retryable=True,
                ) from exc
            return dict(settings)

    def get_session_content(self, session_id: str) -> book_loader.BookContent:
        """Return a detached content snapshot for trusted backend consumers such as TTS."""
        with self._session_lock:
            session = self._require_session(session_id)
            return book_loader.BookContent.from_dict(session.content.to_dict())

    def search(
        self,
        session_id: str,
        query: str,
        cursor: str = "",
        cancel_event: threading.Event | None = None,
        progress_callback: SearchProgress | None = None,
    ) -> dict[str, Any]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            raise ReaderServiceError("SEARCH_EMPTY", "请输入要搜索的关键词。")
        if cursor:
            with self._session_lock:
                session = self._require_session(session_id)
                state, offset = self._search_cursor(session, normalized_query, cursor)
                return self._search_page(state, offset)

        with self._session_lock:
            session = self._require_session(session_id)
            captured_session_id = session.session_id
            chapters = tuple(session.content.chapters)

        cancellation = cancel_event or threading.Event()
        token = uuid.uuid4().hex
        results = []
        total_chapters = len(chapters)
        for chapter_index, chapter in enumerate(chapters):
            if cancellation.is_set():
                raise ReaderServiceError("SEARCH_CANCELLED", "搜索已取消。")
            content = chapter.content
            position = 0
            while len(results) < SEARCH_RESULT_LIMIT:
                if cancellation.is_set():
                    raise ReaderServiceError("SEARCH_CANCELLED", "搜索已取消。")
                match = content.find(normalized_query, position)
                if match < 0:
                    break
                end = match + len(normalized_query)
                excerpt_start = max(0, match - 16)
                excerpt_end = min(len(content), end + 24)
                excerpt = content[excerpt_start:excerpt_end].replace("\n", " ")
                if len(excerpt) > 42:
                    excerpt = excerpt[:42] + "…"
                results.append({
                    "id": f"{token}-{len(results)}",
                    "chapterIndex": chapter_index,
                    "chapterTitle": str(chapter.title or f"第 {chapter_index + 1} 章"),
                    "startOffset": match,
                    "endOffset": end,
                    "excerptStartOffset": excerpt_start,
                    "excerpt": excerpt,
                })
                position = end
            if progress_callback is not None:
                progress_callback(chapter_index + 1, total_chapters)
            if len(results) >= SEARCH_RESULT_LIMIT:
                break

        state = _SearchState(token, captured_session_id, normalized_query, results)
        with self._session_lock:
            session = self._require_session(captured_session_id)
            session.searches.clear()
            session.searches[token] = state
            return self._search_page(state, 0)

    def list_bookmarks(self, session_id: str, cursor: str = "") -> dict[str, Any]:
        with self._session_lock:
            session = self._require_session(session_id)
            offset = self._page_offset(cursor)
            with library_write_lock(self.library_path):
                self._validate_library()
                storage = Storage(os.fspath(self.library_path))
                bookmarks = storage.get_bookmarks(session.book_id)
            items = [self._bookmark_data(session, bookmark) for bookmark in bookmarks]
            end = min(len(items), offset + BOOKMARK_PAGE_SIZE)
            return {
                "total": len(items),
                "nextCursor": str(end) if end < len(items) else "",
                "items": items[offset:end],
            }

    def add_bookmark(
        self,
        session_id: str,
        chapter_index: int,
        start_offset: int,
        end_offset: int,
        note: str,
    ) -> dict[str, Any]:
        with self._session_lock:
            session = self._require_session(session_id)
            chapter_index = self._chapter_index(session.content, chapter_index)
            content = session.content.chapters[chapter_index].content
            start = self._strict_integer(start_offset)
            end = self._strict_integer(end_offset)
            if start < 0 or end <= start or end > len(content):
                raise ReaderServiceError("OFFSET_OUT_OF_RANGE", "书签位置超出章节范围。")
            selected_text = content[start:end].strip()
            if not selected_text:
                raise ReaderServiceError("BOOKMARK_EMPTY", "选中的内容为空，无法添加书签。")
            default_note = selected_text[:30] + ("…" if len(selected_text) > 30 else "")
            bookmark = {
                "chapter_idx": chapter_index,
                "offset": start,
                "offset_end": end,
                "text": selected_text,
                "note": str(note or "").strip() or default_note,
            }
            with library_write_lock(self.library_path):
                self._validate_library()
                storage = Storage(os.fspath(self.library_path))
                if not storage.get_book(session.book_id):
                    raise ReaderServiceError("BOOK_NOT_FOUND", "内容库中不存在该书籍。")
                try:
                    bookmark_id = storage.add_bookmark(session.book_id, bookmark)
                except Exception as exc:
                    raise ReaderServiceError(
                        "LIBRARY_WRITE_FAILED",
                        "无法保存书签，请检查数据目录是否可写。",
                        retryable=True,
                    ) from exc
            if not bookmark_id:
                raise ReaderServiceError("BOOK_NOT_FOUND", "内容库中不存在该书籍。")
            return self._bookmark_data(session, bookmark)

    def remove_bookmark(self, session_id: str, bookmark_id: str) -> dict[str, Any]:
        safe_id = str(bookmark_id or "")
        if not safe_id:
            raise ReaderServiceError("INVALID_REQUEST", "书签编号不能为空。")
        with self._session_lock:
            session = self._require_session(session_id)
            with library_write_lock(self.library_path):
                self._validate_library()
                storage = Storage(os.fspath(self.library_path))
                bookmarks = storage.get_bookmarks(session.book_id)
                if not any(str(bookmark.get("id", "")) == safe_id for bookmark in bookmarks):
                    raise ReaderServiceError("BOOKMARK_NOT_FOUND", "该书签不存在或已删除。")
                try:
                    storage.remove_bookmark(session.book_id, safe_id)
                except Exception as exc:
                    raise ReaderServiceError(
                        "LIBRARY_WRITE_FAILED",
                        "无法删除书签，请检查数据目录是否可写。",
                        retryable=True,
                    ) from exc
            return {"bookmarkId": safe_id, "removed": True}

    def close_session(self, session_id: str = "") -> None:
        with self._session_lock:
            if self._session is None:
                return
            if session_id and self._session.session_id != session_id:
                return
            self.flush_progress()
            self._session = None

    def _require_session(self, session_id: str) -> _ReaderSession:
        if self._session is None or self._session.session_id != str(session_id or ""):
            raise ReaderServiceError("READER_SESSION_EXPIRED", "阅读会话已失效，请重新打开书籍。")
        return self._session

    def _validate_library(self) -> dict[str, Any]:
        if not self.library_path.exists():
            raise ReaderServiceError("BOOK_NOT_FOUND", "内容库中不存在该书籍。")
        try:
            with self.library_path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReaderServiceError(
                "LIBRARY_INVALID",
                "书架数据读取失败，请检查 library.json 是否完整。",
            ) from exc
        books = payload.get("books") if isinstance(payload, dict) else None
        settings = payload.get("settings", {}) if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or not isinstance(books, dict)
            or not isinstance(settings, dict)
            or any(not isinstance(metadata, dict) for metadata in books.values())
        ):
            raise ReaderServiceError(
                "LIBRARY_INVALID",
                "书架数据读取失败，请检查 library.json 是否完整。",
            )
        return payload

    @staticmethod
    def _load_content(
        storage: Storage,
        book_id: str,
        metadata: dict[str, Any],
    ) -> book_loader.BookContent | None:
        cached = storage.read_cache(book_id)
        if cached:
            try:
                return book_loader.BookContent.from_dict(cached)
            except Exception:
                pass

        source_path = str(metadata.get("path") or "")
        if not source_path or not os.path.isfile(source_path):
            source_path = str(metadata.get("source_bak") or "")
        if source_path and os.path.isfile(source_path):
            try:
                content = book_loader.parse_book(source_path)
                storage.write_cache(book_id, content)
                return content
            except Exception:
                pass

        cached = storage.read_cache(book_id, any_version=True)
        if cached:
            try:
                return book_loader.BookContent.from_dict(cached)
            except Exception:
                pass
        return None

    def _ensure_source_backup(
        self,
        storage: Storage,
        book_id: str,
        metadata: dict[str, Any],
    ) -> None:
        backup = str(metadata.get("source_bak") or "")
        if backup and os.path.isfile(backup):
            return
        source = str(metadata.get("path") or "")
        if not source or not os.path.isfile(source):
            return
        backup = storage.backup_source(book_id, source)
        if not backup:
            return
        with library_write_lock(self.library_path):
            self._validate_library()
            current_storage = Storage(os.fspath(self.library_path))
            current = current_storage.get_book(book_id)
            if not isinstance(current, dict):
                return
            current["source_bak"] = backup
            try:
                current_storage.save()
            except Exception:
                return

    @staticmethod
    def _reader_settings(settings: dict[str, Any]) -> dict[str, Any]:
        paragraph_mode = ReaderService._clamp_integer(settings.get("paragraph_mode", 1), 1, 3)
        line_spacing = ReaderService._finite_number(settings.get("line_spacing"))
        sentence_gap = ReaderService._finite_number(settings.get("tts_sentence_gap"))
        return {
            "fontFamily": str(settings.get("font_family") or "微软雅黑"),
            "fontSize": ReaderService._clamp_integer(settings.get("font_size", 17), 10, 48),
            "lineSpacing": min(3.0, max(1.0, line_spacing if line_spacing is not None else 1.5)),
            "paragraphMode": paragraph_mode,
            "firstLineIndent": bool(settings.get("first_line_indent", True)),
            "ttsRate": ReaderService._clamp_integer(settings.get("tts_rate", 200), 80, 400),
            "ttsVoiceId": str(settings.get("tts_voice") or ""),
            "volume": ReaderService._clamp_integer(settings.get("volume", 100), 0, 100),
            "sentenceGapSeconds": min(
                1.0,
                max(0.0, sentence_gap if sentence_gap is not None else 0.1),
            ),
        }

    @staticmethod
    def _validated_settings_patch(patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ReaderServiceError("INVALID_REQUEST", "阅读设置参数不正确。")
        unknown = set(patch) - set(_SETTING_KEYS)
        if unknown:
            raise ReaderServiceError("INVALID_REQUEST", "包含不支持的阅读设置。")

        updates: dict[str, Any] = {}
        for public_key, value in patch.items():
            storage_key = _SETTING_KEYS[public_key]
            if public_key == "fontFamily":
                if not isinstance(value, str) or not value.strip():
                    raise ReaderServiceError("INVALID_REQUEST", "字体名称不正确。")
                updates[storage_key] = value.strip()
            elif public_key == "ttsVoiceId":
                if not isinstance(value, str):
                    raise ReaderServiceError("INVALID_REQUEST", "语音编号不正确。")
                updates[storage_key] = value
            elif public_key == "firstLineIndent":
                if not isinstance(value, bool):
                    raise ReaderServiceError("INVALID_REQUEST", "首行缩进设置不正确。")
                updates[storage_key] = value
            elif public_key in {"fontSize", "paragraphMode", "ttsRate", "volume"}:
                number = ReaderService._strict_integer(value)
                minimum, maximum = {
                    "fontSize": (10, 48),
                    "paragraphMode": (1, 3),
                    "ttsRate": (80, 400),
                    "volume": (0, 100),
                }[public_key]
                if number < minimum or number > maximum:
                    raise ReaderServiceError("INVALID_REQUEST", "阅读设置超出允许范围。")
                updates[storage_key] = number
            else:
                if isinstance(value, bool):
                    raise ReaderServiceError("INVALID_REQUEST", "阅读设置数值不正确。")
                number = ReaderService._finite_number(value)
                minimum, maximum = {
                    "lineSpacing": (1.0, 3.0),
                    "sentenceGapSeconds": (0.0, 1.0),
                }[public_key]
                if number is None or number < minimum or number > maximum:
                    raise ReaderServiceError("INVALID_REQUEST", "阅读设置超出允许范围。")
                updates[storage_key] = number
        return updates

    @staticmethod
    def _stored_position(
        metadata: dict[str, Any],
        content: book_loader.BookContent,
    ) -> dict[str, Any]:
        progress = metadata.get("progress")
        if not isinstance(progress, dict):
            progress = {}
        return ReaderService._normalized_position(
            content,
            progress.get("chapter_idx", 0),
            progress.get("char_offset", 0),
        )

    @staticmethod
    def _normalized_position(
        content: book_loader.BookContent,
        chapter_index: Any,
        char_offset: Any,
    ) -> dict[str, Any]:
        chapter_index = ReaderService._clamp_integer(
            chapter_index,
            0,
            len(content.chapters) - 1,
        )
        char_offset = ReaderService._clamp_integer(
            char_offset,
            0,
            len(content.chapters[chapter_index].content),
        )
        absolute = content.cum[chapter_index] + char_offset
        percent = absolute / content.total_chars * 100.0 if content.total_chars else 0.0
        return {
            "chapterIndex": chapter_index,
            "charOffset": char_offset,
            "progressPercent": round(min(100.0, max(0.0, percent)), 3),
        }

    @staticmethod
    def _position_for_percent(
        content: book_loader.BookContent,
        percent: float,
    ) -> dict[str, Any]:
        percent = min(100.0, max(0.0, percent))
        target = content.total_chars * percent / 100.0
        chapter_index = bisect.bisect_right(content.cum, target) - 1
        chapter_index = max(0, min(chapter_index, len(content.chapters) - 1))
        char_offset = int(target - content.cum[chapter_index])
        return ReaderService._normalized_position(content, chapter_index, char_offset)

    def _content_window(
        self,
        session: _ReaderSession,
        chapter_index: int,
        anchor_offset: int,
    ) -> dict[str, Any]:
        chapter = session.content.chapters[chapter_index]
        blocks = session.block_cache.get(chapter_index)
        if blocks is None:
            blocks = self._build_blocks(chapter_index, chapter.content)
            session.block_cache[chapter_index] = blocks
        selected = self._window_blocks(blocks, anchor_offset)
        start = selected[0]["startOffset"] if selected else 0
        end = selected[-1]["endOffset"] if selected else 0
        return {
            "sessionId": session.session_id,
            "bookId": session.book_id,
            "chapterIndex": chapter_index,
            "chapterTitle": str(chapter.title or f"第 {chapter_index + 1} 章"),
            "chapterCharCount": len(chapter.content),
            "anchorOffset": anchor_offset,
            "windowStartOffset": start,
            "windowEndOffset": end,
            "hasBefore": start > 0,
            "hasAfter": end < len(chapter.content),
            "blocks": [dict(block) for block in selected],
        }

    @staticmethod
    def _build_blocks(chapter_index: int, content: str) -> list[dict[str, Any]]:
        blocks = []
        paragraph_start = 0
        while paragraph_start < len(content):
            newline = content.find("\n", paragraph_start)
            paragraph_end = len(content) if newline < 0 else newline + 1
            block_start = paragraph_start
            while block_start < paragraph_end:
                block_end = min(paragraph_end, block_start + BLOCK_CHAR_LIMIT)
                blocks.append({
                    "id": f"{chapter_index}:{block_start}:{block_end}",
                    "startOffset": block_start,
                    "endOffset": block_end,
                    "text": content[block_start:block_end],
                    "startsParagraph": block_start == paragraph_start,
                    "endsParagraph": block_end == paragraph_end,
                })
                block_start = block_end
            paragraph_start = paragraph_end
        return blocks

    @staticmethod
    def _window_blocks(
        blocks: list[dict[str, Any]],
        anchor_offset: int,
    ) -> list[dict[str, Any]]:
        if not blocks:
            return []
        starts = [block["startOffset"] for block in blocks]
        anchor_index = bisect.bisect_right(starts, anchor_offset) - 1
        anchor_index = max(0, min(anchor_index, len(blocks) - 1))
        left = right = anchor_index
        total_chars = len(blocks[anchor_index]["text"])

        while left > 0 and anchor_offset - blocks[left - 1]["startOffset"] <= 5_000:
            candidate_chars = len(blocks[left - 1]["text"])
            if total_chars + candidate_chars > WINDOW_CHAR_LIMIT or right - left + 2 > WINDOW_BLOCK_LIMIT:
                break
            left -= 1
            total_chars += candidate_chars

        while right + 1 < len(blocks):
            candidate_chars = len(blocks[right + 1]["text"])
            if total_chars + candidate_chars > WINDOW_CHAR_LIMIT or right - left + 2 > WINDOW_BLOCK_LIMIT:
                break
            right += 1
            total_chars += candidate_chars

        while left > 0:
            candidate_chars = len(blocks[left - 1]["text"])
            if total_chars + candidate_chars > WINDOW_CHAR_LIMIT or right - left + 2 > WINDOW_BLOCK_LIMIT:
                break
            left -= 1
            total_chars += candidate_chars
        return blocks[left:right + 1]

    @staticmethod
    def _search_cursor(
        session: _ReaderSession,
        query: str,
        cursor: str,
    ) -> tuple[_SearchState, int]:
        try:
            token, raw_offset = cursor.rsplit(":", 1)
            offset = int(raw_offset)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ReaderServiceError("SEARCH_NOT_FOUND", "搜索结果已失效，请重新搜索。") from exc
        state = session.searches.get(token)
        if state is None or state.query != query or offset < 0 or offset > len(state.results):
            raise ReaderServiceError("SEARCH_NOT_FOUND", "搜索结果已失效，请重新搜索。")
        return state, offset

    @staticmethod
    def _search_page(state: _SearchState, offset: int) -> dict[str, Any]:
        end = min(len(state.results), offset + SEARCH_PAGE_SIZE)
        return {
            "query": state.query,
            "total": len(state.results),
            "nextCursor": f"{state.token}:{end}" if end < len(state.results) else "",
            "results": [dict(result) for result in state.results[offset:end]],
        }

    @staticmethod
    def _bookmark_data(
        session: _ReaderSession,
        bookmark: dict[str, Any],
    ) -> dict[str, Any]:
        chapter_index = ReaderService._clamp_integer(
            bookmark.get("chapter_idx", 0),
            0,
            len(session.content.chapters) - 1,
        )
        chapter = session.content.chapters[chapter_index]
        start = ReaderService._clamp_integer(bookmark.get("offset", 0), 0, len(chapter.content))
        end = ReaderService._clamp_integer(
            bookmark.get("offset_end", start),
            start,
            len(chapter.content),
        )
        created_at = ReaderService._finite_number(bookmark.get("created_at"))
        return {
            "id": str(bookmark.get("id") or ""),
            "chapterIndex": chapter_index,
            "chapterTitle": str(chapter.title or f"第 {chapter_index + 1} 章"),
            "startOffset": start,
            "endOffset": end,
            "text": str(bookmark.get("text") or ""),
            "note": str(bookmark.get("note") or ""),
            "createdAt": created_at or 0.0,
        }

    @staticmethod
    def _page_offset(cursor: str) -> int:
        if not cursor:
            return 0
        try:
            offset = int(cursor)
        except (TypeError, ValueError) as exc:
            raise ReaderServiceError("INVALID_REQUEST", "分页位置无效。") from exc
        if offset < 0:
            raise ReaderServiceError("INVALID_REQUEST", "分页位置无效。")
        return offset

    @staticmethod
    def _chapter_index(content: book_loader.BookContent, value: Any) -> int:
        index = ReaderService._strict_integer(value)
        if index < 0 or index >= len(content.chapters):
            raise ReaderServiceError("CHAPTER_OUT_OF_RANGE", "章节编号超出范围。")
        return index

    @staticmethod
    def _strict_integer(value: Any) -> int:
        if isinstance(value, bool):
            raise ReaderServiceError("INVALID_REQUEST", "数值参数不正确。")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ReaderServiceError("INVALID_REQUEST", "数值参数不正确。") from exc
        if not math.isfinite(number) or number != int(number):
            raise ReaderServiceError("INVALID_REQUEST", "数值参数不正确。")
        return int(number)

    @staticmethod
    def _clamp_integer(value: Any, minimum: int, maximum: int) -> int:
        try:
            integer = ReaderService._strict_integer(value)
        except ReaderServiceError:
            integer = minimum
        return min(maximum, max(minimum, integer))

    @staticmethod
    def _finite_number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None
