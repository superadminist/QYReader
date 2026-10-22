"""Sleep/preview regression checks with no synthesizer, sound device or window."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from novelreader.book_loader import BookContent, Chapter, parse_book
from novelreader.playback_service import PlaybackService
from novelreader.tts_engine import SpeechController


class SleepTimerReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        environment = patch.dict(os.environ, {"DOUBAO_NOVEL_DATA": str(self.root)})
        environment.start(); self.addCleanup(environment.stop)
        self.now = 1000
        self.speech = SpeechController()
        for method in ("_ensure_thread", "prepare"):
            patched = patch.object(self.speech, method)
            patched.start(); self.addCleanup(patched.stop)
        self.service = PlaybackService(self.speech, clock=lambda: self.now)
        self.addCleanup(self.service.shutdown)
        self.book = BookContent("原书", "", "txt", [Chapter("第一章", "第一句。第二句。"), Chapter("第二章", "第三句。")])
        self.service.bind_session("s", "b", self.book, 0, 4)

    def test_cancel_and_invalid_timer_do_not_interrupt_preview(self):
        self.service.control("play")
        self.service.set_sleep_timer("minutes", 1)
        self.service.preview("试听句。", "zh-CN-XiaoxiaoNeural")
        preview_generation = self.speech.generation()
        self.service.set_sleep_timer("off")
        self.assertEqual(self.service.snapshot()["purpose"], "preview")
        self.assertEqual(self.service.snapshot()["status"], "playing")
        self.assertEqual(self.speech.generation(), preview_generation)
        with self.assertRaises(ValueError): self.service.set_sleep_timer("minutes", 0)
        self.assertEqual(self.service.snapshot()["purpose"], "preview")
        self.assertEqual(self.speech.generation(), preview_generation)

    def test_chapter_timer_set_during_preview_binds_original_book(self):
        self.service.control("play")
        self.service.preview("试听句。", "zh-CN-XiaoxiaoNeural")
        state = self.service.set_sleep_timer("chapter")
        self.assertEqual(state["bookId"], "b")
        self.assertEqual(state["chapterIndex"], 0)
        self.assertEqual(self.service._sleep.chapter_version(self.book, 0), state["version"])
        self.assertEqual(self.service.snapshot()["purpose"], "preview")
        self.service.cancel_preview()
        self.assertEqual(self.service.snapshot()["sleepTimer"]["mode"], "chapter")
        self.assertEqual(self.service.snapshot()["position"]["charOffset"], 4)

    def test_deadline_during_preview_restores_book_and_ignores_late_events(self):
        original_voice = self.speech.voice_id()
        self.service.control("play")
        self.service.set_sleep_timer("minutes", 1)
        self.service.preview("试听句。", "zh-CN-XiaoxiaoNeural")
        preview_generation = self.speech.generation()
        self.now += 61
        events = self.service.drain_events()
        state = self.service.snapshot()
        self.assertEqual(state["purpose"], "book")
        self.assertEqual(state["status"], "idle")
        self.assertEqual(state["position"]["charOffset"], 4)
        self.assertEqual(self.speech.voice_id(), original_voice)
        stopped = [event for event in events if event["reason"] == "sleepStopped"]
        self.assertEqual(len(stopped), 1)
        self.assertEqual(stopped[0]["playback"]["purpose"], "book")
        self.speech._post({"type": "finished"}, preview_generation)
        self.speech._post({"type": "sentence_start", "chapter_idx": 1, "char_offset": 0, "char_end": 4, "text": "迟到试听。"}, preview_generation)
        self.service.drain_events()
        self.assertEqual(self.service.snapshot()["position"], state["position"])
        self.assertEqual(self.service.snapshot()["status"], "idle")

    def test_old_chapter_stop_does_not_cancel_replacement_minutes(self):
        old = self.service.set_sleep_timer("chapter")
        generation = self.speech.generation()
        new = self.service.set_sleep_timer("minutes", 30)
        self.speech._post({"type": "sleep_stopped", "timerVersion": old["version"], "chapter_idx": 0, "char_offset": len(self.book.chapters[0].content)}, generation)
        self.service.drain_events()
        timer = self.service.snapshot()["sleepTimer"]
        self.assertEqual(timer["mode"], "minutes")
        self.assertEqual(timer["version"], new["version"])
        self.assertEqual(timer["endReason"], "")

    def test_markdown_original_offsets_and_empty_chapter_stop_before_next(self):
        source = self.root / "fixture.md"
        source.write_text("# 标题\n\n## 第一章\n第一句。。。 😀 [第二句](https://example.test)。\n\n## 第二章\n不能读到的下一章。", encoding="utf-8")
        parsed = parse_book(str(source))
        self.assertGreaterEqual(len(parsed.chapters), 2)
        empty = BookContent("空章", "", "md", [Chapter("空", " \n😀\t"), Chapter("后章", "不能读到。")])
        for book in (parsed, empty):
            self.service.bind_session("markdown", "md", book, 0, 0)
            self.service.set_sleep_timer("chapter")
            self.speech._book, self.speech._state, self.speech._sentence_gap = book, "playing", 0
            self.service._status = "playing"
            spoken = []
            def speak(text, generation, start_event=None):
                spoken.append(text)
                self.speech._post(dict(start_event), generation)
                return True
            with patch.object(self.speech, "_speak_sapi", side_effect=speak):
                self.speech._run_session(book, 0, 0, self.speech.generation())
            self.service.drain_events()
            self.assertEqual(self.service.snapshot()["position"]["chapterIndex"], 0)
            self.assertEqual(self.service.snapshot()["position"]["charOffset"], len(book.chapters[0].content))
            self.assertEqual(self.service.snapshot()["sleepTimer"]["endReason"], "chapterEnd")
            self.assertFalse(any("不能读到" in text for text in spoken))

    def test_play_after_preview_without_a_bound_book_does_not_start_none_content(self):
        from novelreader.playback_service import PlaybackService
        from novelreader.tts_engine import SpeechController
        speech = SpeechController()
        playback = PlaybackService(speech)
        try:
            with patch.object(speech, "_ensure_thread"):
                playback.preview("只有试听。", "")
                with self.assertRaises(RuntimeError): playback.control("play")
                self.assertEqual(playback.snapshot()["status"], "idle")
                self.assertEqual(playback.snapshot()["purpose"], "book")
                self.assertIsNone(speech._book)
        finally:
            playback.shutdown()

    def test_edge_ready_audio_waits_while_paused_and_expiry_never_plays(self):
        self.service.set_sleep_timer("minutes", 1)
        self.speech._state, self.speech._book = "paused", self.book
        opened, played = threading.Event(), threading.Event()
        patches = [
            patch("novelreader.tts_engine._mci_open", side_effect=lambda _path: opened.set()),
            patch("novelreader.tts_engine._mci_set_volume"), patch("novelreader.tts_engine._set_process_volume"),
            patch("novelreader.tts_engine._mci_play", side_effect=lambda: played.set()),
            patch("novelreader.tts_engine._mci_playing", return_value=False),
            patch("novelreader.tts_engine._mci_stop"), patch("novelreader.tts_engine._mci_close"),
        ]
        for patched in patches: patched.start()
        thread = threading.Thread(target=self.speech._speak_edge_play, args=(b"mock audio bytes", self.speech.generation()))
        try:
            thread.start()
            self.assertTrue(opened.wait(1))
            self.assertFalse(played.wait(.05), "Paused Edge audio must not call MCI play")
            self.now += 61
            self.service.tick_sleep_timer()
            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertFalse(played.is_set())
        finally:
            self.speech.stop()
            thread.join(1)
            for patched in reversed(patches): patched.stop()

    def test_qt_expiry_flushes_latest_original_book_progress(self):
        from PySide6.QtCore import QCoreApplication, QObject
        from novelreader.library_service import LibraryQueryService
        from novelreader.qt_bridge import DesktopBridge
        from novelreader.reader_service import ReaderService
        from novelreader.storage import Storage
        from novelreader.feature_store import read_library
        app = QCoreApplication.instance() or QCoreApplication([])
        path = self.root / "library.json"
        path.write_text(json.dumps({"books": {"b": {"title": "原书", "progress": {"chapter_idx": 0, "char_offset": 0, "percent": 0}}}, "settings": {}}), encoding="utf-8")
        Storage(str(path)).write_cache("b", self.book)
        reader = ReaderService(path, deferred_progress=True)
        opened = reader.open_book("b")
        self.service.bind_session(opened["sessionId"], "b", reader.get_session_content(opened["sessionId"]))
        window = QObject()
        with patch("novelreader.qt_bridge.SpeechController.list_voices", return_value=[]):
            bridge = DesktopBridge(window, library=LibraryQueryService(path), reader=reader, playback=self.service)
        try:
            self.service.control("play")
            self.service.set_sleep_timer("minutes", 1)
            self.speech._post({"type": "sentence_done", "chapter_idx": 0, "char_offset": 4}, self.speech.generation())
            self.now += 61
            bridge._drain_reader_events()
            reader.flush_progress(wait=True)
            stored = read_library(path)["books"]["b"]["progress"]
            self.assertEqual(stored["chapter_idx"], 0)
            self.assertEqual(stored["char_offset"], 4)
            self.assertEqual(self.service.snapshot()["status"], "idle")
            self.assertEqual(self.service.snapshot()["sleepTimer"]["endReason"], "expired")
        finally:
            bridge.shutdown()


if __name__ == "__main__": unittest.main()
