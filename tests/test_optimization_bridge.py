"""Qt feature routes in an isolated QCore host: no widgets or audio devices."""
import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QObject

from novelreader.book_loader import BookContent, Chapter
from novelreader.feature_store import FeatureError, read_library, save_library
from novelreader.library_lock import library_write_lock
from novelreader.library_service import LibraryQueryService
from novelreader.playback_service import PlaybackService
from novelreader.qt_bridge import DesktopBridge
from novelreader.reader_service import ReaderService
from novelreader.storage import Storage
from novelreader.tts_engine import SpeechController


class _Window(QObject):
    def isMaximized(self): return False
    def isFullScreen(self): return False


class OptimizationBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "data"
        self.root.mkdir()
        self.path = self.root / "library.json"
        environment = patch.dict(os.environ, {"DOUBAO_NOVEL_DATA": str(self.root)})
        environment.start(); self.addCleanup(environment.stop)
        self.local_voice = r"HKEY_LOCAL_MACHINE\SOFTWARE\QYReaderTestVoice"
        self.patches = [
            patch.object(SpeechController, "_ensure_thread"),
            patch.object(SpeechController, "prepare"),
            patch.object(SpeechController, "set_volume"),
            patch.object(SpeechController, "list_voices", return_value=[self.local_voice]),
            patch("novelreader.tts_engine._synth_audio_governed", return_value=b"mock mp3 audio"),
            patch("novelreader.tts_engine._set_process_volume"),
        ]
        self.mocks = [item.start() for item in self.patches]
        for item in self.patches: self.addCleanup(item.stop)
        data = {"books": {}, "settings": {"tts_voice": "", "tts_rate": 200}, "futureRoot": 7}
        for bid, title in (("a", "甲书"), ("b", "乙书")):
            source = self.base / (bid + ".txt")
            source.write_text("第一章\n第一句。第二句。\n第二章\n第三句。", encoding="utf-8")
            data["books"][bid] = {"id": bid, "title": title, "path": str(source), "progress": {"chapter_idx": 0, "char_offset": 4, "percent": 20}, "bookmarks": [{"id": "saved-note", "chapter_idx": 0, "offset": 0, "text": "第一句", "note": "原备注"}], "future": {"preserve": True}}
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        for bid, title in (("a", "甲书"), ("b", "乙书")):
            Storage(str(self.path)).write_cache(bid, BookContent(title, "", "txt", [Chapter("第一章", "第一句。第二句。"), Chapter("第二章", "第三句。")]))
        self.bridges = []
        self.addCleanup(self.close_bridges)
        self.bridge = self.make_bridge()
        self.opened = []
        self.bridge.readerOpened.connect(lambda raw: self.opened.append(json.loads(raw)))
        self.open_book("a")

    def make_bridge(self):
        window = _Window()
        speech = SpeechController()
        playback = PlaybackService(speech)
        bridge = DesktopBridge(window, library=LibraryQueryService(self.path), reader=ReaderService(self.path, deferred_progress=True), playback=playback)
        bridge._test_window = window  # Keep QObject parent alive for the whole test.
        self.bridges.append(bridge)
        bridge._voice_thread.join(1)
        bridge._drain_reader_events()
        return bridge

    def close_bridges(self):
        for bridge in reversed(self.bridges):
            bridge.shutdown()

    def action(self, name, **payload):
        return json.loads(self.bridge.readerFeatureAction(json.dumps({"action": name, **payload})))

    def accepted(self, name, **payload):
        result = self.action(name, **payload)
        self.assertTrue(result["ok"], result)
        return result["data"]

    def wait_job(self, job):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            result = self.accepted("backupJob", jobId=job["jobId"])
            if result["status"] != "running": return result
            time.sleep(.01)
        self.fail("Background backup job did not finish within 4 seconds")

    def open_book(self, bid):
        response = json.loads(self.bridge.openReaderBook(bid))
        self.assertTrue(response["ok"], response)
        self.bridge._reader_thread.join(2)
        self.bridge._drain_reader_events()
        self.assertFalse(self.bridge._reader_open_request_id)
        if self.opened:
            self.assertTrue(self.opened[-1]["ok"], self.opened[-1])
            return self.opened[-1]["data"]

    def create_archive(self):
        archive = self.base / "snapshot.zip"
        with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(str(archive), "")):
            created = self.wait_job(self.accepted("backupCreate"))
        self.assertEqual(created["status"], "completed", created)
        return archive

    def inspect_archive(self, archive):
        with patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(archive), "")):
            inspected = self.wait_job(self.accepted("backupInspect"))
        self.assertEqual(inspected["status"], "completed", inspected)
        return inspected["result"]

    def test_voice_catalog_validates_all_engines_and_preview_replaces_without_saving(self):
        catalog = self.accepted("voiceCenter")
        self.assertEqual({voice["backend"] for voice in catalog["voices"]}, {"sapi", "edge", "kokoro"})
        edge = next(voice["id"] for voice in catalog["voices"] if voice["backend"] == "edge")
        kokoro = next(voice["id"] for voice in catalog["voices"] if voice["backend"] == "kokoro")
        missing = self.action("previewVoice", voiceId=kokoro)
        self.assertEqual(missing["error"]["code"], "VOICE_NOT_READY")
        self.assertEqual(self.action("previewVoice", voiceId="unknown-voice")["error"]["code"], "VOICE_NOT_FOUND")
        self.bridge._kokoro.state["status"] = "ready"
        playback = self.bridge._playback
        controller = playback.speech_controller
        position = playback.snapshot()["position"]
        playback.control("play")
        generations = []
        for voice in (self.local_voice, edge, kokoro, edge):
            self.assertTrue(self.accepted("previewVoice", voiceId=voice)["accepted"])
            self.assertIs(self.bridge._playback.speech_controller, controller)
            self.assertEqual(playback.snapshot()["purpose"], "preview")
            self.assertEqual(controller.voice_id(), voice)
            generations.append(controller.generation())
        self.assertEqual(sorted(set(generations)), generations)
        self.accepted("cancelPreview")
        self.assertEqual(playback.snapshot()["purpose"], "book")
        self.assertEqual(playback.snapshot()["position"], position)
        self.assertEqual(playback.snapshot()["status"], "paused")
        self.assertEqual(controller.voice_id(), "")
        self.assertEqual(read_library(self.path)["settings"]["tts_voice"], "")

    def test_favorites_survive_restart_and_missing_system_voice_remains_visible(self):
        self.accepted("voiceFavorite", voiceId=self.local_voice, favorite=True)
        self.accepted("voiceFavorite", voiceId=self.local_voice, favorite=True)
        self.bridge.shutdown()
        self.mocks[3].return_value = []
        self.bridge = self.make_bridge()
        catalog = self.accepted("voiceCenter")
        self.assertEqual(catalog["favorites"], [self.local_voice])
        missing = next(voice for voice in catalog["voices"] if voice["id"] == self.local_voice)
        self.assertFalse(missing["available"])
        self.assertTrue(missing["unavailableReason"])
        self.assertEqual(self.action("previewVoice", voiceId=self.local_voice)["error"]["code"], "VOICE_NOT_FOUND")
        self.accepted("voiceFavorite", voiceId=self.local_voice, favorite=False)
        self.assertEqual(self.accepted("voiceCenter")["favorites"], [])

    def test_cache_routes_prepare_other_book_without_changing_playback_identity(self):
        playback = self.bridge._playback
        controller = playback.speech_controller
        playback.control("play")
        before = playback.snapshot()
        identity = playback.session_identity()
        self.assertEqual(self.accepted("cacheState")["jobs"], [])
        created = self.accepted("cacheCreate", bookId="b", chapterIndices=[0], backend="edge", voiceId="zh-CN-XiaoxiaoNeural", rate=200)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            job = next(job for job in self.accepted("cacheState")["jobs"] if job["jobId"] == created["jobId"])
            if job["state"] not in {"queued", "preparing", "running"}: break
            time.sleep(.01)
        self.assertEqual(job["state"], "completed", job)
        self.assertEqual(job["done"], 2)
        self.assertEqual(playback.session_identity(), identity)
        self.assertEqual(playback.snapshot()["position"], before["position"])
        self.assertEqual(playback.snapshot()["requestedVoiceId"], before["requestedVoiceId"])
        self.assertEqual(controller._book_id, "a")
        self.assertIs(self.bridge._playback.speech_controller, controller)
        rejected = self.action("cacheControl", jobId=created["jobId"], command="clean")
        self.assertEqual(rejected["error"]["code"], "CACHE_CONFIRM_REQUIRED")
        paused = self.accepted("cacheControl", jobId=created["jobId"], command="pause")
        self.assertEqual(paused["state"], "paused")
        cancelled = self.accepted("cacheControl", jobId=created["jobId"], command="cancel")
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(playback.session_identity(), identity)

    def test_backup_restore_maintenance_blocks_writers_and_reloads_snapshot(self):
        inventory = self.wait_job(self.accepted("backupInventory"))
        self.assertEqual(inventory["status"], "completed", inventory)
        self.assertEqual(inventory["result"]["bookCount"], 2)
        archive = self.create_archive()
        preview = self.inspect_archive(archive)
        self.assertEqual(preview["noteCount"], 2)
        with library_write_lock(self.path):
            data = read_library(self.path)
            data["books"]["a"]["bookmarks"][0]["note"] = "后来改过"
            data["books"]["a"]["progress"]["char_offset"] = 7
            save_library(self.path, data)
        controller = self.bridge._playback.speech_controller
        old_reader = self.bridge._reader
        original_restore = self.bridge._backup.restore
        entered, release = threading.Event(), threading.Event()
        def blocked_restore(**kwargs):
            entered.set()
            if not release.wait(2): raise RuntimeError("fixture timeout")
            return original_restore(**kwargs)
        with patch.object(self.bridge._backup, "restore", side_effect=blocked_restore):
            job = self.accepted("backupRestore", previewId=preview["previewId"])
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(self.bridge._maintenance)
                self.assertEqual(self.action("voiceFavorite", voiceId="", favorite=True)["error"]["code"], "RESTORE_IN_PROGRESS")
                self.assertEqual(self.action("organizationUpdate", request={"action": "batch", "bookIds": ["a"], "patch": {"readingStatus": "read"}})["error"]["code"], "RESTORE_IN_PROGRESS")
                for raw in (self.bridge.controlReaderPlayback('{}'), self.bridge.updateReaderPosition('{}'), self.bridge.updateReaderSettings('{}'), self.bridge.openReaderBook("a"), self.bridge.getInitialState()):
                    self.assertEqual(json.loads(raw)["error"]["code"], "RESTORE_IN_PROGRESS")
            finally:
                release.set()
            result = self.wait_job(job)
        self.assertEqual(result["status"], "completed", result)
        self.assertFalse(self.bridge._maintenance)
        self.assertIsNot(self.bridge._reader, old_reader)
        self.assertIs(self.bridge._playback.speech_controller, controller)
        self.assertEqual(self.bridge._playback.session_identity()["sessionId"], "")
        opened = self.open_book("a")
        self.assertEqual(opened["position"]["charOffset"], 4)
        notes = self.bridge._reader.list_bookmarks(opened["sessionId"])
        self.assertEqual(notes["items"][0]["note"], "原备注")
        self.assertEqual(read_library(self.path)["futureRoot"], 7)

    def test_restore_failure_releases_maintenance_and_original_data_stays_readable(self):
        archive = self.create_archive()
        preview = self.inspect_archive(archive)
        controller = self.bridge._playback.speech_controller
        changes = []
        self.bridge.featuresChanged.connect(lambda raw: changes.append(json.loads(raw)))
        with patch.object(self.bridge._backup, "restore", side_effect=FeatureError("TEST_RESTORE_FAILED", "模拟恢复失败")):
            failed = self.wait_job(self.accepted("backupRestore", previewId=preview["previewId"]))
        self.assertEqual(failed["status"], "error")
        self.assertEqual(failed["error"]["code"], "TEST_RESTORE_FAILED")
        self.assertFalse(self.bridge._maintenance)
        self.assertIs(self.bridge._playback.speech_controller, controller)
        restored = [event for event in changes if event["kind"] == "restore"]
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]["data"]["status"], "error")
        self.assertEqual(self.bridge._playback.session_identity()["sessionId"], "")
        self.assertEqual(self.open_book("a")["book"]["id"], "a")
        self.assertTrue(self.accepted("organizationState"))

    def test_synchronous_restore_start_failure_notifies_if_reader_session_was_invalidated(self):
        archive = self.create_archive()
        preview = self.inspect_archive(archive)
        before = self.bridge._playback.session_identity()
        changes = []
        self.bridge.featuresChanged.connect(lambda raw: changes.append(json.loads(raw)))
        with patch.object(self.bridge._backup, "start", side_effect=FeatureError("BACKUP_BUSY", "模拟启动任务失败")):
            result = self.action("backupRestore", previewId=preview["previewId"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "BACKUP_BUSY")
        self.assertFalse(self.bridge._maintenance)
        if self.bridge._playback.session_identity() != before:
            restored = [event for event in changes if event["kind"] == "restore"]
            self.assertEqual(len(restored), 1, "Frontend must learn that its old reader session was invalidated")
            self.assertEqual(restored[0]["data"]["status"], "error")
        self.assertEqual(self.open_book("a")["book"]["id"], "a")

    def test_preview_async_error_is_retained_after_book_context_restore(self):
        playback = self.bridge._playback
        speech = playback.speech_controller
        before = playback.snapshot()["position"]
        playback.control("play")
        self.accepted("previewVoice", voiceId="zh-CN-XiaoxiaoNeural")
        speech._post({"type": "error", "code": "MOCK_PREVIEW_FAILED", "message": "模拟试听失败", "retryable": True, "fallback_backend": None}, speech.generation())
        self.bridge._drain_reader_events()
        state = self.accepted("voiceCenter")["playback"]
        self.assertEqual(state["preview"]["status"], "error")
        self.assertEqual(state["preview"]["error"]["code"], "MOCK_PREVIEW_FAILED")
        self.assertEqual(state["purpose"], "book")
        self.assertEqual(state["position"], before)
        self.assertEqual(state["status"], "paused")
        self.assertEqual(speech.voice_id(), "")
        self.accepted("previewVoice", voiceId=self.local_voice)
        self.assertIsNone(playback.snapshot()["preview"]["error"])
        speech._post({"type": "finished"}, speech.generation())
        self.bridge._drain_reader_events()
        state = playback.snapshot()
        self.assertEqual(state["preview"]["status"], "completed")
        self.assertIsNone(state["preview"]["error"])
        self.assertEqual(state["purpose"], "book")
        self.assertEqual(state["position"], before)
        self.accepted("previewVoice", voiceId=self.local_voice)
        self.accepted("cancelPreview")
        self.assertEqual(playback.snapshot()["preview"]["status"], "cancelled")
        self.assertEqual(playback.snapshot()["position"], before)
        self.assertEqual(playback.snapshot()["status"], "paused")

    def test_maintenance_ignores_native_floating_geometry_writes(self):
        before = self.path.read_bytes()
        self.bridge._maintenance = True
        try:
            with patch.object(self.bridge._floating, "update_geometry", wraps=self.bridge._floating.update_geometry) as update:
                self.bridge.floatingGeometryChanged("448x295+50+70")
                update.assert_not_called()
            self.assertEqual(self.path.read_bytes(), before)
        finally:
            self.bridge._maintenance = False

    def test_shutdown_during_maintenance_skips_old_reader_progress_flush(self):
        before = self.path.read_bytes()
        self.bridge._maintenance = True
        with patch.object(self.bridge, "_flush_reader_progress") as flush:
            self.assertTrue(self.bridge.shutdown())
            flush.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(self.bridge._shutdown)

    def test_prepare_shutdown_cancels_running_backup_and_waits_for_completion(self):
        service = self.bridge._backup_service()
        entered, release = threading.Event(), threading.Event()
        original_inventory = service.inventory
        notices = []
        self.bridge.bridgeError.connect(lambda raw: notices.append(json.loads(raw)))
        def blocked_inventory(**kwargs):
            entered.set()
            if not release.wait(2): raise RuntimeError("fixture timeout")
            return original_inventory(**kwargs)
        with patch.object(service, "inventory", side_effect=blocked_inventory):
            job = self.accepted("backupInventory")
            try:
                self.assertTrue(entered.wait(1))
                started = time.monotonic()
                self.assertFalse(self.bridge.prepare_shutdown())
                self.assertLess(time.monotonic() - started, .3)
                self.assertFalse(self.bridge.prepare_shutdown())
                self.assertFalse(self.bridge._shutdown)
                self.assertEqual([notice["code"] for notice in notices], ["EXIT_WAITING_BACKUP"])
            finally:
                release.set()
            result = self.wait_job(job)
        self.assertEqual(result["status"], "cancelled", result)
        self.assertTrue(self.bridge.prepare_shutdown())
        self.assertTrue(self.bridge.shutdown())

    def test_pending_kokoro_model_load_rejects_restore_without_rewriting_model_metadata(self):
        archive = self.create_archive()
        preview = self.inspect_archive(archive)
        registry = self.root / "kokoro-model.json"
        registry.write_bytes(b"model metadata must stay unchanged")
        before = registry.read_bytes()
        pending = Future()
        kokoro = self.bridge._kokoro
        kokoro.load_future = pending
        reader = self.bridge._reader
        try:
            result = self.action("backupRestore", previewId=preview["previewId"])
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "RESTORE_BUSY")
            self.assertEqual(registry.read_bytes(), before)
            self.assertIs(self.bridge._kokoro, kokoro)
            self.assertIs(self.bridge._reader, reader)
            self.assertFalse(self.bridge._maintenance)
            self.assertEqual(self.bridge._restore_job, "")
        finally:
            pending.set_result(None)
            kokoro.load_future = None

    def test_native_close_defers_before_destroying_any_window_resources(self):
        # Call only the early branch on a plain object, never construct a QWidget.
        from novelreader.qt_host import DesktopWindow
        window = SimpleNamespace(bridge=SimpleNamespace(prepare_shutdown=Mock(return_value=False)), close=Mock(),
                                 _cancel_window_interaction=Mock(side_effect=AssertionError("window teardown started before rollback finished")))
        event = Mock()
        with patch("novelreader.qt_host.QTimer.singleShot") as schedule:
            DesktopWindow.closeEvent(window, event)
        event.ignore.assert_called_once()
        window._cancel_window_interaction.assert_not_called()
        schedule.assert_called_once_with(250, window.close)

    def test_retired_offline_worker_blocks_restore_until_it_exits(self):
        preview = self.inspect_archive(self.create_archive())
        reader = self.bridge._reader
        old = SimpleNamespace(thread=SimpleNamespace(is_alive=lambda: True))
        self.bridge._retired_offline = [old]
        try:
            response = self.action("backupRestore", previewId=preview["previewId"])
            self.assertEqual(response["error"]["code"], "RESTORE_BUSY")
            self.assertIs(self.bridge._reader, reader)
            self.assertFalse(self.bridge._maintenance)
        finally:
            self.bridge._retired_offline = []

    def test_backup_cancel_and_cancelled_pickers_leave_data_usable(self):
        with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=("", "")):
            self.assertTrue(self.accepted("backupCreate")["cancelled"])
        with patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=("", "")):
            self.assertTrue(self.accepted("backupInspect")["cancelled"])
        service = self.bridge._backup_service()
        entered, release = threading.Event(), threading.Event()
        original_inventory = service.inventory
        def blocked_inventory(**kwargs):
            entered.set()
            if not release.wait(2): raise RuntimeError("fixture timeout")
            return original_inventory(**kwargs)
        with patch.object(service, "inventory", side_effect=blocked_inventory):
            job = self.accepted("backupInventory")
            try:
                self.assertTrue(entered.wait(1))
                self.accepted("backupCancel", jobId=job["jobId"])
            finally:
                release.set()
            cancelled = self.wait_job(job)
        self.assertEqual(cancelled["status"], "cancelled", cancelled)
        self.assertEqual(cancelled["error"]["code"], "BACKUP_CANCELLED")
        self.assertEqual(self.action("backupRestore", previewId="expired")["error"]["code"], "BACKUP_PREVIEW_EXPIRED")
        self.assertEqual(self.bridge._playback.session_identity()["bookId"], "a")


if __name__ == "__main__": unittest.main()
