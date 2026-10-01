# -*- coding: utf-8 -*-
"""UI-independent file and pasted-text imports for the Qt frontend."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import book_loader
from .library_lock import library_write_lock
from .library_service import default_library_path, _manual_order
from .storage import Storage


LARGE_FILE_BYTES = 25 * 1024 * 1024
DUPLICATE_MODES = {"cancel", "overwrite", "reparse"}


class ImportServiceError(Exception):
    """A safe, user-facing import failure."""

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


@dataclass(frozen=True)
class ImportCandidate:
    """A selected path plus its path-free Bridge projection."""

    item_id: str
    path: str
    name: str
    format: str
    size_bytes: int
    supported: bool
    large: bool
    book_id: str
    duplicate_exists: bool
    duplicate_title: str

    def public_data(self) -> dict[str, Any]:
        return {
            "itemId": self.item_id,
            "name": self.name,
            "format": self.format,
            "sizeBytes": self.size_bytes,
            "supported": self.supported,
            "large": self.large,
            "duplicate": {
                "exists": self.duplicate_exists,
                "bookId": self.book_id if self.duplicate_exists else "",
                "title": self.duplicate_title,
            },
        }


ProgressCallback = Callable[[dict[str, Any]], None]


class LibraryImportService:
    """Import books while retaining the legacy library and cache formats."""

    def __init__(self, library_path: str | os.PathLike[str] | None = None):
        self.library_path = Path(library_path) if library_path is not None else default_library_path()

    def inspect_files(self, paths: list[str]) -> list[ImportCandidate]:
        books = self._validated_books_for_write()
        candidates = []
        for raw_path in paths:
            path = os.fspath(raw_path)
            suffix = Path(path).suffix.lower()
            try:
                size_bytes = max(0, os.path.getsize(path)) if os.path.isfile(path) else 0
            except OSError:
                size_bytes = 0
            book_id = Storage.book_id(path)
            existing = books.get(book_id)
            candidates.append(ImportCandidate(
                item_id=uuid.uuid4().hex,
                path=path,
                name=os.path.basename(path),
                format=suffix.lstrip(".").upper(),
                size_bytes=size_bytes,
                supported=suffix in book_loader.SUPPORTED_EXTS,
                large=size_bytes > LARGE_FILE_BYTES,
                book_id=book_id,
                duplicate_exists=bool(existing),
                duplicate_title=str(existing.get("title", "")) if isinstance(existing, dict) else "",
            ))
        return candidates

    def import_files(
        self,
        candidates: list[ImportCandidate],
        duplicate_mode: str,
        confirm_large_files: bool,
        cancel_event: threading.Event,
        progress_callback: ProgressCallback,
    ) -> dict[str, Any]:
        if duplicate_mode not in DUPLICATE_MODES:
            raise ImportServiceError("INVALID_REQUEST", "无效的重复书籍处理方式。")
        if any(candidate.large for candidate in candidates) and not confirm_large_files:
            raise ImportServiceError(
                "LARGE_FILE_CONFIRMATION_REQUIRED",
                "所选文件中包含超过 25MB 的文件，请确认后再导入。",
            )
        if duplicate_mode == "cancel" and any(candidate.duplicate_exists for candidate in candidates):
            return self._empty_result(candidates, "cancelled")

        with library_write_lock(self.library_path):
            self._validate_library_for_write()
            self.library_path.parent.mkdir(parents=True, exist_ok=True)
        total = len(candidates)
        completed = succeeded = failed = 0
        results = []
        last_imported_book_id = ""
        state = "completed"

        for index, candidate in enumerate(candidates):
            if cancel_event.is_set():
                state = "cancelled"
                break

            progress_callback(self._progress(
                index, candidate, "running", completed, total, succeeded, failed, None,
            ))
            try:
                self._validate_candidate(candidate)
                with library_write_lock(self.library_path):
                    self._validate_library_for_write()
                    storage = Storage(os.fspath(self.library_path))
                force_reparse = duplicate_mode == "reparse" and bool(storage.get_book(candidate.book_id))
                content = self._load_content(
                    storage,
                    candidate.path,
                    candidate.book_id,
                    force_reparse=force_reparse,
                )
                book_id = self._save_import(storage, content, candidate.path)
                succeeded += 1
                last_imported_book_id = book_id
                result = {
                    "name": candidate.name,
                    "status": "succeeded",
                    "bookId": book_id,
                    "error": None,
                }
                error = None
            except Exception as exc:
                failure = self._safe_error(exc)
                failed += 1
                book_id = ""
                error = failure.as_dict()
                result = {
                    "name": candidate.name,
                    "status": "failed",
                    "bookId": "",
                    "error": error,
                }

            completed += 1
            results.append(result)
            progress_callback(self._progress(
                index,
                candidate,
                result["status"],
                completed,
                total,
                succeeded,
                failed,
                error,
                book_id,
            ))

        return {
            "state": state,
            "total": total,
            "processed": completed,
            "succeeded": succeeded,
            "failed": failed,
            "lastImportedBookId": last_imported_book_id,
            "openAfterImportBookId": last_imported_book_id,
            "results": results,
        }

    def import_pasted_text(
        self,
        title: str,
        text: str,
        cancel_event: threading.Event,
        progress_callback: ProgressCallback,
    ) -> dict[str, Any]:
        body = str(text or "").strip()
        if not body:
            raise ImportServiceError("PASTE_EMPTY", "正文不能为空，请粘贴要朗读的内容。")
        if cancel_event.is_set():
            return {
                "state": "cancelled",
                "total": 1,
                "processed": 0,
                "succeeded": 0,
                "failed": 0,
                "lastImportedBookId": "",
                "openAfterImportBookId": "",
                "results": [],
            }

        self._validate_library_for_write()
        normalized_title = str(title or "").strip()
        if not normalized_title:
            normalized_title = next(
                (line.strip() for line in body.splitlines() if line.strip()),
                "粘贴文本",
            )[:40]
        safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", normalized_title)
        safe_title = safe_title.strip(" .")[:60] or "粘贴文本"

        pasted_dir = self.library_path.parent / "pasted"
        try:
            pasted_dir.mkdir(parents=True, exist_ok=True)
            pasted_path = pasted_dir / (
                f"{int(time.time())}-{uuid.uuid4().hex[:10]}-{safe_title}.txt"
            )
            pasted_path.write_text(normalized_title + "\n\n" + body, encoding="utf-8")
        except OSError as exc:
            raise ImportServiceError(
                "PASTE_WRITE_FAILED",
                "无法保存粘贴文本，请检查数据目录是否可写。",
                retryable=True,
            ) from exc

        candidate = self.inspect_files([os.fspath(pasted_path)])[0]
        return self.import_files(
            [candidate],
            duplicate_mode="overwrite",
            confirm_large_files=True,
            # Creating the pasted source starts its only item. A later cancel
            # must let that item finish safely rather than leave an orphan.
            cancel_event=threading.Event(),
            progress_callback=progress_callback,
        )

    def _validated_books_for_write(self) -> dict[str, dict[str, Any]]:
        payload = self._validate_library_for_write()
        books = payload.get("books", {})
        return books

    def _validate_library_for_write(self) -> dict[str, Any]:
        if not self.library_path.exists():
            return {"books": {}, "settings": {}}
        try:
            with self.library_path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ImportServiceError(
                "LIBRARY_INVALID",
                "书架数据读取失败，请检查 library.json 是否完整。",
            ) from exc
        if not isinstance(payload, dict):
            raise ImportServiceError(
                "LIBRARY_INVALID",
                "书架数据读取失败，请检查 library.json 是否完整。",
            )
        books = payload.get("books", {})
        settings = payload.get("settings", {})
        if (
            not isinstance(books, dict)
            or not isinstance(settings, dict)
            or any(not isinstance(metadata, dict) for metadata in books.values())
        ):
            raise ImportServiceError(
                "LIBRARY_INVALID",
                "书架数据读取失败，请检查 library.json 是否完整。",
            )
        return payload

    @staticmethod
    def _validate_candidate(candidate: ImportCandidate) -> None:
        if not os.path.isfile(candidate.path):
            raise ImportServiceError("FILE_NOT_FOUND", "所选文件不存在或无法访问。")
        if Path(candidate.path).suffix.lower() not in book_loader.SUPPORTED_EXTS:
            raise ImportServiceError("UNSUPPORTED_FORMAT", "暂不支持该文件格式。")

    @staticmethod
    def _load_content(
        storage: Storage,
        path: str,
        book_id: str,
        force_reparse: bool = False,
    ) -> book_loader.BookContent:
        if not force_reparse:
            cached = storage.read_cache(book_id)
            if cached:
                try:
                    return book_loader.BookContent.from_dict(cached)
                except Exception:
                    pass

        source_path = path if os.path.exists(path) else ""
        if not source_path:
            metadata = storage.get_book(book_id) or {}
            backup_path = metadata.get("source_bak", "")
            if backup_path and os.path.exists(backup_path):
                source_path = backup_path

        parse_error = None
        if source_path:
            try:
                return book_loader.parse_book(source_path)
            except Exception as exc:
                parse_error = exc

        if force_reparse:
            if parse_error is not None:
                raise ImportServiceError(
                    "PARSE_FAILED",
                    "无法解析该文件，请检查文件是否完整。",
                ) from parse_error
            raise ImportServiceError("FILE_NOT_FOUND", "所选文件不存在或无法访问。")

        cached = storage.read_cache(book_id, any_version=True)
        if cached:
            try:
                return book_loader.BookContent.from_dict(cached)
            except Exception:
                pass
        if parse_error is not None:
            raise ImportServiceError(
                "PARSE_FAILED",
                "无法解析该文件，请检查文件是否完整。",
            ) from parse_error
        raise ImportServiceError("FILE_NOT_FOUND", "所选文件不存在或无法访问。")

    def _save_import(
        self,
        storage: Storage,
        content: book_loader.BookContent,
        path: str,
    ) -> str:
        book_id = storage.book_id(path)
        metadata = {
            "id": book_id,
            "title": content.title,
            "author": content.author,
            "format": content.format,
            "path": path,
            "added_at": time.time(),
            "last_read_at": time.time(),
            "total_chars": content.total_chars,
            "chapter_titles": [chapter.title for chapter in content.chapters],
            "progress": {"chapter_idx": 0, "char_offset": 0, "percent": 0.0},
        }
        try:
            backup_path = storage.backup_source(book_id, path)
            if backup_path:
                metadata["source_bak"] = backup_path
        except Exception:
            pass
        with library_write_lock(self.library_path):
            self._validate_library_for_write()
            current_storage = Storage(os.fspath(self.library_path))
            try:
                if current_storage.get_setting("library_sort_mode") == "manual":
                    order = _manual_order(current_storage.data)
                    if book_id not in order:
                        order.append(book_id)
                    current_storage.data["settings"]["library_manual_order"] = order
                current_storage.add_book(metadata)
            except Exception as exc:
                raise ImportServiceError(
                    "LIBRARY_WRITE_FAILED",
                    "无法更新书架数据，请检查数据目录是否可写。",
                    retryable=True,
                ) from exc
        current_storage.write_cache(book_id, content)
        return book_id

    @staticmethod
    def _safe_error(exc: Exception) -> ImportServiceError:
        if isinstance(exc, ImportServiceError):
            return exc
        return ImportServiceError(
            "IMPORT_FAILED",
            "导入失败，请检查文件是否完整。",
            retryable=True,
        )

    @staticmethod
    def _progress(
        index: int,
        candidate: ImportCandidate,
        status: str,
        completed: int,
        total: int,
        succeeded: int,
        failed: int,
        error: dict[str, Any] | None,
        book_id: str = "",
    ) -> dict[str, Any]:
        return {
            "phase": "item",
            "completed": completed,
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "item": {
                "index": index,
                "name": candidate.name,
                "status": status,
                "bookId": book_id,
            },
            "error": error,
        }

    @staticmethod
    def _empty_result(candidates: list[ImportCandidate], state: str) -> dict[str, Any]:
        return {
            "state": state,
            "total": len(candidates),
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "lastImportedBookId": "",
            "openAfterImportBookId": "",
            "results": [],
        }
