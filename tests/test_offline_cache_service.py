"""Isolated job/cache proofs; all synthesis is fake and no player is created."""
import concurrent.futures
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from novelreader.book_loader import BookContent, Chapter
from novelreader.feature_store import FeatureError
from novelreader.kokoro_service import KokoroService
from novelreader.offline_cache_service import OfflineCacheService, MIN_FREE_BYTES
from novelreader.tts_engine import EdgeSynthesisError, SpeechController

EDGE = "zh-CN-XiaoxiaoNeural"
KOKORO = "kokoro:v1.0:zf_xiaobei"


def book(first="第一句。第二句。", second="第三句。"):
    return BookContent("测试书", "", "txt", [Chapter("第一章", first), Chapter("第二章", second)])


class OfflineCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.calls = []
        self.current_book = book()
        self.services = []
        self.kokoro = None

    def tearDown(self):
        for service in self.services:
            service.close()
            service.thread.join(2)
        if self.kokoro:
            self.kokoro.close()
            self.kokoro.executor.thread.join(2)
        self.temporary.cleanup()

    def service(self, **kwargs):
        def synth(text, voice, rate):
            self.calls.append((text, voice, rate))
            return ("fake-mp3:" + text).encode()
        service = OfflineCacheService(self.root, loader=kwargs.pop("loader", lambda bid: self.current_book), edge_synth=kwargs.pop("edge_synth", synth), **kwargs)
        self.services.append(service)
        return service

    def settled(self, service, identifier, expected=None):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = next(job for job in service.state()["jobs"] if job["jobId"] == identifier)
            if job["state"] not in {"queued", "preparing", "running"}:
                if expected:
                    self.assertEqual(job["state"], expected, job)
                return job
            time.sleep(.01)
        self.fail("job did not settle")

    def create(self, service, chapters=None, **kwargs):
        return service.create("book-b", chapters or [0], kwargs.get("backend", "edge"), kwargs.get("voice", EDGE), kwargs.get("rate", 200))

    def test_range_cache_replay_verify_and_repair_are_real_file_counts(self):
        service = self.service()
        identifier = self.create(service)["jobId"]
        result = self.settled(service, identifier, "completed")
        self.assertEqual((result["total"], result["done"]), (2, 2))
        self.assertEqual(len(self.calls), 2)
        speech = SpeechController()
        speech.set_tts_cache_dir(str(self.root / "tts_cache"))
        speech.set_book_id("book-b")
        speech.set_voice(EDGE)
        self.assertIsNotNone(speech._cached_audio(0, 0, text="第一句。"))
        self.assertIsNone(speech._cached_audio(0, 0, text="变更后的句子。"))
        self.assertIsNone(speech._cached_audio(1, 0, text="第三句。"))
        # A complete replay cannot enter a synthesis function.
        service.edge_synth = lambda *args: self.fail("warm replay synthesized")
        service.control(identifier, "resume")
        self.assertEqual(self.settled(service, identifier, "completed")["done"], 2)
        audio = next((self.root / "tts_cache").rglob("*.mp3"))
        audio.unlink()
        service.control(identifier, "verify")
        self.assertEqual(self.settled(service, identifier, "paused")["done"], 1)
        service.edge_synth = lambda text, *_: ("repaired:" + text).encode()
        service.control(identifier, "repair")
        self.assertTrue(self.settled(service, identifier, "completed")["verified"])

    def test_idempotent_pause_cancel_restart_and_changed_content(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(text, *_):
            entered.set(); release.wait(2)
            return text.encode()
        service = self.service(edge_synth=blocked)
        try:
            identifier = self.create(service)["jobId"]
            self.assertTrue(entered.wait(1))
            self.assertEqual(self.create(service)["jobId"], identifier)
            service.control(identifier, "pause")
            release.set()
            time.sleep(.03)
            self.assertEqual(service.state()["jobs"][0]["state"], "paused")
            service.edge_synth = lambda text, *_: text.encode()
            service.control(identifier, "resume")
            old = self.settled(service, identifier, "completed")["fingerprint"]
            service.close(); service.thread.join(2)
            new = self.service()
            self.assertFalse(new.state()["jobs"][0]["verified"])
            self.current_book = book("已变更。")
            new.control(identifier, "resume")
            result = self.settled(new, identifier, "completed")
            self.assertNotEqual(result["fingerprint"], old)
            self.assertEqual(result["total"], 1)
            new.control(identifier, "cancel")
            self.assertTrue(list((self.root / "tts_cache").rglob("*.mp3")))
        finally:
            release.set()

    def test_failures_and_no_space_do_not_inflate_completed(self):
        service = self.service(edge_synth=lambda *_: (_ for _ in ()).throw(EdgeSynthesisError({"category": "rate_limit"})))
        identifier = self.create(service)["jobId"]
        job = self.settled(service, identifier, "paused")
        self.assertEqual(job["done"], 0)
        self.assertEqual(job["error"]["code"], "EDGE_BUSY")
        service.disk_free = lambda path: MIN_FREE_BYTES - 1
        service.control(identifier, "resume")
        self.assertEqual(self.settled(service, identifier, "paused")["error"]["code"], "CACHE_NO_SPACE")

    def test_clear_is_scoped_confirmed_and_protects_current_playback(self):
        service = self.service(protected=lambda job: True)
        identifier = self.create(service)["jobId"]
        self.settled(service, identifier, "completed")
        unrelated = self.root / "tts_cache" / "unrelated.mp3"
        unrelated.write_bytes(b"unchanged")
        with self.assertRaises(FeatureError): service.control(identifier, "clean")
        service.control(identifier, "clean", confirmed=True)
        self.assertEqual(self.settled(service, identifier, "error")["error"]["code"], "CACHE_IN_USE")
        service.protected = lambda job: False
        service.control(identifier, "clean", confirmed=True)
        self.settled(service, identifier, "cancelled")
        self.assertEqual(list((self.root / "tts_cache").rglob("*.mp3")), [unrelated])

    def test_scope_rate_and_legacy_content_are_separate(self):
        service = self.service()
        legacy = self.root / "tts_cache" / "book-b" / EDGE / "200" / "0000_00000000.mp3"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy-without-proof")
        identifier = self.create(service)["jobId"]
        self.assertTrue(self.settled(service, identifier, "completed")["verified"])
        self.assertNotEqual(legacy.read_bytes(), b"legacy-without-proof")
        second = self.create(service, [1], rate=220)["jobId"]
        result = self.settled(service, second, "completed")
        self.assertEqual(result["chapterIndices"], [1])
        self.assertEqual(result["done"], 1)
        self.assertTrue(list((self.root / "tts_cache" / "book-b" / EDGE / "220").glob("*.mp3")))

    def test_managed_paths_reject_escape_without_deleting_files(self):
        service = self.service()
        identifier = self.create(service)["jobId"]
        self.settled(service, identifier, "completed")
        source = self.root / "keep.mp3"; source.write_bytes(b"source")
        service.jobs[identifier]["tasks"][0]["path"] = "../keep.mp3"
        service.control(identifier, "clean", confirmed=True)
        self.assertEqual(self.settled(service, identifier, "error")["error"]["code"], "CACHE_PATH_INVALID")
        self.assertEqual(source.read_bytes(), b"source")

    def test_kokoro_shared_references_survive_restart_trim_and_one_job_cleanup(self):
        self.current_book = book("共享一句。", "共享一句。")
        self.kokoro = KokoroService(self.root)
        self.kokoro.state["status"] = "ready"
        generated = []
        def generate(key, text, sid, rate):
            generated.append(text)
            self.kokoro.cache.mkdir(parents=True, exist_ok=True)
            path = self.kokoro.cache / (key + ".wav")
            path.write_bytes(b"RIFF" + b"a" * 80)
            self.kokoro._trim_cache(path)
            return path
        with patch.object(self.kokoro, "_generate", side_effect=generate):
            service = self.service(kokoro=self.kokoro)
            first = self.create(service, [0], backend="kokoro", voice=KOKORO)["jobId"]
            self.settled(service, first, "completed")
            second = self.create(service, [1], backend="kokoro", voice=KOKORO)["jobId"]
            self.settled(service, second, "completed")
            self.assertEqual(generated, ["共享一句。"])
            path = self.kokoro.cache_path_for("共享一句。", KOKORO, 200)
            self.assertTrue(self.kokoro.is_retained(path))
            # Empty the recent-Future safety net: only persistent chapter refs remain.
            self.kokoro.futures.clear()
            other = self.kokoro.cache / "temporary.wav"; other.write_bytes(b"RIFF" + b"b" * 80)
            with patch("novelreader.kokoro_service.CACHE_BYTES", 1): self.kokoro._trim_cache(other)
            self.assertTrue(path.is_file())
            service.control(first, "clean", confirmed=True)
            self.settled(service, first, "cancelled")
            self.assertTrue(path.is_file())
            self.assertTrue(self.kokoro.is_retained(path))
            service.control(second, "clean", confirmed=True)
            self.settled(service, second, "cancelled")
            self.assertFalse(path.exists())

    def test_kokoro_model_change_cannot_publish_old_completion(self):
        self.kokoro = KokoroService(self.root)
        self.kokoro.state["status"] = "ready"
        pending = concurrent.futures.Future()
        with patch.object(self.kokoro, "request", return_value=pending):
            service = self.service(kokoro=self.kokoro)
            identifier = self.create(service, backend="kokoro", voice=KOKORO)["jobId"]
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and service.state()["jobs"][0]["state"] != "running": time.sleep(.01)
            self.kokoro.set_variant("fp32")
            result = self.settled(service, identifier, "paused")
            self.assertEqual(result["error"]["code"], "MODEL_CHANGED")
            self.assertEqual(result["done"], 0)

    def test_slow_book_preparation_is_background_and_closed_network_job_cannot_write(self):
        entered, release = threading.Event(), threading.Event()
        def loader(identifier):
            entered.set(); release.wait(2); return self.current_book
        service = self.service(loader=loader)
        started = time.monotonic()
        result = self.create(service)
        self.assertLess(time.monotonic() - started, .2)
        self.assertTrue(entered.wait(1))
        self.assertFalse(service.close())
        release.set(); service.thread.join(2)
        self.assertFalse(list((self.root / "tts_cache").rglob("*.mp3")))
        self.assertEqual(service.state()["jobs"][0]["state"], "paused")

    def test_write_failure_is_not_counted_and_corrupt_retention_is_fail_closed(self):
        service = self.service()
        with patch("novelreader.offline_cache_service._EdgeFiles.write_verified", side_effect=OSError("disk write")):
            result = self.create(service)
            settled = self.settled(service, result["jobId"], "error")
            self.assertEqual(settled["done"], 0)
        service.close(); service.thread.join(2)
        (self.root / "offline-audio-refs-v1.json").write_text('{"version":1,"refs":{"x":["../escape.wav"]}}', encoding="utf-8")
        self.kokoro = KokoroService(self.root)
        self.assertTrue(self.kokoro.is_retained(self.root / "any.wav"))
        with self.assertRaises(FeatureError): self.kokoro.retain_path(self.root / "tts_cache" / "a.wav", "x")

    def test_overlapping_edge_job_with_changed_text_invalidates_old_verified_task(self):
        service = self.service()
        first = self.create(service, [0])["jobId"]
        self.settled(service, first, "completed")
        self.current_book = book("新正文。")
        second = self.create(service, [0, 1])["jobId"]
        self.settled(service, second, "completed")
        old = next(job for job in service.state()["jobs"] if job["jobId"] == first)
        self.assertFalse(old["verified"])
        self.assertEqual(old["state"], "paused")
        self.assertLess(old["done"], old["total"])

    def test_cleanup_rechecks_when_play_starts_after_initial_guard(self):
        guard_calls = []
        def guard(job):
            guard_calls.append(job["jobId"])
            return len(guard_calls) > 1
        service = self.service(protected=guard)
        identifier = self.create(service)["jobId"]
        self.settled(service, identifier, "completed")
        files_before = list((self.root / "tts_cache").rglob("*.mp3"))
        service.control(identifier, "clean", confirmed=True)
        self.assertEqual(self.settled(service, identifier, "error")["error"]["code"], "CACHE_IN_USE")
        self.assertTrue(all(path.is_file() for path in files_before))
        self.assertGreaterEqual(len(guard_calls), 2)

    def test_cached_kokoro_replay_needs_no_model_or_native_loader_after_restart(self):
        self.kokoro = KokoroService(self.root)
        path = self.kokoro.cache_path_for("保留音频。", KOKORO, 200)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"RIFF" + b"a" * 80)
        self.kokoro.retain_path(path, "saved:0")
        self.kokoro.close(); self.kokoro.executor.thread.join(2)
        self.kokoro = KokoroService(self.root)
        self.assertEqual(self.kokoro.snapshot()["status"], "missing")
        with patch.object(self.kokoro, "_load_engine", side_effect=AssertionError("must not load")), patch.object(self.kokoro, "_generate", side_effect=AssertionError("must not synthesize")):
            future = self.kokoro.request("保留音频。", KOKORO, 200)
            self.assertTrue(future.done())
            self.assertEqual(future.result().read_bytes(), b"RIFF" + b"a" * 80)
            self.assertIsNone(self.kokoro.preload())
        self.assertTrue(self.kokoro.is_retained(path))

    def test_retained_kokoro_job_verifies_without_model_and_pauses_only_missing_generation(self):
        self.kokoro = KokoroService(self.root)
        self.kokoro.state["status"] = "ready"
        def generate(key, text, sid, rate):
            self.kokoro.cache.mkdir(parents=True, exist_ok=True)
            path = self.kokoro.cache / (key + ".wav")
            path.write_bytes(b"RIFF" + b"a" * 80)
            return path
        with patch.object(self.kokoro, "_generate", side_effect=generate):
            service = self.service(kokoro=self.kokoro)
            identifier = self.create(service, backend="kokoro", voice=KOKORO)["jobId"]
            self.settled(service, identifier, "completed")
            self.kokoro.state["status"] = "missing"
            with patch.object(self.kokoro, "request", side_effect=AssertionError("must not synthesize")):
                service.control(identifier, "verify")
                self.assertTrue(self.settled(service, identifier, "completed")["verified"])
                service.control(identifier, "resume")
                self.assertTrue(self.settled(service, identifier, "completed")["verified"])
            next(self.kokoro.cache.glob("*.wav")).unlink()
            service.control(identifier, "repair")
            self.assertEqual(self.settled(service, identifier, "paused")["error"]["code"], "MODEL_NOT_READY")

    def test_close_between_job_initialization_and_retention_prevents_late_reference_write(self):
        self.kokoro = KokoroService(self.root)
        self.kokoro.state["status"] = "ready"
        service = self.service(kokoro=self.kokoro)
        entered, release = threading.Event(), threading.Event()
        original = service._retain_job_paths
        def delayed(*args, **kwargs):
            entered.set(); release.wait(2)
            return original(*args, **kwargs)
        try:
            with patch.object(service, "_retain_job_paths", side_effect=delayed), patch.object(self.kokoro, "retain_paths") as retain:
                self.create(service, backend="kokoro", voice=KOKORO)
                self.assertTrue(entered.wait(1))
                self.assertFalse(service.close())
                closed_manifest = service.index.read_bytes()
                release.set(); service.thread.join(2)
                retain.assert_not_called()
                self.assertEqual(service.index.read_bytes(), closed_manifest)
                self.assertFalse((self.root / "offline-audio-refs-v1.json").exists())
                self.assertFalse(list((self.root / "tts_cache").rglob("*.wav")))
                with patch.object(service, "_persist_locked", side_effect=AssertionError("closed service wrote again")):
                    self.assertTrue(service.close())
        finally:
            release.set()

    def test_closed_cleanup_cannot_release_references_or_delete_audio(self):
        self.kokoro = KokoroService(self.root)
        service = self.service(kokoro=self.kokoro)
        service.close(); service.thread.join(2)
        job = {"jobId": "old", "chapterIndices": [0], "tasks": [], "backend": "kokoro", "revision": 0, "state": "running"}
        with patch.object(self.kokoro, "release_reference") as release:
            service._clean(job, 0)
            release.assert_not_called()

    def test_legacy_start_does_not_rebind_current_reader(self):
        speech = SpeechController()
        speech._backend = "edge"
        speech._book_id = "book-a"
        speech._tts_cache_dir = str(self.root / "tts_cache")
        with patch("novelreader.tts_engine.WholeBookCacher") as factory:
            factory.return_value.status.return_value = {"state": "caching"}
            speech.start_book_cache(book(), "book-b")
        self.assertEqual(speech._book_id, "book-a")

if __name__ == "__main__": unittest.main()
