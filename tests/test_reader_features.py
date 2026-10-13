"""Isolated acceptance for metadata preservation, anchors, clocks and archives."""
import datetime as dt
import io
import json
import os
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

from novelreader.activity_service import ActivityService
from novelreader.annotations import locate, make_anchor
from novelreader.feature_store import FeatureError, OrganizationService, read_library
from novelreader.import_service import LibraryImportService
from novelreader.kokoro_service import safe_extract
from novelreader.reader_service import ReaderService


class ReaderFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"DOUBAO_NOVEL_DATA": str(self.root)})
        self.environment.start()
        self.path = self.root / "library.json"
        self.path.write_text(json.dumps({"books": {"b": {"title": "测试", "progress": {"percent": 40}, "extra": {"untouched": True}}}, "settings": {}, "unknownRoot": 123}), encoding="utf-8")

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_organization_preserves_unknown_fields_and_backup(self):
        before = self.path.read_bytes()
        service = OrganizationService(self.path)
        state = service.update({"action": "create", "kind": "categories", "name": "学习"})
        category = state["categories"][0]["id"]
        service.update({"action": "book", "bookId": "b", "patch": {"contentType": "reference", "categoryId": category, "tagIds": ["to-read"], "readingStatus": "read"}})
        stored = read_library(self.path)
        self.assertEqual(stored["unknownRoot"], 123)
        self.assertEqual(stored["books"]["b"]["extra"], {"untouched": True})
        self.assertEqual(stored["books"]["b"]["progress"]["percent"], 40)
        self.assertEqual(self.path.with_name("library.json.before-reader-features.bak").read_bytes(), before)
        service.update({"action": "delete", "kind": "categories", "id": category})
        self.assertEqual(read_library(self.path)["books"]["b"]["category_id"], "")
        service.active("b")
        self.assertEqual(read_library(self.path)["books"]["b"]["reading_status"], "read")

    def test_corrupted_library_is_never_replaced(self):
        self.path.write_bytes(b"broken original data")
        with self.assertRaises(FeatureError):
            OrganizationService(self.path).update({"action": "create", "kind": "tags", "name": "test"})
        self.assertEqual(self.path.read_bytes(), b"broken original data")

    def test_repeat_import_preserves_progress_notes_and_unknown_metadata(self):
        source = self.root / "fixture.txt"
        source.write_text("第一章 测试\n甲😀乙。这是自建测试正文。", encoding="utf-8")
        service = LibraryImportService(self.path)
        def run():
            candidates = service.inspect_files([str(source)])
            return service.import_files(candidates, "reparse", True, threading.Event(), lambda x: None)
        bid = run()["lastImportedBookId"]
        data = read_library(self.path)
        data["books"][bid].update({"progress": {"percent": 70, "futureField": 99}, "bookmarks": [{"id": "old", "text": "甲"}], "tag_ids": ["to-read"], "extra": "keep"})
        self.path.write_text(json.dumps(data), encoding="utf-8")
        run()
        book = read_library(self.path)["books"][bid]
        self.assertEqual(book["progress"], {"percent": 70, "futureField": 99})
        self.assertEqual(book["bookmarks"][0]["id"], "old")
        self.assertEqual(book["extra"], "keep")

    def test_annotation_edit_export_and_unicode_offsets(self):
        from novelreader.storage import Storage
        from novelreader.book_loader import BookContent, Chapter
        storage = Storage(str(self.path))
        text = "甲😀乙。后续文字。"
        storage.write_cache("b", BookContent("测试", "", "txt", [Chapter("章节", text)]))
        service = ReaderService(self.path)
        session = service.open_book("b")["sessionId"]
        note = service.add_bookmark(session, 0, 1, 3, "", kind="annotation", color="blue")
        self.assertEqual(note["text"], "😀乙")
        self.assertEqual(note["note"], "")
        updated = service.update_bookmark(session, note["id"], {"note": "备注", "color": "green"})
        self.assertEqual(updated["note"], "备注")
        self.assertIn("> 😀乙", service.export_bookmarks(session, "md"))
        self.assertIn("备注：备注", service.export_bookmarks(session, "txt"))
        service.update_position(session, 0, len(text))
        self.assertEqual(read_library(self.path)["books"]["b"]["reading_status"], "read")

    def test_anchor_relocation_does_not_guess_ambiguous_quotes(self):
        content = "原有上下文" + "选中文字" + "后文"
        start = len("原有上下文")
        note = {"offset": start, "offset_end": start + 4, "anchor": make_anchor(content, start, start + 4)}
        self.assertEqual(locate(note, "新增" + content), (start + 2, start + 6))
        self.assertIsNone(locate(note, content + "\n" + content))
        self.assertIsNone(locate(note, "完全不同的正文"))

    def test_malicious_tar_paths_and_links_are_rejected(self):
        for name, kind in [("../escape", tarfile.REGTYPE), ("C:/escape", tarfile.REGTYPE), ("root/link", tarfile.SYMTYPE)]:
            archive = self.root / "malicious.tar.bz2"
            with tarfile.open(archive, "w:bz2") as output:
                member = tarfile.TarInfo(name); member.type = kind
                if kind == tarfile.REGTYPE:
                    member.size = 1; output.addfile(member, io.BytesIO(b"x"))
                else:
                    member.linkname = "../escape"; output.addfile(member)
            with self.assertRaises(FeatureError):
                safe_extract(archive, self.root / "output")
            self.assertFalse((self.root.parent / "escape").exists())

    def test_preview_reuses_controller_and_restores_book_position(self):
        from novelreader.tts_engine import SpeechController
        from novelreader.playback_service import PlaybackService
        from novelreader.book_loader import BookContent, Chapter
        speech = SpeechController()
        service = PlaybackService(speech)
        book = BookContent("原书", "", "txt", [Chapter("章节", "第一句。第二句。")])
        with patch.object(speech, "_ensure_thread"):
            service.bind_session("session", "book", book, 0, 4)
            service.control("play")
            position = service.snapshot()["position"]
            service.preview("试听句。", "kokoro:v1.0:zf_xiaoni")
            self.assertIs(service.speech_controller, speech)
            self.assertEqual(service.snapshot()["purpose"], "preview")
            speech._post({"type": "finished"}, speech.generation())
            events = service.drain_events()
            self.assertTrue(any(e["playback"]["purpose"] == "preview" for e in events))
            self.assertEqual(service.snapshot()["position"], position)
            self.assertEqual(service.snapshot()["purpose"], "book")
            self.assertEqual(service.snapshot()["status"], "paused")
            self.assertEqual(speech.backend(), "sapi")
        service.shutdown()

    def test_model_import_rejects_corruption_and_preserves_source_package(self):
        from novelreader.kokoro_service import KokoroService
        package = self.root / "user-model.tar.bz2"
        package.write_bytes(b"not the official model")
        service = KokoroService(self.root)
        service.start(package)
        service.thread.join(timeout=2)
        self.assertEqual(service.snapshot()["error"]["code"], "MODEL_CHECKSUM_FAILED")
        self.assertEqual(package.read_bytes(), b"not the official model")
        self.assertFalse(service.directory.exists())
        service.close()

    def test_ready_wav_waits_for_resume_before_starting_audio(self):
        from novelreader.tts_engine import SpeechController
        speech = SpeechController()
        speech._state, speech._gen, speech._book = "paused", 1, object()
        opened = threading.Event()
        with patch("novelreader.tts_engine._mci_open", side_effect=lambda path: opened.set()), patch("novelreader.tts_engine._mci_set_volume"), patch("novelreader.tts_engine._set_process_volume"), patch("novelreader.tts_engine._mci_play") as play, patch("novelreader.tts_engine._mci_playing", return_value=False), patch("novelreader.tts_engine._mci_stop"), patch("novelreader.tts_engine._mci_close"):
            thread = threading.Thread(target=speech._speak_edge_play, args=(b"fixture", 1, {"type": "sentence_start"}, "kokoro"))
            thread.start()
            self.assertTrue(opened.wait(1))
            self.assertFalse(play.called)
            speech.resume()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(play.call_count, 1)
        speech.shutdown()

    def test_sentence_generation_is_single_flight_and_cancel_discards_lookahead(self):
        from novelreader.kokoro_service import KokoroService
        service = KokoroService(self.root)
        service.state["status"] = "ready"
        ready, release = threading.Event(), threading.Event()
        output = self.root / "generated.wav"
        output.write_bytes(b"test fixture")
        def generate(*args):
            ready.set()
            release.wait(2)
            return output
        with patch.object(service, "_generate", side_effect=generate) as mock:
            first = service.request("当前句", "kokoro:v1.0:zf_xiaobei", 200)
            self.assertTrue(ready.wait(1))
            same = service.request("当前句", "kokoro:v1.0:zf_xiaobei", 200)
            following = service.request("下一句", "kokoro:v1.0:zf_xiaobei", 200)
            self.assertIs(first, same)
            service.cancel_pending()
            self.assertTrue(following.cancelled())
            release.set()
            self.assertEqual(first.result(timeout=2), output)
            self.assertEqual(mock.call_count, 1)
        service.close()

    def test_shutdown_does_not_wait_for_blocked_native_synthesis(self):
        import time
        from novelreader.kokoro_service import KokoroService
        service = KokoroService(self.root)
        service.state["status"] = "ready"
        entered, release = threading.Event(), threading.Event()
        def blocked(*args):
            entered.set(); release.wait(2); return self.root / "fixture.wav"
        with patch.object(service, "_generate", side_effect=blocked):
            future = service.request("阻塞测试", "kokoro:v1.0:zf_xiaobei", 200)
            self.assertTrue(entered.wait(1))
            start = time.monotonic()
            service.close()
            self.assertLess(time.monotonic() - start, .5)
            self.assertTrue(service.executor.thread.daemon)
            release.set()
            future.result(timeout=2)

    def test_bridge_export_utf8_cancel_and_protect_library(self):
        from PySide6.QtCore import QCoreApplication, QObject
        from novelreader.qt_bridge import DesktopBridge
        from novelreader.library_service import LibraryQueryService
        from novelreader.book_loader import BookContent, Chapter
        from novelreader.storage import Storage
        app = QCoreApplication.instance() or QCoreApplication([])
        reader = ReaderService(self.path)
        Storage(str(self.path)).write_cache("b", BookContent("笔记导出测试", "", "txt", [Chapter("正文", "第一句。第二句。")]))
        session = reader.open_book("b")["sessionId"]
        reader.add_bookmark(session, 0, 0, 4, "中文备注", kind="annotation")
        window = QObject()
        with patch("novelreader.qt_bridge.SpeechController.list_voices", return_value=[]):
            bridge = DesktopBridge(window, library=LibraryQueryService(self.path), reader=reader)
        try:
            request = json.dumps({"action": "exportNotes", "sessionId": session, "format": "md"})
            output = self.root / "notes.md"
            with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(output), "")):
                response = json.loads(bridge.readerFeatureAction(request))
            self.assertTrue(response["ok"])
            self.assertIn("中文备注", output.read_text(encoding="utf-8"))
            with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=("", "")):
                response = json.loads(bridge.readerFeatureAction(request))
            self.assertTrue(response["data"]["cancelled"])
            before = self.path.read_bytes()
            with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(self.path), "")):
                response = json.loads(bridge.readerFeatureAction(request))
            self.assertEqual(response["error"]["code"], "EXPORT_SOURCE_PROTECTED")
            self.assertEqual(before, self.path.read_bytes())
        finally:
            bridge.shutdown()

    def test_bridge_model_variant_updates_voice_availability_and_rejects_active_playback(self):
        from PySide6.QtCore import QCoreApplication, QObject
        from novelreader.qt_bridge import DesktopBridge
        from novelreader.library_service import LibraryQueryService
        app = QCoreApplication.instance() or QCoreApplication([])
        window = QObject()
        with patch("novelreader.qt_bridge.SpeechController.list_voices", return_value=[]):
            bridge = DesktopBridge(window, library=LibraryQueryService(self.path), reader=ReaderService(self.path))
        try:
            updates = []
            bridge.speechPreferencesChanged.connect(lambda raw: updates.append(json.loads(raw)))
            request = json.dumps({"action": "modelVariant", "variant": "fp32"})
            response = json.loads(bridge.readerFeatureAction(request))
            self.assertTrue(response["ok"])
            self.assertEqual(response["data"]["variant"], "fp32")
            self.assertEqual(response["data"]["status"], "missing")
            bridge._drain_features()
            self.assertTrue(updates)
            voices = [v for v in updates[-1]["state"]["voices"] if v["backend"] == "kokoro"]
            self.assertEqual(len(voices), 8)
            self.assertFalse(any(v["available"] for v in voices))
            for status in ("playing", "paused"):
                with patch.object(bridge._playback, "snapshot", return_value={"status": status}):
                    response = json.loads(bridge.readerFeatureAction(json.dumps({"action": "modelVariant", "variant": "int8"})))
                self.assertEqual(response["error"]["code"], "MODEL_BUSY")
                self.assertEqual(bridge._kokoro.variant, "fp32")
        finally:
            bridge.shutdown()


