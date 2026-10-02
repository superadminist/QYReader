# -*- coding: utf-8 -*-
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from novelreader.book_loader import BookContent, Chapter
from novelreader.import_service import LibraryImportService
from novelreader.reader_service import (
    BLOCK_CHAR_LIMIT,
    SEARCH_RESULT_LIMIT,
    WINDOW_BLOCK_LIMIT,
    WINDOW_CHAR_LIMIT,
    ReaderService,
    ReaderServiceError,
)
from novelreader.storage import Storage


class ReaderServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.data_root = self.root / "data"
        self.data_root.mkdir()
        self.environment = patch.dict(
            os.environ,
            {"DOUBAO_NOVEL_DATA": os.fspath(self.data_root)},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.library_path = self.data_root / "library.json"

    def add_book(self, name="reader.txt", chapters=None, cache=True):
        source = self.root / "private" / name
        source.parent.mkdir(exist_ok=True)
        source.write_text("source", encoding="utf-8")
        content = BookContent(
            Path(name).stem,
            "测试作者",
            Path(name).suffix.lstrip("."),
            chapters or [Chapter("第一章", "甲😀乙。第二句。")],
        )
        storage = Storage(os.fspath(self.library_path))
        book_id = storage.book_id(os.fspath(source))
        metadata = {
            "id": book_id,
            "title": content.title,
            "author": content.author,
            "format": content.format,
            "path": os.fspath(source),
            "added_at": time.time(),
            "last_read_at": time.time(),
            "total_chars": content.total_chars,
            "chapter_titles": [chapter.title for chapter in content.chapters],
            "progress": {"chapter_idx": 0, "char_offset": 0, "percent": 0.0},
        }
        storage.add_book(metadata)
        if cache:
            storage.write_cache(book_id, content)
        return book_id, source, content

    def test_open_returns_real_contract_data_without_paths(self):
        book_id, source, content = self.add_book(
            chapters=[Chapter("序章", "开头。"), Chapter("第二章", "后续正文。")],
        )
        payload = json.loads(self.library_path.read_text(encoding="utf-8"))
        payload["books"][book_id]["progress"] = {
            "chapter_idx": 1,
            "char_offset": 2,
            "percent": 99,
        }
        self.library_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        opened = ReaderService(self.library_path).open_book(book_id)

        self.assertEqual(opened["book"]["id"], book_id)
        self.assertEqual(opened["book"]["chapters"][1]["title"], "第二章")
        self.assertEqual(opened["position"]["chapterIndex"], 1)
        self.assertEqual(opened["position"]["charOffset"], 2)
        expected = (len(content.chapters[0].content) + 2) / content.total_chars * 100
        self.assertEqual(opened["position"]["progressPercent"], round(expected, 3))
        serialized = json.dumps(opened, ensure_ascii=False)
        self.assertNotIn(os.fspath(source), serialized)
        self.assertNotIn("source_bak", serialized)

    def test_single_active_session_invalidates_the_previous_one(self):
        first_id, _, _ = self.add_book("first.txt")
        second_id, _, _ = self.add_book("second.txt")
        service = ReaderService(self.library_path)
        first = service.open_book(first_id)
        second = service.open_book(second_id)

        with self.assertRaises(ReaderServiceError) as caught:
            service.get_window(first["sessionId"], 0, 0)

        self.assertEqual(caught.exception.code, "READER_SESSION_EXPIRED")
        self.assertEqual(service.get_window(second["sessionId"], 0, 0)["bookId"], second_id)

    def test_source_backup_and_old_cache_fallbacks_remain_readable(self):
        book_id, source, content = self.add_book(cache=False)
        storage = Storage(os.fspath(self.library_path))
        backup = storage.backup_source(book_id, os.fspath(source))
        metadata = storage.get_book(book_id)
        metadata["source_bak"] = backup
        storage.save()
        source.unlink()

        with patch("novelreader.reader_service.book_loader.parse_book", return_value=content):
            opened = ReaderService(self.library_path).open_book(book_id)
        self.assertEqual(opened["book"]["totalChars"], content.total_chars)

        storage = Storage(os.fspath(self.library_path))
        cache_path = Path(storage.cache_path(book_id))
        cached = content.to_dict()
        cached["v"] = 0
        cache_path.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
        Path(backup).unlink()
        opened = ReaderService(self.library_path).open_book(book_id)
        self.assertEqual(opened["book"]["title"], content.title)

    def test_window_is_bounded_and_blocks_preserve_code_point_offsets(self):
        long_text = ("甲😀乙" * 34_000)[:100_000]
        book_id, _, _ = self.add_book(chapters=[Chapter("长章", long_text)])
        service = ReaderService(self.library_path)
        opened = service.open_book(book_id)

        window = service.get_window(opened["sessionId"], 0, 50_000)

        self.assertLessEqual(len(window["blocks"]), WINDOW_BLOCK_LIMIT)
        self.assertLessEqual(sum(len(block["text"]) for block in window["blocks"]), WINDOW_CHAR_LIMIT)
        self.assertTrue(all(len(block["text"]) <= BLOCK_CHAR_LIMIT for block in window["blocks"]))
        self.assertLessEqual(window["windowStartOffset"], 50_000)
        self.assertGreaterEqual(window["windowEndOffset"], 50_000)
        joined = "".join(block["text"] for block in window["blocks"])
        self.assertEqual(joined, long_text[window["windowStartOffset"]:window["windowEndOffset"]])
        emoji_offset = long_text.index("😀")
        self.assertEqual(long_text[emoji_offset], "😀")

    def test_long_paragraphs_split_at_2048_and_paragraph_flags_are_stable(self):
        text = "甲" * 5_000 + "\n" + "乙" * 15_000
        book_id, _, _ = self.add_book(chapters=[Chapter("分块", text)])
        service = ReaderService(self.library_path)
        opened = service.open_book(book_id)
        blocks = service.get_window(opened["sessionId"], 0, 0)["blocks"]

        self.assertTrue(all(len(block["text"]) <= BLOCK_CHAR_LIMIT for block in blocks))
        self.assertTrue(blocks[0]["startsParagraph"])
        self.assertFalse(blocks[0]["endsParagraph"])
        second_paragraph = next(block for block in blocks if block["startOffset"] == 5_001)
        self.assertTrue(second_paragraph["startsParagraph"])

    def test_navigation_and_progress_keep_legacy_storage_semantics(self):
        chapters = [Chapter("一", "a" * 10), Chapter("二", "b" * 30)]
        book_id, _, _ = self.add_book(chapters=chapters)
        service = ReaderService(self.library_path)
        opened = service.open_book(book_id)
        session_id = opened["sessionId"]

        navigated = service.navigate(session_id, {"kind": "percent", "percent": 50})
        self.assertEqual(navigated["position"]["chapterIndex"], 1)
        saved = service.update_position(session_id, 1, 10)

        self.assertTrue(saved["updated"])
        storage = Storage(os.fspath(self.library_path))
        progress = storage.get_book(book_id)["progress"]
        self.assertEqual(progress, {
            "chapter_idx": 1,
            "char_offset": 10,
            "percent": 50.0,
        })
        self.assertEqual(storage.get_setting("last_book"), book_id)
        self.assertGreater(storage.get_book(book_id)["last_read_at"], 0)

    def test_background_progress_flushes_on_switch_and_preserves_library_changes(self):
        first, _, _ = self.add_book(chapters=[Chapter("一", "正文。" * 100)])
        service = ReaderService(self.library_path, deferred_progress=True)
        self.addCleanup(service.shutdown)
        opened = service.open_book(first)
        for offset in range(1, 100):
            service.update_position(opened["sessionId"], 0, offset)
        second, _, _ = self.add_book(name="second.txt")
        storage = Storage(os.fspath(self.library_path))
        storage.set_setting("volume", 42)
        service.open_book(second)
        saved = Storage(os.fspath(self.library_path))
        self.assertEqual(saved.get_book(first)["progress"]["char_offset"], 99)
        self.assertIsNotNone(saved.get_book(second))
        self.assertEqual(saved.get_setting("volume"), 42)

    def test_background_navigation_and_close_save_exact_unicode_position(self):
        book_id, _, _ = self.add_book()
        service = ReaderService(self.library_path, deferred_progress=True)
        self.addCleanup(service.shutdown)
        opened = service.open_book(book_id)
        service.navigate(opened["sessionId"], {"kind": "position", "chapterIndex": 0, "charOffset": 2})
        service.close_session(opened["sessionId"])
        restored = service.open_book(book_id)
        self.assertEqual(restored["position"]["charOffset"], 2)

    def test_removing_active_book_drains_pending_progress_and_closes_cleanly(self):
        from PySide6.QtCore import QCoreApplication
        from novelreader.library_service import LibraryQueryService
        from novelreader.qt_bridge import DesktopBridge
        from tests.test_stage3_qt_bridge import _Playback, _Window
        app = QCoreApplication.instance() or QCoreApplication([])
        book_id, _, _ = self.add_book()
        service = ReaderService(self.library_path, deferred_progress=True)
        opened = service.open_book(book_id)
        service.update_position(opened["sessionId"], 0, 2)
        playback = _Playback()
        playback.session_id = opened["sessionId"]
        playback.session_identity = lambda: {"sessionId": opened["sessionId"], "bookId": book_id}
        bridge = DesktopBridge(_Window(), library=LibraryQueryService(self.library_path), reader=service, playback=playback)
        self.addCleanup(bridge.shutdown)
        errors = []
        bridge.bridgeError.connect(errors.append)
        removed = json.loads(bridge.removeLibraryBook(book_id))
        self.assertTrue(removed["ok"], removed)
        self.assertIsNone(Storage(os.fspath(self.library_path)).get_book(book_id))
        bridge.shutdown()
        self.assertEqual(errors, [])
        self.assertFalse(service._progress_writer._thread.is_alive())

    def test_update_settings_maps_contract_fields_and_preserves_legacy_settings(self):
        book_id, _, _ = self.add_book()
        service = ReaderService(self.library_path)
        session_id = service.open_book(book_id)["sessionId"]

        updated = service.update_settings(session_id, {
            "fontFamily": "宋体",
            "fontSize": 20,
            "lineSpacing": 2.0,
            "paragraphMode": 3,
            "firstLineIndent": False,
            "ttsRate": 320,
            "ttsVoiceId": "voice-id",
            "volume": 0,
            "sentenceGapSeconds": 0.0,
        })

        self.assertEqual(updated, {
            "fontFamily": "宋体",
            "fontSize": 20,
            "lineSpacing": 2.0,
            "paragraphMode": 3,
            "firstLineIndent": False,
            "ttsRate": 320,
            "ttsVoiceId": "voice-id",
            "volume": 0,
            "sentenceGapSeconds": 0.0,
        })
        stored = Storage(os.fspath(self.library_path)).settings()
        self.assertEqual(stored["font_family"], "宋体")
        self.assertEqual(stored["tts_sentence_gap"], 0.0)
        self.assertEqual(stored["theme"], "护眼")

    def test_update_settings_rejects_invalid_ranges_without_writing(self):
        book_id, _, _ = self.add_book()
        service = ReaderService(self.library_path)
        session_id = service.open_book(book_id)["sessionId"]
        before = self.library_path.read_bytes()

        for patch_value in ({"fontSize": 49}, {"lineSpacing": True}, {"theme": "夜间"}):
            with self.subTest(patch=patch_value):
                with self.assertRaises(ReaderServiceError) as caught:
                    service.update_settings(session_id, patch_value)
                self.assertEqual(caught.exception.code, "INVALID_REQUEST")

        self.assertEqual(self.library_path.read_bytes(), before)

    def test_session_content_is_a_detached_snapshot_and_expires_with_session(self):
        first_id, _, first_content = self.add_book("first.txt")
        second_id, _, _ = self.add_book("second.txt")
        service = ReaderService(self.library_path)
        first_session = service.open_book(first_id)["sessionId"]

        snapshot = service.get_session_content(first_session)
        self.assertEqual(snapshot.chapters[0].content, first_content.chapters[0].content)
        snapshot.chapters[0].content = "changed"
        self.assertEqual(
            service.get_session_content(first_session).chapters[0].content,
            first_content.chapters[0].content,
        )

        service.open_book(second_id)
        with self.assertRaises(ReaderServiceError) as caught:
            service.get_session_content(first_session)
        self.assertEqual(caught.exception.code, "READER_SESSION_EXPIRED")

    def test_search_reuses_exact_non_overlapping_semantics_and_cursor_pages(self):
        text = "aba ABA " + ("词 " * 60)
        book_id, _, _ = self.add_book(chapters=[Chapter("搜索章", text)])
        service = ReaderService(self.library_path)
        session_id = service.open_book(book_id)["sessionId"]

        exact = service.search(session_id, "aba")
        self.assertEqual(exact["total"], 1)
        self.assertEqual(exact["results"][0]["startOffset"], 0)

        first = service.search(session_id, "词")
        self.assertEqual(first["total"], 60)
        self.assertEqual(len(first["results"]), 50)
        self.assertTrue(first["nextCursor"])
        second = service.search(session_id, "词", first["nextCursor"])
        self.assertEqual(len(second["results"]), 10)
        self.assertEqual(second["nextCursor"], "")

    def test_search_stops_at_legacy_limit_and_honors_cancellation(self):
        book_id, _, _ = self.add_book(chapters=[Chapter("搜索章", "词" * 700)])
        service = ReaderService(self.library_path)
        session_id = service.open_book(book_id)["sessionId"]

        page = service.search(session_id, "词")
        self.assertEqual(page["total"], SEARCH_RESULT_LIMIT)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ReaderServiceError) as caught:
            service.search(session_id, "词", cancel_event=cancel)
        self.assertEqual(caught.exception.code, "SEARCH_CANCELLED")

    def test_bookmarks_use_real_unicode_offsets_and_legacy_fields(self):
        book_id, _, _ = self.add_book(chapters=[Chapter("书签章", "甲😀乙。下一句。")])
        service = ReaderService(self.library_path)
        session_id = service.open_book(book_id)["sessionId"]

        bookmark = service.add_bookmark(session_id, 0, 1, 3, "")
        self.assertEqual(bookmark["text"], "😀乙")
        self.assertEqual(bookmark["startOffset"], 1)
        page = service.list_bookmarks(session_id)
        self.assertEqual(page["total"], 1)
        stored = Storage(os.fspath(self.library_path)).get_bookmarks(book_id)[0]
        self.assertEqual(stored["chapter_idx"], 0)
        self.assertEqual(stored["offset"], 1)
        self.assertEqual(stored["offset_end"], 3)

        removed = service.remove_bookmark(session_id, bookmark["id"])
        self.assertTrue(removed["removed"])
        self.assertEqual(service.list_bookmarks(session_id)["total"], 0)

    def test_global_speech_settings_work_without_an_open_book(self):
        service = ReaderService(self.library_path)
        updated = service.update_global_settings({
            "ttsVoiceId": "zh-CN-XiaoxiaoNeural",
            "ttsRate": 280,
            "sentenceGapSeconds": 0.35,
        })
        self.assertEqual(updated["ttsVoiceId"], "zh-CN-XiaoxiaoNeural")
        self.assertEqual(updated["ttsRate"], 280)
        self.assertEqual(updated["sentenceGapSeconds"], 0.35)
        self.assertEqual(ReaderService(self.library_path).settings_state()["ttsRate"], 280)

    def test_global_settings_create_a_fresh_library_but_fail_closed_when_damaged(self):
        fresh_path = self.root / "fresh" / "library.json"
        service = ReaderService(fresh_path)
        self.assertEqual(service.settings_state()["ttsRate"], 200)
        service.update_global_settings({"ttsRate": 240})
        self.assertEqual(Storage(os.fspath(fresh_path)).get_setting("tts_rate"), 240)

        original = b"{damaged"
        fresh_path.write_bytes(original)
        with self.assertRaises(ReaderServiceError) as caught:
            service.update_global_settings({"ttsRate": 260})
        self.assertEqual(caught.exception.code, "LIBRARY_INVALID")
        self.assertEqual(fresh_path.read_bytes(), original)

    def test_damaged_library_fails_closed_without_rewrite(self):
        original = b"{damaged"
        self.library_path.write_bytes(original)

        with self.assertRaises(ReaderServiceError) as caught:
            ReaderService(self.library_path).open_book("book")

        self.assertEqual(caught.exception.code, "LIBRARY_INVALID")
        self.assertEqual(self.library_path.read_bytes(), original)

    def test_import_progress_and_settings_writes_do_not_lose_each_other(self):
        first_id, _, _ = self.add_book("first.txt")
        service = ReaderService(self.library_path)
        session_id = service.open_book(first_id)["sessionId"]
        second = self.root / "private" / "second-import.txt"
        second.write_text("第二本正文。", encoding="utf-8")
        importer = LibraryImportService(self.library_path)
        candidates = importer.inspect_files([os.fspath(second)])
        barrier = threading.Barrier(3)
        failures = []

        def save_progress():
            try:
                barrier.wait()
                service.update_position(session_id, 0, 2)
            except Exception as exc:  # pragma: no cover - asserted below
                failures.append(exc)

        def import_second():
            try:
                barrier.wait()
                importer.import_files(
                    candidates,
                    "overwrite",
                    True,
                    threading.Event(),
                    lambda _event: None,
                )
            except Exception as exc:  # pragma: no cover - asserted below
                failures.append(exc)

        def save_settings():
            try:
                barrier.wait()
                service.update_settings(session_id, {"volume": 35})
            except Exception as exc:  # pragma: no cover - asserted below
                failures.append(exc)

        threads = [
            threading.Thread(target=save_progress),
            threading.Thread(target=import_second),
            threading.Thread(target=save_settings),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)

        self.assertEqual(failures, [])
        storage = Storage(os.fspath(self.library_path))
        self.assertIn(first_id, storage.all_books())
        self.assertIn(candidates[0].book_id, storage.all_books())
        self.assertEqual(storage.get_book(first_id)["progress"]["char_offset"], 2)
        self.assertEqual(storage.get_setting("volume"), 35)


if __name__ == "__main__":
    unittest.main()
