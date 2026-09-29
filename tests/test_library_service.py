# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novelreader.library_service import (
    DEFAULT_COVER_URLS,
    LibraryDataError,
    LibraryEditService,
    LibraryRemoveError,
    LibraryQueryService,
    default_library_path,
)


class LibraryQueryServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "library.json"

    def write_library(self, payload):
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_missing_library_is_an_empty_read_only_result(self):
        service = LibraryQueryService(self.path)
        self.assertEqual(service.load_library(), {"books": [], "total": 0})
        self.assertFalse(self.path.exists())

    def test_reads_legacy_book_map_without_exposing_paths_or_writing(self):
        self.write_library({
            "books": {
                "book-b": {
                    "id": "book-b",
                    "title": "较早阅读",
                    "author": "作者乙",
                    "format": ".epub",
                    "path": "D:/private/earlier.epub",
                    "source_bak": "C:/private/cache/earlier.epub",
                    "last_read_at": 10,
                    "total_chars": 1200,
                    "chapter_titles": ["第一章"],
                    "progress": {"chapter_idx": 0, "char_offset": 3, "percent": 36.04},
                },
                "book-a": {
                    "title": "最近阅读",
                    "last_read_at": 20,
                    "chapter_titles": ["序章", "第一章"],
                    "progress": {"chapter_idx": 1, "percent": 135},
                },
            },
            "settings": {"last_book": "book-a"},
        })
        before_bytes = self.path.read_bytes()
        before_mtime = self.path.stat().st_mtime_ns

        result = LibraryQueryService(self.path).load_library()

        self.assertEqual(result["total"], 2)
        self.assertEqual([book["id"] for book in result["books"]], ["book-a", "book-b"])
        latest = result["books"][0]
        self.assertEqual(latest["progressPercent"], 100)
        self.assertEqual(latest["currentChapterTitle"], "第一章")
        self.assertEqual(latest["chapterCount"], 2)
        self.assertIn(latest["coverUrl"], DEFAULT_COVER_URLS)
        self.assertEqual(
            latest["coverUrl"],
            LibraryQueryService._book_summary("book-a", {"title": "任意标题"})["coverUrl"],
        )
        self.assertNotEqual(latest["coverUrl"], result["books"][1]["coverUrl"])
        self.assertNotIn("path", latest)
        self.assertNotIn("source_bak", latest)
        self.assertEqual(self.path.read_bytes(), before_bytes)
        self.assertEqual(self.path.stat().st_mtime_ns, before_mtime)

    def test_normalizes_optional_and_invalid_values(self):
        self.write_library({
            "books": {
                "fallback-id": {
                    "title": "",
                    "format": None,
                    "total_chars": -20,
                    "last_read_at": "not-a-number",
                    "chapter_titles": ["序章"],
                    "progress": {"chapter_idx": 4, "percent": -8},
                },
                "ignored": "not-an-object",
            }
        })

        result = LibraryQueryService(self.path).load_library()

        self.assertEqual(result["total"], 1)
        book = result["books"][0]
        self.assertEqual(book["id"], "fallback-id")
        self.assertEqual(book["title"], "未命名内容")
        self.assertEqual(book["progressPercent"], 0)
        self.assertEqual(book["currentChapterTitle"], "")
        self.assertEqual(book["lastReadAt"], None)
        self.assertEqual(book["totalChars"], 0)

    def test_rejects_damaged_or_incompatible_json(self):
        for content in ("", "{broken", "[]", '{"books": []}'):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                with self.assertRaises(LibraryDataError):
                    LibraryQueryService(self.path).load_library()

    def test_default_path_resolution_does_not_create_directories(self):
        appdata = Path(self.tempdir.name) / "missing-appdata"
        with patch.dict(os.environ, {"APPDATA": os.fspath(appdata)}, clear=False):
            with patch.dict(os.environ, {"DOUBAO_NOVEL_DATA": ""}, clear=False):
                resolved = default_library_path()
        self.assertEqual(resolved, appdata / "DDNovelReader" / "library.json")
        self.assertFalse(appdata.exists())

    def test_remove_book_keeps_source_file_and_other_library_data(self):
        source = Path(self.tempdir.name) / "user-book.txt"
        source.write_text("原文件正文", encoding="utf-8")
        self.write_library({
            "books": {
                "remove-me": {"title": "待移除", "path": os.fspath(source)},
                "keep-me": {"title": "保留"},
            },
            "settings": {"last_book": "remove-me", "theme": "夜间"},
            "other": {"kept": True},
        })
        result = LibraryEditService(self.path).remove_book("remove-me")
        stored = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(result, {"bookId": "remove-me", "removed": True})
        self.assertEqual(list(stored["books"]), ["keep-me"])
        self.assertEqual(stored["settings"], {"last_book": "", "theme": "夜间"})
        self.assertEqual(stored["other"], {"kept": True})
        self.assertEqual(source.read_text(encoding="utf-8"), "原文件正文")
        with self.assertRaises(LibraryRemoveError):
            LibraryEditService(self.path).remove_book("remove-me")


if __name__ == "__main__":
    unittest.main()
