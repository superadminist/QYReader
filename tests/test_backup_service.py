"""Isolated snapshots, archive validation, portable IDs and rollback."""
import hashlib
import json
import os
import sqlite3
import stat
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from novelreader.backup_service import BackupService
from novelreader.book_loader import BookContent, Chapter
from novelreader.feature_store import FeatureError
from novelreader.reader_service import ReaderService


class BackupServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "source-data"
        self.root.mkdir()
        self.custom = self.base / "custom-body"
        (self.custom / "sources").mkdir(parents=True)
        self.audio = self.base / "custom-audio"
        (self.audio / "kokoro-v1.0-int8").mkdir(parents=True)
        (self.audio / "kokoro-v1.0-int8" / "shared.wav").write_bytes(b"audio" * 20)
        self.external = self.base / "original.txt"
        self.external.write_text("原始正文不应被修改。", encoding="utf-8")
        content = BookContent("测试书", "作者", "txt", [Chapter("一", "第一句。"), Chapter("二", "第二句。")])
        (self.custom / "book-stable.json").write_text(json.dumps(content.to_dict()), encoding="utf-8")
        self.source_backup = self.custom / "sources" / "book-stable.txt"
        self.source_backup.write_text(self.external.read_text(encoding="utf-8"), encoding="utf-8")
        self.data = {"books": {"book-stable": {"id": "book-stable", "title": "测试书", "path": str(self.external), "source_bak": str(self.source_backup),
                      "bookmarks": [{"id": "note", "chapter_idx": 1, "offset": 0, "text": "第二句", "note": "跨章备注"}], "progress": {"chapter": 1, "offset": 2, "percent": 70, "future": 99}, "category_id": "category", "tag_ids": ["tag"], "futureMeta": {"keep": 1}}},
                     "settings": {"cache_dir": str(self.custom), "tts_cache_dir": str(self.audio), "voice_favorites": ["kokoro:v1.0:zf_xiaobei"], "futureSetting": 9},
                     "categories": [{"id": "category", "name": "测试"}], "tags": [{"id": "tag", "name": "收藏"}], "futureRoot": "keep"}
        self._save()
        self.db = sqlite3.connect(str(self.root / "reading_stats.sqlite3"))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE daily(date TEXT PRIMARY KEY,reading REAL,listening REAL,overlap REAL)")
        self.db.execute("INSERT INTO daily VALUES('2026-10-22',100,200,50)")
        self.db.commit()
        (self.root / "offline-jobs-v1.json").write_text(json.dumps({"version": 1, "jobs": [{"status": "completed", "tasks": [{"path": "kokoro-v1.0-int8/shared.wav"}]}]}), encoding="utf-8")
        self.service = BackupService(self.root)
        self.archive = self.base / "reader.qyrbackup"

    def _save(self):
        (self.root / "library.json").write_text(json.dumps(self.data), encoding="utf-8")

    def tearDown(self):
        self.db.close()
        self.service.close()
        self.temporary.cleanup()

    def test_portable_snapshot_preserves_ids_notes_unknowns_stats_and_audio(self):
        result = self.service.create(self.archive, include_audio=True)
        self.assertTrue(result["complete"])
        target = self.base / "target-data"
        destination = BackupService(target)
        try:
            preview = destination.inspect(self.archive)
            self.assertEqual(preview["bookCount"], 1)
            self.assertEqual(preview["noteCount"], 1)
            self.assertEqual(preview["statisticsRange"], ["2026-10-22", "2026-10-22"])
            destination.restore(preview["previewId"])
            restored = json.loads((target / "library.json").read_text(encoding="utf-8"))
            self.assertEqual(restored["futureRoot"], "keep")
            self.assertEqual(restored["books"]["book-stable"]["futureMeta"], {"keep": 1})
            self.assertEqual(restored["books"]["book-stable"]["bookmarks"], self.data["books"]["book-stable"]["bookmarks"])
            self.assertEqual(restored["books"]["book-stable"]["progress"], self.data["books"]["book-stable"]["progress"])
            self.assertEqual(restored["settings"]["futureSetting"], 9)
            self.assertEqual(restored["settings"]["voice_favorites"], self.data["settings"]["voice_favorites"])
            self.assertTrue(Path(restored["books"]["book-stable"]["path"]).is_relative_to(target))
            with sqlite3.connect(str(target / "reading_stats.sqlite3")) as db:
                self.assertEqual(db.execute("SELECT * FROM daily").fetchone(), ("2026-10-22", 100, 200, 50))
            self.assertEqual((target / "tts_cache/kokoro-v1.0-int8/shared.wav").read_bytes(), b"audio" * 20)
            jobs = json.loads((target / "offline-jobs-v1.json").read_text(encoding="utf-8"))
            self.assertEqual(jobs["jobs"][0]["status"], "paused")
            with patch.dict(os.environ, {"DOUBAO_NOVEL_DATA": str(target)}):
                reader = ReaderService(target / "library.json")
                opened = reader.open_book("book-stable")
                self.assertEqual(opened["book"]["chapters"][1]["title"], "二")
            self.assertEqual(self.external.read_text(encoding="utf-8"), "原始正文不应被修改。")
        finally:
            destination.close()

    def test_missing_content_is_reported_and_old_library_defaults_work(self):
        self.data["books"]["missing"] = {"path": str(self.base / "gone.txt")}
        self._save()
        inventory = self.service.inventory()
        self.assertEqual(inventory["bookCount"], 2)
        self.assertTrue(any(x["kind"] == "content" for x in inventory["missing"]))
        result = self.service.create(self.archive)
        self.assertFalse(result["complete"])
        self.assertTrue(self.service.inspect(self.archive)["missing"])

    def test_cancel_and_low_disk_leave_existing_destination(self):
        self.archive.write_bytes(b"existing backup")
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(FeatureError):
            self.service.create(self.archive, cancel=cancel)
        self.assertEqual(self.archive.read_bytes(), b"existing backup")
        with patch("novelreader.backup_service.shutil.disk_usage", return_value=type("Space", (), {"free": 0})()):
            with self.assertRaises(FeatureError):
                self.service.create(self.archive)
        self.assertEqual(self.archive.read_bytes(), b"existing backup")

    def test_malicious_paths_hashes_links_duplicates_and_unlisted_files_are_rejected(self):
        self.service.create(self.archive)
        with zipfile.ZipFile(self.archive) as source:
            originals = {name: source.read(name) for name in source.namelist()}
        def package(entries):
            target = self.base / "malicious.zip"
            with zipfile.ZipFile(target, "w") as output:
                for name, content in entries:
                    output.writestr(name, content)
            return target
        for path in ("../escape", "/absolute", "cache/../../escape", "cache\\escape", "cache/C:escape", "cache/CON.txt"):
            manifest = json.loads(originals["manifest.json"])
            manifest["files"][0]["path"] = path
            malformed = {**originals, "manifest.json": json.dumps(manifest).encode()}
            with self.assertRaises(FeatureError): self.service.inspect(package(malformed.items()))
        altered = dict(originals); altered["data/library.json"] = b"x" * len(altered["data/library.json"])
        with self.assertRaises(FeatureError) as failure: self.service.inspect(package(altered.items()))
        self.assertEqual(failure.exception.code, "BACKUP_HASH_MISMATCH")
        with self.assertRaises(FeatureError): self.service.inspect(package([*originals.items(), ("unlisted", b"x")]))
        with self.assertRaises(FeatureError): self.service.inspect(package([*originals.items(), ("DATA/LIBRARY.JSON", originals["data/library.json"])]))
        target = package(originals.items())
        manifest = json.loads(originals["manifest.json"])
        link_bytes = b"../../escape"
        manifest["files"].append({"path": "cache/link", "size": len(link_bytes), "sha256": hashlib.sha256(link_bytes).hexdigest()})
        changed = {**originals, "manifest.json": json.dumps(manifest).encode()}
        target = package(changed.items())
        with zipfile.ZipFile(target, "a") as output:
            link = zipfile.ZipInfo("data/cache/link")
            link.create_system = 3; link.external_attr = (stat.S_IFLNK | 0o777) << 16
            output.writestr(link, link_bytes)
        with self.assertRaises(FeatureError): self.service.inspect(target)
        self.assertFalse((self.base / "escape").exists())

    def test_audio_only_backup_preserves_selected_model_variant_without_installing_model(self):
        from novelreader.kokoro_service import KokoroService, MODEL_PACKAGES
        registry = {"directory": str(self.base / "external-model"), "variant": "fp32"}
        (self.root / "kokoro-model.json").write_text(json.dumps(registry), encoding="utf-8")
        digest = hashlib.sha256(f"{MODEL_PACKAGES['fp32']['sha256']}|45|200|v1|已缓存。".encode()).hexdigest()
        wav = self.audio / "kokoro-v1.0-fp32" / (digest + ".wav")
        wav.parent.mkdir(); wav.write_bytes(b"mock cached WAV" * 10)
        self.service.create(self.archive, include_audio=True, include_models=False)
        destination = BackupService(self.base / "audio-only-target")
        kokoro = None
        try:
            preview = destination.inspect(self.archive)
            destination.restore(preview["previewId"])
            kokoro = KokoroService(destination.root)
            self.assertEqual(kokoro.variant, "fp32")
            self.assertEqual(kokoro.snapshot()["status"], "missing")
            with patch.object(kokoro, "_load_engine", side_effect=AssertionError("no model loading")):
                self.assertEqual(kokoro.request("已缓存。", "kokoro:v1.0:zf_xiaobei", 200).result().read_bytes(), wav.read_bytes())
        finally:
            if kokoro is not None: kokoro.close()
            destination.close()

    def test_archive_rejects_unsafe_book_id_even_with_matching_file_hashes(self):
        self.service.create(self.archive)
        with zipfile.ZipFile(self.archive) as source:
            entries = {name: source.read(name) for name in source.namelist()}
        library = json.loads(entries["data/library.json"])
        library["books"]["../outside"] = library["books"].pop("book-stable")
        encoded = json.dumps(library).encode()
        manifest = json.loads(entries["manifest.json"])
        manifest["bookFiles"]["../outside"] = manifest["bookFiles"].pop("book-stable")
        record = next(record for record in manifest["files"] if record["path"] == "library.json")
        record.update(size=len(encoded), sha256=hashlib.sha256(encoded).hexdigest())
        entries.update({"data/library.json": encoded, "manifest.json": json.dumps(manifest).encode()})
        forged = self.base / "unsafe-id.zip"
        with zipfile.ZipFile(forged, "w") as output:
            for name, content in entries.items(): output.writestr(name, content)
        with self.assertRaises(FeatureError) as failure: self.service.inspect(forged)
        self.assertEqual(failure.exception.code, "BACKUP_ARCHIVE_INVALID")

    def test_restore_failure_rolls_back_every_file(self):
        self.service.create(self.archive)
        target = self.base / "restore-target"
        target.mkdir(); (target / "library.json").write_bytes(b'{"books":{},"settings":{},"original":1}')
        (target / "cache").mkdir(); (target / "cache/old.txt").write_bytes(b"old")
        destination = BackupService(target)
        preview = destination.inspect(self.archive)
        real_replace = os.replace
        failed = False
        def fail_once(source, destination):
            nonlocal failed
            if not failed and Path(destination) == target / "reading_stats.sqlite3":
                failed = True; raise OSError("simulated interrupted restore")
            return real_replace(source, destination)
        try:
            with patch("novelreader.backup_service.os.replace", side_effect=fail_once):
                with self.assertRaises(OSError): destination.restore(preview["previewId"])
            self.assertEqual((target / "library.json").read_bytes(), b'{"books":{},"settings":{},"original":1}')
            self.assertEqual((target / "cache/old.txt").read_bytes(), b"old")
            self.assertFalse((target / "reading_stats.sqlite3").exists())
            restored = destination.restore(preview["previewId"])
            self.assertTrue(restored["restored"])
            rollback = Path(restored["rollbackDirectory"])
            self.assertTrue((rollback / "library.json").exists())
            self.assertTrue((rollback / "cache/old.txt").exists())
            self.assertTrue(Path(restored["rollbackArchive"]).is_file())
            rollback_preview = destination.inspect(restored["rollbackArchive"])
            self.assertEqual(rollback_preview["bookCount"], 0)
        finally:
            destination.close()

    def test_background_job_and_destination_protection(self):
        with self.assertRaises(FeatureError): self.service.create(self.root / "backup.zip")
        with self.assertRaises(FeatureError): self.service.create(self.external)
        job = self.service.start("create", destination=self.archive)
        deadline = time.monotonic() + 10
        while job["status"] == "running" and time.monotonic() < deadline:
            time.sleep(.01); job = self.service.state(job["jobId"])
        self.assertEqual(job["status"], "completed")
        self.assertTrue(self.archive.exists())

    def test_old_defaults_and_restore_space_cancel_preserve_current_data(self):
        old_root = self.base / "old-data"
        old_root.mkdir(); (old_root / "library.json").write_text('{"books":{},"futureRoot":123}', encoding="utf-8")
        old = BackupService(old_root)
        try:
            old.create(self.archive)
            preview = self.service.inspect(self.archive)
            before = (self.root / "library.json").read_bytes()
            cancel = threading.Event(); cancel.set()
            with self.assertRaises(FeatureError): self.service.restore(preview["previewId"], cancel=cancel)
            with patch("novelreader.backup_service.shutil.disk_usage", return_value=type("Space", (), {"free": 0})()):
                with self.assertRaises(FeatureError): self.service.restore(preview["previewId"])
            self.assertEqual((self.root / "library.json").read_bytes(), before)
            # Restore to another isolated root; no statistics connection is open there.
            target = BackupService(self.base / "old-restored")
            try:
                result = target.inspect(self.archive)
                target.restore(result["previewId"])
                restored = json.loads((target.root / "library.json").read_text(encoding="utf-8"))
                self.assertEqual(restored["futureRoot"], 123)
                self.assertIn("cache_dir", restored["settings"])
            finally: target.close()
        finally: old.close()

    def test_cancel_after_first_swap_rolls_back_and_close_finishes_job(self):
        self.service.create(self.archive)
        target = self.base / "cancel-target"
        target.mkdir()
        before = b'{"books":{},"settings":{},"original":1}'
        (target / "library.json").write_bytes(before)
        destination = BackupService(target)
        preview = destination.inspect(self.archive)
        cancel = threading.Event()
        real_replace = os.replace
        triggered = False
        def cancel_after_first_swap(source, result):
            nonlocal triggered
            value = real_replace(source, result)
            if not triggered and Path(result) == target / "library.json":
                triggered = True
                cancel.set()
            return value
        try:
            with patch("novelreader.backup_service.os.replace", side_effect=cancel_after_first_swap):
                with self.assertRaises(FeatureError) as failure:
                    destination.restore(preview["previewId"], cancel=cancel)
            self.assertEqual(failure.exception.code, "BACKUP_CANCELLED")
            self.assertTrue(triggered)
            self.assertEqual((target / "library.json").read_bytes(), before)
            self.assertFalse((target / "cache").exists())
            job = destination.start("inventory")
            self.assertTrue(destination.close())
            self.assertNotEqual(destination.state(job["jobId"])["status"], "running")
        finally:
            destination.close()


if __name__ == "__main__":
    unittest.main()