class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "stats.sqlite3"
        self.mono = 0.
        self.wall = dt.datetime(2026, 10, 10, 23, 59, 58).timestamp()
        self.service = ActivityService(self.path, lambda: self.mono, lambda: self.wall)

    def tearDown(self):
        self.service.close(); self.temp.cleanup()

    def advance(self, seconds, **flags):
        self.mono += seconds; self.wall += seconds
        self.service.tick(**flags)

    def test_overlap_cross_day_and_committed_restore(self):
        self.service.report("main", "s", True, 1)
        self.service.tick("main", True, "book", "b")
        self.advance(4, foreground_surface="main", speaking=True, book_id="b")
        state = self.service.state()
        self.assertEqual(state["total"]["totalMs"], 4000)
        self.assertEqual(state["total"]["readingMs"], 4000)
        self.assertEqual(state["total"]["listeningMs"], 4000)
        self.assertEqual([x["totalMs"] for x in state["days"]], [2000, 2000])
        self.service.flush()
        restored = ActivityService(self.path, lambda: self.mono, lambda: self.wall)
        self.assertEqual(restored.state()["total"], state["total"])
        restored.close()

    def test_short_audio_uses_event_boundaries_between_timer_ticks(self):
        self.service.report("main", "s", True, 1)
        self.service.tick("main", None)
        self.mono += .05; self.wall += .05
        self.service.record_audio(True, self.mono)
        self.mono += .10; self.wall += .10
        self.service.record_audio(False, self.mono)
        self.advance(.1, foreground_surface="main", speaking=None)
        state = self.service.state()["total"]
        self.assertEqual(state["listeningMs"], 100)
        self.assertEqual(state["overlapMs"], 100)
        self.assertEqual(state["readingMs"], 250)

    def test_background_preview_pause_idle_and_suspend(self):
        self.service.report("floating", "s", True, 1)
        self.service.tick("floating", True, "book", "b")
        self.advance(2, speaking=True, book_id="b")
        self.advance(2, speaking=False, book_id="b")
        self.advance(2, speaking=True, purpose="preview", book_id="b")
        self.advance(2)
        self.assertEqual(self.service.state()["total"]["readingMs"], 2000)
        self.assertEqual(self.service.state()["total"]["listeningMs"], 4000)
        before = self.service.state()["total"]
        self.advance(3600)
        self.assertEqual(self.service.state()["total"], before)
        self.service.report("main", "s", True, 1)
        self.service.tick("main")
        for _ in range(301): self.advance(1, foreground_surface="main")
        self.assertEqual(self.service.state()["total"]["readingMs"], 302000)


if __name__ == "__main__":
    unittest.main()
