import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from novelreader.app_service import AppPreferencesService
from novelreader.import_service import LibraryImportService
from novelreader.library_service import LibraryEditService, LibraryQueryService, LibraryRemoveError


class LibraryManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.json"
        self.path.write_text(json.dumps({
            "books": {"a": {"title": "甲", "last_read_at": 1, "progress": {"percent": 17}},
                      "b": {"title": "乙", "last_read_at": 3}, "c": {"title": "丙", "last_read_at": 2}},
            "settings": {"theme": "夜间"}, "extra": {"preserved": True},
        }), encoding="utf-8")
        self.editor = LibraryEditService(self.path)

    def ids(self):
        return [book["id"] for book in LibraryQueryService(self.path).load_library()["books"]]

    def test_modes_seed_and_retain_manual_order_across_reopen(self):
        self.assertEqual(self.ids(), ["b", "c", "a"])
        self.editor.set_sort_mode("manual")
        self.editor.move_book("a", "b")
        self.assertEqual(self.ids(), ["a", "b", "c"])
        self.editor.set_sort_mode("recent")
        self.assertEqual(self.ids(), ["b", "c", "a"])
        LibraryEditService(self.path).set_sort_mode("manual")
        self.assertEqual(self.ids(), ["a", "b", "c"])
        self.editor.move_book("a", None)
        self.assertEqual(self.ids(), ["b", "c", "a"])
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["books"]["a"]["progress"]["percent"], 17)
        self.assertEqual(payload["settings"]["theme"], "夜间")
        self.assertEqual(payload["extra"], {"preserved": True})

    def test_invalid_move_never_writes(self):
        self.editor.set_sort_mode("manual")
        before = self.path.read_bytes()
        for book, target in [("missing", "b"), ("a", "missing"), ("a", 123)]:
            with self.assertRaises(LibraryRemoveError):
                self.editor.move_book(book, target)
            self.assertEqual(self.path.read_bytes(), before)
        self.editor.set_sort_mode("recent")
        with self.assertRaises(LibraryRemoveError):
            self.editor.move_book("a", None)

    def test_failed_atomic_replace_keeps_last_good_order(self):
        self.editor.set_sort_mode("manual")
        before = self.path.read_bytes()
        with patch("novelreader.library_service.os.replace", side_effect=OSError("write blocked")):
            with self.assertRaises(LibraryRemoveError) as caught:
                self.editor.move_book("a", "b")
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(self.path.read_bytes(), before)

    def test_new_import_appends_and_remove_cleans_order(self):
        self.editor.set_sort_mode("manual")
        self.editor.move_book("a", "b")
        source = Path(self.temp.name) / "新 文本.txt"
        source.write_text("第一章\n新内容。", encoding="utf-8")
        importer = LibraryImportService(self.path)
        selected = importer.inspect_files([os.fspath(source)])
        result = importer.import_files(selected, duplicate_mode="cancel", confirm_large_files=False,
                                       cancel_event=threading.Event(), progress_callback=lambda event: None)
        new_id = result["results"][0]["bookId"]
        self.assertEqual(self.ids(), ["a", "b", "c", new_id])
        self.editor.remove_book("b")
        stored = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(stored["settings"]["library_manual_order"], ["a", "c", new_id])

    def test_concurrent_preferences_and_move_keep_both_updates(self):
        self.editor.set_sort_mode("manual")
        barrier = threading.Barrier(2)
        errors = []
        def run(action):
            try:
                barrier.wait(timeout=5)
                action()
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=run, args=(lambda: self.editor.move_book("a", "b"),)),
                   threading.Thread(target=run, args=(lambda: AppPreferencesService(self.path).update({"theme": "米黄"}),))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertFalse(errors)
        self.assertEqual(self.ids(), ["a", "b", "c"])
        self.assertEqual(AppPreferencesService(self.path).state()["theme"], "米黄")

    def test_reveal_uses_original_source_not_backup(self):
        original = Path(self.temp.name) / "中文 源文件.txt"
        original.write_text("文本", encoding="utf-8")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["books"]["a"].update(path=os.fspath(original), source_bak="other-file.txt")
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(self.editor.source_file("a"), original.resolve())
        summary = LibraryQueryService(self.path).load_library()["books"][-1]
        self.assertTrue(summary["canRevealSource"])
        self.assertNotIn("path", summary)
        original.unlink()
        with self.assertRaises(LibraryRemoveError) as caught:
            self.editor.source_file("a")
        self.assertEqual(caught.exception.code, "SOURCE_NOT_FOUND")

    def test_import_directory_is_internal_and_survives_restart(self):
        preferences = AppPreferencesService(self.path)
        self.assertEqual(preferences.import_directory(), "")
        preferences.record_import_directory(self.temp.name)
        self.assertEqual(AppPreferencesService(self.path).import_directory(), self.temp.name)
        self.assertNotIn("last_import_dir", preferences.state())
        self.assertEqual(self.ids(), ["b", "c", "a"])
