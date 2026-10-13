"""Offline queue/cache regressions without a model download or audio device."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from novelreader.feature_store import FeatureError
from novelreader.kokoro_service import MODEL_SHA256, KokoroService, _cache_path


VOICE = "kokoro:v1.0:zf_xiaobei"


class KokoroSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = KokoroService(self.root)
        self.service.state["status"] = "ready"
        self.release = threading.Event()

    def tearDown(self):
        self.release.set()
        self.service.close()
        self.service.executor.thread.join(2)
        # This is the exact TemporaryDirectory owned by this test. Its long
        # children need the same extended path for Windows cleanup as writing.
        self.assertEqual(self.root, Path(self.temp.name))
        self.temp.name = str(_cache_path(self.root))
        self.temp.cleanup()

    def test_current_sentence_overtakes_queued_prefetch_without_duplicate_generation(self):
        entered = threading.Event()
        order = []
        def generate(key, text, sid, rate):
            order.append(text)
            if text == "正在生成":
                entered.set()
                self.release.wait(2)
            path = self.root / (text + ".wav")
            path.write_bytes(b"test audio")
            return path
        with patch.object(self.service, "_generate", side_effect=generate):
            running = self.service.request("正在生成", VOICE, 200, priority=10)
            self.assertTrue(entered.wait(1))
            background = self.service.request("后台句", VOICE, 200, priority=10)
            next_sentence = self.service.request("当前句", VOICE, 200, priority=10)
            foreground = self.service.request("当前句", VOICE, 200, priority=0)
            self.assertIs(foreground, next_sentence)
            self.release.set()
            for future in (running, foreground, background):
                future.result(2)
        self.assertEqual(order, ["正在生成", "当前句", "后台句"])

    def test_disk_cache_replay_does_not_wait_for_busy_native_worker(self):
        entered = threading.Event()
        def blocked(*args):
            entered.set()
            self.release.wait(2)
            return self.root / "other.wav"
        key = hashlib.sha256(f"{MODEL_SHA256}|45|200|v1|已缓存句".encode()).hexdigest()
        self.service.cache.mkdir(parents=True)
        audio = self.service.cache / (key + ".wav")
        audio.write_bytes(b"RIFF" + b"x" * 48)
        with patch.object(self.service, "_generate", side_effect=blocked) as generate:
            other = self.service.request("未缓存句", VOICE, 200)
            self.assertTrue(entered.wait(1))
            ready = self.service.request("已缓存句", VOICE, 200)
            self.assertTrue(ready.done())
            self.assertEqual(ready.result(), audio)
            self.assertEqual(generate.call_count, 1)
            self.release.set()
            other.result(2)

    def test_preload_is_single_flight_and_cancel_pending_keeps_model_load(self):
        entered = threading.Event()
        engine = object()
        def load():
            entered.set()
            self.release.wait(2)
            self.service.engine = engine
            return engine
        with patch.object(self.service, "_load_engine", side_effect=load) as factory:
            first = self.service.preload()
            self.assertTrue(entered.wait(1))
            self.assertIs(self.service.preload(), first)
            self.service.cancel_pending()
            self.release.set()
            self.assertIs(first.result(2), engine)
            self.assertIsNone(self.service.preload())
            self.assertEqual(factory.call_count, 1)

    def test_uninstalled_model_is_not_loaded_by_idle_prepare(self):
        self.service.state["status"] = "missing"
        with patch.object(self.service, "_load_engine") as load:
            self.assertIsNone(self.service.preload())
            load.assert_not_called()

    def test_model_validation_failure_is_reported_before_any_audio(self):
        reported = threading.Event()
        self.service.notify = lambda state: reported.set() if state["status"] == "error" else None
        self.service.directory.mkdir(parents=True)
        (self.service.directory / "manifest.json").write_text(json.dumps({
            "files": {"missing.onnx": {"size": 1, "sha256": "bad"}}
        }))
        with patch("novelreader.kokoro_service.create_engine") as factory:
            future = self.service.preload()
            with self.assertRaisesRegex(Exception, "模型文件损坏"):
                future.result(2)
            self.assertTrue(reported.wait(1))
            factory.assert_not_called()
            self.assertEqual(self.service.snapshot()["error"]["code"], "MODEL_FILES_INVALID")

    def test_cache_accounting_does_not_scan_entire_directory_for_each_sentence(self):
        self.service.cache.mkdir(parents=True)
        first = self.service.cache / "one.wav"
        first.write_bytes(b"x" * 100)
        self.service._trim_cache(first)
        second = self.service.cache / "two.wav"
        second.write_bytes(b"x" * 200)
        with patch.object(Path, "glob", side_effect=AssertionError("unnecessary scan")):
            self.service._trim_cache(second)
        self.assertEqual(self.service._cache_bytes, 300)

    def test_recent_ready_audio_is_protected_during_cache_eviction(self):
        self.service.cache.mkdir(parents=True)
        key = hashlib.sha256(f"{MODEL_SHA256}|45|200|v1|正在回放".encode()).hexdigest()
        playing = self.service.cache / (key + ".wav")
        playing.write_bytes(b"x" * 60)
        ready = self.service.request("正在回放", VOICE, 200)
        generated = self.service.cache / "new.wav"
        generated.write_bytes(b"x" * 60)
        obsolete = self.service.cache / "obsolete.wav"
        obsolete.write_bytes(b"x" * 60)
        with patch("novelreader.kokoro_service.CACHE_BYTES", 100):
            self.service._trim_cache(generated)
        self.assertEqual(ready.result().read_bytes(), b"x" * 60)
        self.assertTrue(generated.exists())
        self.assertFalse(obsolete.exists())
        self.assertEqual(self.service._cache_bytes, 120)

    def test_old_preload_failure_does_not_mark_new_directory_broken(self):
        entered = threading.Event()
        def broken():
            entered.set()
            self.release.wait(2)
            raise FeatureError("MODEL_FILES_INVALID", "旧模型损坏", True)
        new_root = self.root / "new-models"
        directory = new_root / "kokoro" / "v1.0" / "int8"
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text(json.dumps({"installedBytes": 123}))
        with patch.object(self.service, "_load_engine", side_effect=broken):
            old = self.service.preload()
            self.assertTrue(entered.wait(1))
            self.service.set_directory(new_root)
            self.release.set()
            with self.assertRaises(FeatureError):
                old.result(2)
        self.assertEqual(self.service.snapshot()["status"], "ready")
        self.assertIsNone(self.service.snapshot()["error"])

    def test_optional_fp32_keeps_int8_model_and_voice_identity(self):
        original = self.service.directory
        original.mkdir(parents=True)
        marker = original / "keep-model.bin"
        marker.write_bytes(b"original model")
        self.service.set_variant("fp32")
        self.assertEqual(self.service.snapshot()["variant"], "fp32")
        self.assertEqual(self.service.snapshot()["totalBytes"], 349906910)
        self.assertEqual(self.service.directory, original.parent / "fp32")
        self.assertEqual(self.service.voices()[0]["id"], VOICE)
        self.assertEqual(marker.read_bytes(), b"original model")
        restored = KokoroService(self.root)
        try:
            self.assertEqual(restored.variant, "fp32")
            self.assertEqual(restored.cache.name, "kokoro-v1.0-fp32")
        finally:
            restored.close()
        self.service.set_variant("int8")
        self.assertEqual(self.service.directory, original)
        self.assertEqual(marker.read_bytes(), b"original model")

    def test_invalid_or_busy_variant_does_not_persist_configuration(self):
        with self.assertRaises(FeatureError):
            self.service.set_variant("unknown")
        self.assertFalse(self.service.registry.exists())
        class Busy:
            def is_alive(self):
                return True
        self.service.thread = Busy()
        with self.assertRaises(FeatureError):
            self.service.set_variant("fp32")
        self.assertFalse(self.service.registry.exists())

    def test_old_sentence_does_not_generate_with_new_model_after_variant_switch(self):
        entered = threading.Event()
        engine = SimpleNamespace(generate=lambda *a, **k: self.fail("stale synthesis"))
        self.service.engine = engine
        load = self.service._load_engine
        def delayed_load(**kwargs):
            entered.set()
            self.release.wait(2)
            return load(**kwargs)
        with patch.object(self.service, "_load_engine", side_effect=delayed_load):
            old = self.service.request("旧模型的句子", VOICE, 200)
            self.assertTrue(entered.wait(1))
            self.service.set_variant("fp32")
            self.release.set()
            with self.assertRaises(FeatureError) as error:
                old.result(2)
            self.assertEqual(error.exception.code, "MODEL_CHANGED")
        self.assertEqual(self.service.variant, "fp32")
        self.assertFalse(self.service.cache.exists())

    @unittest.skipUnless(os.name == "nt", "Windows extended-path regression")
    def test_native_wav_writer_supports_long_cache_path(self):
        # Keep native extension initialization out of the shared Qt fixture
        # process while exercising the real writer and production service.
        script = """
import sys, wave
from pathlib import Path
from types import SimpleNamespace
from novelreader.kokoro_service import KokoroService, _cache_path
service = KokoroService(Path(sys.argv[1]))
service.state['status'] = 'ready'
service.cache = _cache_path(Path(sys.argv[1]) / ('长路径' * 60) / 'audio-cache')
service.engine = SimpleNamespace(generate=lambda *a, **k: SimpleNamespace(samples=[0.1] * 100, sample_rate=24000))
try:
    audio = service.request('长路径写入测试', 'kokoro:v1.0:zf_xiaobei', 200).result(5)
    assert len(str(audio)) > 260
    with wave.open(str(audio), 'rb') as source:
        assert source.getnframes() == 100
        assert source.getframerate() == 24000
finally:
    service.close()
    service.executor.thread.join(2)
"""
        result = subprocess.run([sys.executable, "-B", "-X", "faulthandler", "-c", script, str(self.root)],
                                cwd=Path(__file__).resolve().parents[1], text=True, encoding="utf-8", errors="replace",
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
