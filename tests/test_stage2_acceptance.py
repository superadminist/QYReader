# -*- coding: utf-8 -*-
"""Executable acceptance contract for stage-2 library imports.

These tests intentionally target only the public Qt bridge contract.  They use
an isolated DOUBAO_NOVEL_DATA directory and must fail (never skip) until the
stage-2 implementation exists.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QObject
from PySide6.QtTest import QSignalSpy

from novelreader.library_service import LibraryQueryService
from novelreader.qt_bridge import DesktopBridge, SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[1]
REAL_LIBRARY = Path(os.environ.get("APPDATA", Path.home())) / "DDNovelReader" / "library.json"
PROTECTED_FILES = (REAL_LIBRARY, ROOT / "sample" / "星火.docx", ROOT / "sample" / "星火.epub")


def _fingerprint(path: Path):
    if not path.is_file():
        return None
    stat = path.stat()
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _tree_manifest(root: Path):
    if not root.exists():
        return {}
    return {
        item.relative_to(root).as_posix(): _fingerprint(item)
        for item in sorted(root.rglob("*"))
        if item.is_file()
    }


class _FakeHandle:
    def startSystemMove(self):
        return True

    def startSystemResize(self, _edge):
        return True


class _FakeWindow(QObject):
    def __init__(self):
        super().__init__()
        self._maximized = False

    def isMaximized(self):
        return self._maximized

    def showMinimized(self):
        pass

    def showMaximized(self):
        self._maximized = True

    def showNormal(self):
        self._maximized = False

    def close(self):
        pass

    def windowHandle(self):
        return _FakeHandle()


class Stage2AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])
        cls.protected_before = {path: _fingerprint(path) for path in PROTECTED_FILES}

    @classmethod
    def tearDownClass(cls):
        protected_after = {path: _fingerprint(path) for path in PROTECTED_FILES}
        if protected_after != cls.protected_before:
            raise AssertionError(
                "Stage-2 acceptance modified a protected real-data/sample file: "
                f"before={cls.protected_before!r}, after={protected_after!r}"
            )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ddnr_stage2_acceptance_")
        self.case_root = Path(self.temp.name)
        self.data_root = self.case_root / "data"
        self.input_root = self.case_root / "inputs"
        self.data_root.mkdir()
        self.input_root.mkdir()
        self.env = patch.dict(
            os.environ,
            {"DOUBAO_NOVEL_DATA": os.fspath(self.data_root)},
            clear=False,
        )
        self.env.start()
        self.window = _FakeWindow()
        self.selected_paths = []
        self.bridge = DesktopBridge(
            self.window,
            file_picker=lambda: list(self.selected_paths),
        )

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def _write_input(self, name: str, content: bytes) -> Path:
        path = self.input_root / name
        path.write_bytes(content)
        return path

    def _require_method(self, name: str):
        method = getattr(self.bridge, name, None)
        self.assertTrue(callable(method), f"Stage-2 bridge method is missing: {name}")
        return method

    def _require_signal(self, name: str):
        signal = getattr(self.bridge, name, None)
        self.assertIsNotNone(signal, f"Stage-2 bridge signal is missing: {name}")
        self.assertTrue(hasattr(signal, "connect"), f"Stage-2 bridge signal is invalid: {name}")
        return signal

    def _call(self, name: str, *args):
        raw = self._require_method(name)(*args)
        self.assertIsInstance(raw, str, f"{name} must return a JSON string")
        payload = json.loads(raw)
        self._assert_envelope(payload)
        return payload, raw

    def _call_json(self, name: str, payload):
        return self._call(
            name,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )

    def _assert_envelope(self, payload):
        self.assertEqual(payload.get("schemaVersion"), SCHEMA_VERSION)
        self.assertIsInstance(payload.get("ok"), bool)
        self.assertIsInstance(payload.get("data"), dict)
        error = payload.get("error")
        if payload["ok"]:
            self.assertIsNone(error)
        else:
            self.assertIsInstance(error, dict)
            self.assertIsInstance(error.get("code"), str)
            self.assertTrue(error["code"])
            self.assertIsInstance(error.get("message"), str)
            self.assertIsInstance(error.get("retryable"), bool)

    def _set_file_picker(self, paths):
        self.selected_paths = [os.fspath(path) for path in paths]

    def _select_files(self, paths):
        self._set_file_picker(paths)
        return self._call("selectImportFiles")

    def _finished_spy(self):
        return QSignalSpy(self._require_signal("importFinished"))

    def _progress_spy(self):
        return QSignalSpy(self._require_signal("importProgress"))

    def _wait_finished(self, spy: QSignalSpy, timeout_ms: int = 15_000):
        if spy.count() == 0:
            self.assertTrue(spy.wait(timeout_ms), "Timed out waiting for importFinished")
        raw = spy.at(spy.count() - 1)[0]
        self.assertIsInstance(raw, str)
        event = json.loads(raw)
        self._assert_finished_event(event)
        return event, raw

    def _assert_progress_event(self, event):
        self.assertEqual(event.get("schemaVersion"), SCHEMA_VERSION)
        self.assertIsInstance(event.get("jobId"), str)
        self.assertTrue(event["jobId"])
        self.assertEqual(event.get("phase"), "item")
        for key in ("completed", "total", "succeeded", "failed"):
            self.assertIsInstance(event.get(key), int)
            self.assertGreaterEqual(event[key], 0)
        self.assertIsInstance(event.get("item"), dict)
        self.assertIsInstance(event["item"].get("index"), int)
        self.assertIsInstance(event["item"].get("name"), str)
        self.assertIn(event["item"].get("status"), {"running", "succeeded", "failed"})
        self.assertIsInstance(event["item"].get("bookId"), str)
        if event.get("error") is not None:
            self.assertIsInstance(event["error"].get("code"), str)
            self.assertIsInstance(event["error"].get("message"), str)
            self.assertIsInstance(event["error"].get("retryable"), bool)

    def _assert_finished_event(self, event):
        self.assertEqual(event.get("schemaVersion"), SCHEMA_VERSION)
        self.assertIsInstance(event.get("jobId"), str)
        self.assertTrue(event["jobId"])
        self.assertIn(event.get("state"), {"completed", "cancelled"})
        for key in ("total", "processed", "succeeded", "failed"):
            self.assertIsInstance(event.get(key), int)
            self.assertGreaterEqual(event[key], 0)
        self.assertLessEqual(event["processed"], event["total"])
        self.assertEqual(event["processed"], event["succeeded"] + event["failed"])
        self.assertIsInstance(event.get("lastImportedBookId"), str)
        self.assertIsInstance(event.get("openAfterImportBookId"), str)
        self.assertIsInstance(event.get("results"), list)
        self.assertEqual(len(event["results"]), event["processed"])
        for result in event["results"]:
            self.assertIsInstance(result.get("name"), str)
            self.assertIn(result.get("status"), {"succeeded", "failed"})
            self.assertIsInstance(result.get("bookId"), str)
            error = result.get("error")
            if result["status"] == "succeeded":
                self.assertIsNone(error)
                self.assertTrue(result["bookId"])
            else:
                self.assertIsInstance(error, dict)
                self.assertIsInstance(error.get("code"), str)
                self.assertIsInstance(error.get("message"), str)
                self.assertIsInstance(error.get("retryable"), bool)

    def test_missing_library_is_empty_and_read_only(self):
        library_path = self.data_root / "library.json"
        self.assertFalse(library_path.exists())
        before = _tree_manifest(self.data_root)

        payload = json.loads(self.bridge.getInitialState())

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["library"], {"books": [], "total": 0, "sortMode": "recent"})
        self.assertEqual(_tree_manifest(self.data_root), before)
        self.assertFalse(library_path.exists())

    def test_corrupt_library_is_safe_and_does_not_expose_its_path(self):
        library_path = self.data_root / "library.json"
        library_path.write_text("{not json", encoding="utf-8")
        before = _fingerprint(library_path)

        raw = self.bridge.getInitialState()
        payload = json.loads(raw)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "LIBRARY_INVALID")
        self.assertNotIn(os.fspath(library_path), raw)
        self.assertEqual(_fingerprint(library_path), before)

    def test_current_capabilities_enable_imports_reader_and_tts(self):
        payload = json.loads(self.bridge.getInitialState())
        capabilities = payload["data"]["capabilities"]
        self.assertTrue(capabilities["fileImport"])
        self.assertTrue(capabilities["pasteImport"])
        self.assertFalse(capabilities["webImport"])
        self.assertFalse(capabilities["audioImport"])
        self.assertTrue(capabilities["reader"])
        self.assertTrue(capabilities["tts"])
        self.assertTrue(capabilities["floatingReader"])

    def test_file_selection_cancel_is_a_zero_write_success(self):
        before = _tree_manifest(self.data_root)
        self._set_file_picker([])
        finished = self._finished_spy()
        payload, _ = self._call("selectImportFiles")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["cancelled"], True)
        self.assertEqual(payload["data"]["selectionId"], "")
        self.assertEqual(payload["data"]["total"], 0)
        self.assertEqual(payload["data"]["items"], [])
        self.assertEqual(finished.count(), 0)
        self.assertEqual(_tree_manifest(self.data_root), before)

    def test_txt_file_import_is_real_redacted_and_produces_open_intent(self):
        source = self._write_input("阶段2测试.txt", "第一章\n真实正文第一句。第二句。".encode("utf-8"))
        source_before = _fingerprint(source)
        selection, selection_raw = self._select_files([source])
        finished = self._finished_spy()
        progress = self._progress_spy()

        self.assertTrue(selection["ok"])
        self.assertFalse(selection["data"]["cancelled"])
        self.assertEqual(selection["data"]["total"], 1)
        item = selection["data"]["items"][0]
        self.assertEqual(item["name"], source.name)
        self.assertEqual(item["format"].lower(), "txt")
        self.assertEqual(item["sizeBytes"], source.stat().st_size)
        self.assertTrue(item["supported"])
        self.assertFalse(item["duplicate"]["exists"])
        self.assertNotIn(os.fspath(source), selection_raw)
        self.assertNotIn("path", item)
        self.assertNotIn("sourcePath", item)

        started, _ = self._call_json("startFileImport", {
            "selectionId": selection["data"]["selectionId"],
            "confirmLargeFiles": True,
            "duplicateMode": "cancel",
        })
        self.assertTrue(started["ok"])
        self.assertEqual(started["data"]["state"], "queued")
        self.assertTrue(started["data"]["jobId"])
        event, event_raw = self._wait_finished(finished)

        self.assertEqual(event["jobId"], started["data"]["jobId"])
        self.assertEqual(event["state"], "completed")
        self.assertEqual((event["total"], event["succeeded"], event["failed"]), (1, 1, 0))
        self.assertTrue(event["openAfterImportBookId"])
        self.assertEqual(event["openAfterImportBookId"], event["lastImportedBookId"])
        self.assertNotIn(os.fspath(source), event_raw)
        self.assertNotIn("chapters", event)
        self.assertNotIn("content", event)
        self.assertNotIn("body", event)
        self.assertGreater(progress.count(), 0)
        for index in range(progress.count()):
            self._assert_progress_event(json.loads(progress.at(index)[0]))
        self.assertEqual(LibraryQueryService().load_library()["total"], 1)
        self.assertEqual(_fingerprint(source), source_before)
        self.assertTrue(json.loads(self.bridge.getInitialState())["data"]["capabilities"]["reader"])

    def test_paste_import_uses_real_text_unique_ids_and_no_reader_payload(self):
        first_finished = self._finished_spy()
        first, _ = self._call_json("startPasteImport", {
            "title": "",
            "text": "首行标题\n真实正文内容。",
        })
        self.assertTrue(first["ok"])
        first_event, _ = self._wait_finished(first_finished)
        first_id = first_event["openAfterImportBookId"]
        self.assertTrue(first_id)
        self.assertNotIn("chapters", first_event)
        self.assertNotIn("content", first_event)

        second_finished = self._finished_spy()
        second, _ = self._call_json("startPasteImport", {
            "title": "",
            "text": "首行标题\n真实正文内容。",
        })
        self.assertTrue(second["ok"])
        second_event, _ = self._wait_finished(second_finished)
        second_id = second_event["openAfterImportBookId"]

        self.assertTrue(second_id)
        self.assertNotEqual(first_id, second_id)
        library = LibraryQueryService().load_library()
        self.assertEqual(library["total"], 2)
        titles = [book["title"] for book in library["books"]]
        self.assertEqual(len(set(titles)), 2)
        self.assertTrue(all(title.endswith("-首行标题") for title in titles))
        pasted_sources = sorted((self.data_root / "pasted").glob("*.txt"))
        self.assertEqual(len(pasted_sources), 2)
        self.assertEqual(len({path.name for path in pasted_sources}), 2)
        self.assertTrue(all(
            path.read_text(encoding="utf-8")
            == "首行标题\n\n首行标题\n真实正文内容。"
            for path in pasted_sources
        ))
        self.assertTrue(json.loads(self.bridge.getInitialState())["data"]["capabilities"]["reader"])

    def test_invalid_requests_fail_closed_without_files_or_events(self):
        before = _tree_manifest(self.data_root)
        finished = self._finished_spy()

        invalid_file, invalid_raw = self._call_json("startFileImport", {
            "selectionId": "missing-selection",
            "confirmLargeFiles": False,
            "duplicateMode": "invalid-mode",
        })
        self.assertFalse(invalid_file["ok"])
        self.assertNotIn(os.fspath(self.data_root), invalid_raw)

        invalid_paste, invalid_paste_raw = self._call_json("startPasteImport", {
            "title": "空正文",
            "text": " \n\t ",
        })
        self.assertFalse(invalid_paste["ok"])
        self.assertNotIn(os.fspath(self.data_root), invalid_paste_raw)

        invalid_cancel, _ = self._call("cancelImport", "missing-job")
        self.assertFalse(invalid_cancel["ok"])
        self.assertFalse(invalid_cancel["data"]["cancelRequested"])
        self.assertEqual(finished.count(), 0)
        self.assertEqual(_tree_manifest(self.data_root), before)

    def test_partial_failure_keeps_success_and_redacts_failed_path(self):
        valid = self._write_input("成功.txt", "第一章\n可读取正文。".encode("utf-8"))
        broken = self._write_input("损坏.epub", b"not-an-epub")
        valid_before = _fingerprint(valid)
        broken_before = _fingerprint(broken)
        selection, selection_raw = self._select_files([valid, broken])
        finished = self._finished_spy()

        self.assertTrue(selection["ok"])
        self.assertEqual(selection["data"]["total"], 2)
        self.assertNotIn(os.fspath(valid), selection_raw)
        self.assertNotIn(os.fspath(broken), selection_raw)
        started, _ = self._call_json("startFileImport", {
            "selectionId": selection["data"]["selectionId"],
            "confirmLargeFiles": True,
            "duplicateMode": "cancel",
        })
        self.assertTrue(started["ok"])
        event, event_raw = self._wait_finished(finished)

        self.assertEqual(event["state"], "completed")
        self.assertEqual((event["total"], event["processed"]), (2, 2))
        self.assertEqual((event["succeeded"], event["failed"]), (1, 1))
        self.assertTrue(event["openAfterImportBookId"])
        self.assertEqual([item["status"] for item in event["results"]], ["succeeded", "failed"])
        self.assertNotIn(os.fspath(valid), event_raw)
        self.assertNotIn(os.fspath(broken), event_raw)
        self.assertEqual(LibraryQueryService().load_library()["total"], 1)
        self.assertEqual(_fingerprint(valid), valid_before)
        self.assertEqual(_fingerprint(broken), broken_before)

    def test_duplicate_file_is_reported_and_cancel_mode_is_zero_write(self):
        source = self._write_input("重复书.txt", "第一章\n重复导入正文。".encode("utf-8"))
        first_selection, _ = self._select_files([source])
        first_finished = self._finished_spy()
        first_start, _ = self._call_json("startFileImport", {
            "selectionId": first_selection["data"]["selectionId"],
            "confirmLargeFiles": True,
            "duplicateMode": "cancel",
        })
        self.assertTrue(first_start["ok"])
        first_event, _ = self._wait_finished(first_finished)
        first_book_id = first_event["openAfterImportBookId"]
        self.assertTrue(first_book_id)
        before_duplicate = _tree_manifest(self.data_root)

        duplicate_selection, duplicate_raw = self._select_files([source])
        self.assertTrue(duplicate_selection["ok"])
        self.assertEqual(duplicate_selection["data"]["duplicateCount"], 1)
        duplicate_item = duplicate_selection["data"]["items"][0]
        self.assertTrue(duplicate_item["duplicate"]["exists"])
        self.assertEqual(duplicate_item["duplicate"]["bookId"], first_book_id)
        self.assertTrue(duplicate_item["duplicate"]["title"])
        self.assertNotIn(os.fspath(source), duplicate_raw)

        cancelled_finished = self._finished_spy()
        cancelled_start, _ = self._call_json("startFileImport", {
            "selectionId": duplicate_selection["data"]["selectionId"],
            "confirmLargeFiles": True,
            "duplicateMode": "cancel",
        })
        self.assertTrue(cancelled_start["ok"])
        cancelled_event, _ = self._wait_finished(cancelled_finished)
        self.assertEqual(cancelled_event["state"], "cancelled")
        self.assertEqual(cancelled_event["processed"], 0)
        self.assertEqual(cancelled_event["openAfterImportBookId"], "")
        self.assertEqual(LibraryQueryService().load_library()["total"], 1)
        self.assertEqual(_tree_manifest(self.data_root), before_duplicate)

    def test_running_job_can_be_cancelled_without_processing_later_items(self):
        first = self._write_input("慢文件.txt", "第一章\n慢解析正文。".encode("utf-8"))
        second = self._write_input("不应处理.txt", "第一章\n取消后不应处理。".encode("utf-8"))
        selection, _ = self._select_files([first, second])
        finished = self._finished_spy()
        entered = threading.Event()
        release = threading.Event()

        from novelreader import book_loader

        original_parse = book_loader.parse_book

        def slow_first(path):
            if Path(path).name == first.name:
                entered.set()
                release.wait(5)
            return original_parse(path)

        with patch.object(book_loader, "parse_book", side_effect=slow_first):
            started, _ = self._call_json("startFileImport", {
                "selectionId": selection["data"]["selectionId"],
                "confirmLargeFiles": True,
                "duplicateMode": "cancel",
            })
            self.assertTrue(started["ok"])
            self.assertTrue(entered.wait(5), "Import worker never started parsing")
            cancelled, _ = self._call("cancelImport", started["data"]["jobId"])
            self.assertTrue(cancelled["ok"])
            self.assertTrue(cancelled["data"]["cancelRequested"])
            release.set()
            event, _ = self._wait_finished(finished)

        self.assertEqual(event["state"], "cancelled")
        self.assertLess(event["processed"], event["total"])
        self.assertNotIn(second.name, [item["name"] for item in event["results"]])


if __name__ == "__main__":
    unittest.main()
