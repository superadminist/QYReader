# -*- coding: utf-8 -*-
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from novelreader import book_loader
from novelreader.import_service import (
    LARGE_FILE_BYTES,
    ImportServiceError,
    LibraryImportService,
)


class LibraryImportServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.library_path = self.root / "data" / "library.json"
        self.environment = patch.dict(
            os.environ,
            {"DOUBAO_NOVEL_DATA": os.fspath(self.library_path.parent)},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.source = self.root / "private" / "测试小说.txt"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("第一章\n第一句。第二句。\n第二章\n第三句。", encoding="utf-8")
        self.service = LibraryImportService(self.library_path)

    def import_source(self, duplicate_mode="overwrite"):
        candidates = self.service.inspect_files([os.fspath(self.source)])
        progress = []
        result = self.service.import_files(
            candidates,
            duplicate_mode,
            True,
            threading.Event(),
            progress.append,
        )
        return candidates, progress, result

    def test_first_import_preserves_legacy_metadata_cache_and_backup(self):
        candidates, progress, result = self.import_source()

        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(len(progress), 2)
        payload = json.loads(self.library_path.read_text(encoding="utf-8"))
        metadata = payload["books"][candidates[0].book_id]
        self.assertEqual(metadata["path"], os.fspath(self.source))
        self.assertEqual(metadata["progress"], {
            "chapter_idx": 0,
            "char_offset": 0,
            "percent": 0.0,
        })
        self.assertTrue(Path(metadata["source_bak"]).is_file())
        cache_path = self.library_path.parent / "cache" / f"{candidates[0].book_id}.json"
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        self.assertEqual(cache["v"], book_loader.CONTENT_CACHE_VERSION)

    @unittest.skipUnless(os.name == "nt", "Windows read-handle semantics")
    def test_paste_import_keeps_the_previous_library_when_replacement_stays_blocked(self):
        self.assertEqual(self.import_source()[2]["succeeded"], 1)
        before = self.library_path.read_bytes()
        real_replace = os.replace
        attempts = []

        def observe_replace(source, target):
            if Path(target) == self.library_path:
                attempts.append(target)
            return real_replace(source, target)

        with self.library_path.open("rb"):
            with patch("novelreader.storage.os.replace", side_effect=observe_replace):
                result = self.service.import_pasted_text(
                    "写入阻塞", "这次替换应当失败。", threading.Event(), lambda event: None,
                )

        self.assertEqual(len(attempts), 4)
        self.assertEqual(result["succeeded"], 0)
        self.assertEqual(result["results"][0]["error"]["code"], "LIBRARY_WRITE_FAILED")
        self.assertEqual(self.library_path.read_bytes(), before)

    def test_bridge_projections_and_progress_never_expose_paths(self):
        candidates, progress, result = self.import_source()

        public_json = json.dumps(candidates[0].public_data(), ensure_ascii=False)
        progress_json = json.dumps(progress, ensure_ascii=False)
        result_json = json.dumps(result, ensure_ascii=False)
        private_root = os.fspath(self.root)
        self.assertNotIn(private_root, public_json)
        self.assertNotIn(private_root, progress_json)
        self.assertNotIn(private_root, result_json)

    def test_damaged_library_fails_closed_without_writing(self):
        self.library_path.parent.mkdir(parents=True)
        original = b"{damaged"
        self.library_path.write_bytes(original)

        with self.assertRaises(ImportServiceError) as caught:
            self.service.import_pasted_text(
                "标题",
                "正文",
                threading.Event(),
                lambda _event: None,
            )

        self.assertEqual(caught.exception.code, "LIBRARY_INVALID")
        self.assertEqual(self.library_path.read_bytes(), original)
        self.assertFalse((self.library_path.parent / "pasted").exists())
        self.assertFalse((self.library_path.parent / "cache").exists())

    def test_duplicate_overwrite_uses_cache_and_reparse_ignores_it(self):
        candidates, _, _ = self.import_source()
        duplicate = self.service.inspect_files([os.fspath(self.source)])
        self.assertTrue(duplicate[0].duplicate_exists)

        with patch("novelreader.import_service.book_loader.parse_book") as parse:
            overwrite = self.service.import_files(
                duplicate,
                "overwrite",
                True,
                threading.Event(),
                lambda _event: None,
            )
        self.assertEqual(overwrite["succeeded"], 1)
        parse.assert_not_called()

        reparsed = book_loader.BookContent(
            "重新解析",
            "",
            "txt",
            [book_loader.Chapter("正文", "新正文。")],
        )
        with patch(
            "novelreader.import_service.book_loader.parse_book",
            return_value=reparsed,
        ) as parse:
            result = self.service.import_files(
                duplicate,
                "reparse",
                True,
                threading.Event(),
                lambda _event: None,
            )
        self.assertEqual(result["succeeded"], 1)
        parse.assert_called_once()
        payload = json.loads(self.library_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["books"][candidates[0].book_id]["title"], "重新解析")

    def test_duplicate_cancel_keeps_library_unchanged(self):
        self.import_source()
        duplicate = self.service.inspect_files([os.fspath(self.source)])
        before = self.library_path.read_bytes()
        progress = []

        result = self.service.import_files(
            duplicate,
            "cancel",
            True,
            threading.Event(),
            progress.append,
        )

        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(result["processed"], 0)
        self.assertEqual(progress, [])
        self.assertEqual(self.library_path.read_bytes(), before)

    def test_reparse_failure_does_not_fall_back_or_replace_old_data(self):
        candidates, _, _ = self.import_source()
        cache_path = self.library_path.parent / "cache" / f"{candidates[0].book_id}.json"
        library_before = self.library_path.read_bytes()
        cache_before = cache_path.read_bytes()
        duplicate = self.service.inspect_files([os.fspath(self.source)])

        with patch(
            "novelreader.import_service.book_loader.parse_book",
            side_effect=ValueError("damaged"),
        ):
            result = self.service.import_files(
                duplicate,
                "reparse",
                True,
                threading.Event(),
                lambda _event: None,
            )

        self.assertEqual(result["succeeded"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["results"][0]["error"]["code"], "PARSE_FAILED")
        self.assertEqual(self.library_path.read_bytes(), library_before)
        self.assertEqual(cache_path.read_bytes(), cache_before)

    def test_reparse_does_not_replace_cache_before_library_commit(self):
        candidates, _, _ = self.import_source()
        cache_path = self.library_path.parent / "cache" / f"{candidates[0].book_id}.json"
        cache_before = cache_path.read_bytes()
        duplicate = self.service.inspect_files([os.fspath(self.source)])
        reparsed = book_loader.BookContent(
            "尚未提交",
            "",
            "txt",
            [book_loader.Chapter("正文", "不能提前覆盖缓存。")],
        )

        with patch(
            "novelreader.import_service.book_loader.parse_book",
            return_value=reparsed,
        ), patch(
            "novelreader.import_service.Storage.add_book",
            side_effect=OSError("read only"),
        ):
            result = self.service.import_files(
                duplicate,
                "reparse",
                True,
                threading.Event(),
                lambda _event: None,
            )

        self.assertEqual(result["succeeded"], 0)
        self.assertEqual(result["results"][0]["error"]["code"], "LIBRARY_WRITE_FAILED")
        self.assertEqual(cache_path.read_bytes(), cache_before)

    def test_cancel_finishes_current_item_and_stops_before_the_next(self):
        second = self.source.with_name("第二本.txt")
        second.write_text("第二本正文。", encoding="utf-8")
        candidates = self.service.inspect_files([
            os.fspath(self.source),
            os.fspath(second),
        ])
        cancel_event = threading.Event()

        def progress(event):
            if event["item"]["status"] == "succeeded":
                cancel_event.set()

        result = self.service.import_files(
            candidates,
            "overwrite",
            True,
            cancel_event,
            progress,
        )

        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(result["processed"], 1)
        payload = json.loads(self.library_path.read_text(encoding="utf-8"))
        self.assertIn(candidates[0].book_id, payload["books"])
        self.assertNotIn(candidates[1].book_id, payload["books"])

    def test_large_file_requires_confirmation_before_any_write(self):
        with patch(
            "novelreader.import_service.os.path.getsize",
            return_value=LARGE_FILE_BYTES + 1,
        ):
            candidates = self.service.inspect_files([os.fspath(self.source)])
        self.assertTrue(candidates[0].large)

        with self.assertRaises(ImportServiceError) as caught:
            self.service.import_files(
                candidates,
                "overwrite",
                False,
                threading.Event(),
                lambda _event: None,
            )

        self.assertEqual(caught.exception.code, "LARGE_FILE_CONFIRMATION_REQUIRED")
        self.assertFalse(self.library_path.exists())

    def test_pasted_text_uses_compatible_unique_persistent_sources(self):
        results = []
        for _ in range(2):
            results.append(self.service.import_pasted_text(
                "",
                "首行标题\n正文内容。",
                threading.Event(),
                lambda _event: None,
            ))

        pasted = list((self.library_path.parent / "pasted").glob("*.txt"))
        payload = json.loads(self.library_path.read_text(encoding="utf-8"))
        self.assertEqual(len(pasted), 2)
        self.assertEqual(len(payload["books"]), 2)
        self.assertNotEqual(
            results[0]["lastImportedBookId"],
            results[1]["lastImportedBookId"],
        )
        self.assertTrue(all(path.read_text(encoding="utf-8").startswith(
            "首行标题\n\n首行标题"
        ) for path in pasted))

    def test_cancelled_paste_does_not_create_an_orphan_source(self):
        cancel_event = threading.Event()
        cancel_event.set()

        result = self.service.import_pasted_text(
            "标题",
            "正文",
            cancel_event,
            lambda _event: None,
        )

        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(result["processed"], 0)
        self.assertFalse((self.library_path.parent / "pasted").exists())


if __name__ == "__main__":
    unittest.main()
