"""Batch edits must share the progress writer's transaction boundary."""
import copy
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from novelreader.feature_store import FeatureError, OrganizationService, read_library, save_library, status_for
from novelreader.library_lock import library_write_lock


class LibraryBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"DOUBAO_NOVEL_DATA": str(self.root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.path = self.root / "library.json"
        self.data = {
            "books": {
                "a": {"title": "甲", "category_id": "old", "tag_ids": ["one", "legacy"], "progress": {"percent": 32, "char_offset": 91}, "bookmarks": [{"id": "note", "offset": 3}], "path": "source.txt", "future": {"keep": True}},
                "b": {"title": "乙", "tag_ids": ["two"], "progress": {"percent": 100}, "reading_status": "unread", "reading_status_mode": "manual"},
                "c": {"title": "丙", "progress": {"percent": 0}},
            },
            "categories": [{"id": "old", "name": "旧分类"}, {"id": "new", "name": "新分类"}],
            "tags": [{"id": "one", "name": "一"}, {"id": "two", "name": "二"}],
            "settings": {"futureSetting": 99}, "futureRoot": [1, 2, 3],
        }
        self.path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        self.service = OrganizationService(self.path)

    def batch(self, patch_data, ids=None):
        return self.service.update({"action": "batch", "bookIds": ["a", "b"] if ids is None else ids, "patch": patch_data})

    def test_category_tag_union_difference_and_one_write_preserve_other_fields(self):
        with patch("novelreader.feature_store.save_library", wraps=save_library) as save:
            self.batch({"categoryId": "new", "addTagIds": ["to-read", "two"], "removeTagIds": ["one"]})
            self.assertEqual(save.call_count, 1)
        data = read_library(self.path)
        self.assertEqual(data["books"]["a"]["tag_ids"], ["legacy", "to-read", "two"])
        self.assertEqual(data["books"]["b"]["tag_ids"], ["two", "to-read"])
        for bid in ("a", "b"):
            self.assertEqual(data["books"][bid]["category_id"], "new")
            for key, value in self.data["books"][bid].items():
                if key not in {"category_id", "tag_ids"}:
                    self.assertEqual(data["books"][bid][key], value)
        self.assertEqual(data["books"]["c"], self.data["books"]["c"])
        self.assertEqual(data["settings"], self.data["settings"])
        self.assertEqual(data["futureRoot"], self.data["futureRoot"])
        self.batch({"categoryId": ""})
        self.assertEqual(read_library(self.path)["books"]["a"]["category_id"], "")

    def test_manual_status_survives_automatic_activity_and_auto_is_explicit(self):
        self.batch({"readingStatus": "read"})
        self.service.active("a")
        data = read_library(self.path)
        self.assertEqual(data["books"]["a"]["reading_status_mode"], "manual")
        self.assertEqual(status_for(data["books"]["a"]), "read")
        self.batch({"statusMode": "auto"})
        data = read_library(self.path)
        self.assertEqual(status_for(data["books"]["a"]), "reading")
        self.assertEqual(status_for(data["books"]["b"]), "read")
        self.assertNotIn("reading_status", data["books"]["a"])
        self.assertEqual(data["books"]["a"]["reading_status_mode"], "auto")

    def test_every_invalid_request_leaves_bytes_unchanged(self):
        requests = [
            {"bookIds": [], "patch": {"categoryId": "new"}},
            {"bookIds": ["a", "a"], "patch": {"categoryId": "new"}},
            {"bookIds": ["a", "deleted"], "patch": {"categoryId": "new"}},
            {"bookIds": ["a", {}], "patch": {"categoryId": "new"}},
            {"bookIds": "a", "patch": {"categoryId": "new"}},
            {"bookIds": ["a"], "patch": {"categoryId": []}},
            {"bookIds": ["a"], "patch": {"categoryId": "missing"}},
            {"bookIds": ["a"], "patch": {"addTagIds": ["missing"]}},
            {"bookIds": ["a"], "patch": {"removeTagIds": [[]]}},
            {"bookIds": ["a"], "patch": {"addTagIds": ["one", "one"]}},
            {"bookIds": ["a"], "patch": {"addTagIds": ["one"], "removeTagIds": ["one"]}},
            {"bookIds": ["a"], "patch": {"readingStatus": "bad"}},
            {"bookIds": ["a"], "patch": {"readingStatus": "read", "statusMode": "auto"}},
            {"bookIds": ["a"], "patch": {"statusMode": []}},
            {"bookIds": ["a"], "patch": {"tagIds": ["one"]}},
            {"bookIds": ["a"], "patch": {"addTagIds": [], "removeTagIds": []}},
            {"bookIds": ["a"], "patch": {}},
        ]
        before = self.path.read_bytes()
        for request in requests:
            with self.subTest(request=request), self.assertRaises(FeatureError):
                self.service.update({"action": "batch", **request})
            self.assertEqual(self.path.read_bytes(), before)

    def test_corrupt_tags_in_last_target_do_not_partially_save_first_target(self):
        self.data["books"]["b"]["tag_ids"] = "invalid"
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        before = self.path.read_bytes()
        with self.assertRaises(FeatureError):
            self.batch({"categoryId": "new", "addTagIds": ["to-read"]})
        self.assertEqual(self.path.read_bytes(), before)

    def test_replace_failure_keeps_original_and_removes_temporary(self):
        before = self.path.read_bytes()
        with patch("novelreader.feature_store.os.replace", side_effect=OSError("injected save failure")):
            with self.assertRaises(OSError): self.batch({"categoryId": "new"})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_progress_write_serializes_and_preserves_batch_fields(self):
        entered, release, progress_done = threading.Event(), threading.Event(), threading.Event()
        failures = []
        def paused_save(path, data):
            entered.set()
            if not release.wait(2): raise RuntimeError("test timeout")
            save_library(path, data)
        def edit():
            try: self.batch({"categoryId": "new"})
            except Exception as exc: failures.append(exc)
        def progress():
            try:
                with library_write_lock(self.path):
                    latest = read_library(self.path)
                    latest["books"]["a"]["progress"]["percent"] = 75
                    save_library(self.path, latest)
                progress_done.set()
            except Exception as exc: failures.append(exc)
        with patch("novelreader.feature_store.save_library", side_effect=paused_save):
            edit_thread = threading.Thread(target=edit)
            edit_thread.start()
            self.assertTrue(entered.wait(2))
            progress_thread = threading.Thread(target=progress)
            progress_thread.start()
            self.assertFalse(progress_done.wait(0.05))
            release.set()
            edit_thread.join(2)
            progress_thread.join(2)
        self.assertEqual(failures, [])
        self.assertFalse(edit_thread.is_alive())
        self.assertFalse(progress_thread.is_alive())
        data = read_library(self.path)
        self.assertEqual(data["books"]["a"]["category_id"], "new")
        self.assertEqual(data["books"]["a"]["progress"]["percent"], 75)


if __name__ == "__main__": unittest.main()
