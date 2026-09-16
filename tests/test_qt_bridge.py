# -*- coding: utf-8 -*-
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None

if PYSIDE6_AVAILABLE:
    from PySide6.QtCore import QCoreApplication, QObject
    from PySide6.QtTest import QSignalSpy

    from novelreader import __version__
    from novelreader.import_service import LibraryImportService
    from novelreader.library_service import LibraryDataError
    from novelreader.qt_bridge import DesktopBridge, SCHEMA_VERSION
    from novelreader.software_update import ReleaseInfo, version_tuple


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class DesktopBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.data_dir = Path(self.tempdir.name) / "data"
        self.environment = patch.dict(
            os.environ,
            {"DOUBAO_NOVEL_DATA": os.fspath(self.data_dir)},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.source = Path(self.tempdir.name) / "private" / "bridge-book.txt"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("第一章\nBridge 测试正文。", encoding="utf-8")

        class FakeHandle:
            def __init__(self):
                self.moves = 0
                self.resize_edges = []

            def startSystemMove(self):
                self.moves += 1
                return True

            def startSystemResize(self, edge):
                self.resize_edges.append(edge)
                return True

        class FakeWindow(QObject):
            def __init__(self):
                super().__init__()
                self.maximized = False
                self.minimized = False
                self.closed = False
                self.fullscreen_toggles = 0
                self.launched_installer = ""
                self.opened_url = ""
                self.handle = FakeHandle()

            def isMaximized(self):
                return self.maximized

            def showMinimized(self):
                self.minimized = True

            def showMaximized(self):
                self.maximized = True

            def showNormal(self):
                self.maximized = False

            def close(self):
                self.closed = True

            def toggleFullscreenWindow(self):
                self.fullscreen_toggles += 1

            def windowHandle(self):
                return self.handle

            def launchUpdateInstaller(self, path):
                self.launched_installer = path
                return True

            def openExternalUrl(self, url):
                self.opened_url = url
                return True

        class FakeLibrary:
            path = self.data_dir / "library.json"

            def load_library(self):
                return {"books": [{"id": "book-1"}], "total": 1}

        self.window = FakeWindow()
        self.bridge = DesktopBridge(
            self.window,
            FakeLibrary(),
            importer=LibraryImportService(FakeLibrary.path),
            file_picker=lambda: [os.fspath(self.source)],
        )

    def test_initial_state_uses_schema_v2_and_current_capabilities(self):
        payload = json.loads(self.bridge.getInitialState())
        self.assertEqual(payload["schemaVersion"], SCHEMA_VERSION)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["library"]["total"], 1)
        self.assertEqual(payload["data"]["app"]["version"], "2.1.0")
        self.assertEqual(payload["data"]["preferences"]["theme"], "护眼")
        self.assertTrue(payload["data"]["preferences"]["autoOpenLast"])
        self.assertFalse(payload["data"]["preferences"]["closeToTray"])
        self.assertTrue(payload["data"]["preferences"]["autoCheckUpdates"])
        self.assertEqual(payload["data"]["softwareUpdate"]["status"], "idle")
        capabilities = payload["data"]["capabilities"]
        self.assertTrue(capabilities["fileImport"])
        self.assertTrue(capabilities["pasteImport"])
        self.assertTrue(capabilities["reader"])
        self.assertTrue(capabilities["tts"])

    def test_frozen_native_import_slots_and_signals_are_qt_visible(self):
        meta_object = self.bridge.metaObject()
        signatures = {
            bytes(meta_object.method(index).methodSignature()).decode("ascii")
            for index in range(meta_object.methodCount())
        }
        self.assertIn("selectImportFiles()", signatures)
        self.assertIn("startFileImport(QString)", signatures)
        self.assertIn("startPasteImport(QString)", signatures)
        self.assertIn("cancelImport(QString)", signatures)
        self.assertIn("importProgress(QString)", signatures)
        self.assertIn("importFinished(QString)", signatures)
        self.assertIn("updateAppPreferences(QString)", signatures)
        self.assertIn("appPreferencesChanged(QString)", signatures)
        self.assertIn("updateSpeechPreferences(QString)", signatures)
        self.assertIn("speechPreferencesChanged(QString)", signatures)
        self.assertIn("checkSoftwareUpdate(QString)", signatures)
        self.assertIn("downloadSoftwareUpdate(QString)", signatures)
        self.assertIn("skipSoftwareUpdate(QString)", signatures)
        self.assertIn("installSoftwareUpdate()", signatures)
        self.assertIn("softwareUpdateChanged(QString)", signatures)
        self.assertIn("floatingPointerChanged(bool)", signatures)
        self.assertIn("toggleFullscreen()", signatures)

    def test_library_error_is_a_safe_failure_envelope(self):
        class BrokenLibrary:
            def load_library(self):
                raise LibraryDataError()

        payload = json.loads(DesktopBridge(self.window, BrokenLibrary()).getInitialState())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "LIBRARY_INVALID")
        self.assertEqual(payload["data"]["library"], {"books": [], "total": 0})

    def test_window_controls_delegate_to_the_host(self):
        state_spy = QSignalSpy(self.bridge.windowStateChanged)
        self.bridge.minimizeWindow()
        self.bridge.toggleMaximizeWindow()
        self.bridge.toggleFullscreen()
        self.bridge.startWindowMove()
        self.bridge.startWindowResize("bottomRight")
        self.bridge.closeWindow()

        self.assertTrue(self.window.minimized)
        self.assertTrue(self.window.maximized)
        self.assertEqual(self.window.fullscreen_toggles, 1)
        self.assertEqual(self.window.handle.moves, 1)
        self.assertEqual(len(self.window.handle.resize_edges), 1)
        self.assertTrue(self.window.closed)
        self.assertEqual(state_spy.count(), 0)

        self.bridge.emitWindowState()
        self.assertEqual(state_spy.count(), 1)

        self.bridge.toggleMaximizeWindow()
        self.assertFalse(self.window.maximized)

    def test_app_preferences_are_validated_persisted_and_emitted(self):
        preference_spy = QSignalSpy(self.bridge.appPreferencesChanged)
        payload = json.loads(self.bridge.updateAppPreferences(json.dumps({
            "patch": {"theme": "夜间", "autoOpenLast": False, "closeToTray": True}
        })))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["colorScheme"], "dark")
        self.assertFalse(payload["data"]["autoOpenLast"])
        self.assertTrue(payload["data"]["closeToTray"])
        self.assertEqual(preference_spy.count(), 1)
        stored = json.loads((self.data_dir / "library.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["settings"]["theme"], "夜间")
        self.assertFalse(stored["settings"]["auto_open_last"])
        self.assertTrue(stored["settings"]["close_to_tray"])

        self.bridge.closeWindow()
        self.assertTrue(self.window.minimized)
        self.assertFalse(self.window.closed)

        rejected = json.loads(self.bridge.updateAppPreferences(json.dumps({
            "patch": {"theme": "蓝色"}
        })))
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error"]["code"], "INVALID_REQUEST")

    def test_software_update_check_download_skip_install_and_open_page(self):
        major, minor, patch_version = version_tuple(__version__)
        next_version = f"{major}.{minor}.{patch_version + 1}"
        installer_path = Path(self.tempdir.name) / f"QYReader-Setup-{next_version}.exe"

        class FakeSoftwareUpdates:
            @staticmethod
            def check_latest():
                return ReleaseInfo(
                    version=next_version,
                    tag=f"v{next_version}",
                    release_url=f"https://github.com/superadminist/QYReader/releases/tag/v{next_version}",
                    published_at="2026-09-14T09:00:00Z",
                    installer_name=f"QYReader-Setup-{next_version}.exe",
                    installer_url=f"https://github.com/superadminist/QYReader/releases/download/v{next_version}/QYReader-Setup-{next_version}.exe",
                    installer_size=9,
                    checksum_url=f"https://github.com/superadminist/QYReader/releases/download/v{next_version}/SHA256SUMS.txt",
                    release_notes="- 修复悬浮窗暂停错句\n- 设置立即生效",
                )

            @staticmethod
            def download(_release, progress):
                installer_path.write_bytes(b"installer")
                progress(9, 9)
                return installer_path

        self.bridge._software_updates = FakeSoftwareUpdates()
        update_spy = QSignalSpy(self.bridge.softwareUpdateChanged)

        mark = update_spy.count()
        started = json.loads(self.bridge.checkSoftwareUpdate(json.dumps({"manual": True})))
        self.assertEqual(started["data"]["status"], "checking")
        available = self._wait_for_update_status(update_spy, "available", mark)
        self.assertIn("暂停错句", available["releaseNotes"])
        self.assertEqual(available["publishedAt"], "2026-09-14T09:00:00Z")

        skipped = json.loads(self.bridge.skipSoftwareUpdate(json.dumps({"version": next_version})))
        self.assertEqual(skipped["data"]["status"], "skipped")
        metadata = self.bridge._app.update_metadata()
        self.assertEqual(metadata["skippedVersion"], next_version)

        mark = update_spy.count()
        self.bridge.checkSoftwareUpdate(json.dumps({"manual": True}))
        self._wait_for_update_status(update_spy, "available", mark)
        mark = update_spy.count()
        downloading = json.loads(self.bridge.downloadSoftwareUpdate(json.dumps({"version": next_version})))
        self.assertEqual(downloading["data"]["status"], "downloading")
        ready = self._wait_for_update_status(update_spy, "ready", mark)
        self.assertEqual(ready["progressPercent"], 100)
        self.assertTrue(ready["canInstall"])

        opened = json.loads(self.bridge.openSoftwareUpdatePage("release"))
        self.assertTrue(opened["ok"])
        self.assertTrue(self.window.opened_url.endswith(f"/tag/v{next_version}"))
        installing = json.loads(self.bridge.installSoftwareUpdate())
        self.assertEqual(installing["data"]["status"], "installing")
        self.assertEqual(self.window.launched_installer, str(installer_path))

    def _wait_for_update_status(self, spy, expected, start_index=0):
        deadline = time.time() + 3
        while time.time() < deadline:
            self.app.processEvents()
            for index in range(start_index, spy.count()):
                state = json.loads(spy.at(index)[0])
                if state["status"] == expected:
                    return state
            time.sleep(0.01)
        self.fail(f"software update state did not reach {expected}")

    def test_invalid_resize_edge_emits_bridge_error(self):
        error_spy = QSignalSpy(self.bridge.bridgeError)
        self.bridge.startWindowResize("diagonal")
        self.assertEqual(error_spy.count(), 1)
        payload = json.loads(error_spy.at(0)[0])
        self.assertEqual(payload["code"], "INVALID_RESIZE_EDGE")
        self.assertEqual(self.window.handle.resize_edges, [])

    def test_file_selection_and_async_import_follow_the_frozen_contract(self):
        selection = json.loads(self.bridge.selectImportFiles())
        self.assertTrue(selection["ok"])
        self.assertEqual(selection["data"]["total"], 1)
        self.assertNotIn(os.fspath(self.source), json.dumps(selection, ensure_ascii=False))

        progress_spy = QSignalSpy(self.bridge.importProgress)
        finished_spy = QSignalSpy(self.bridge.importFinished)
        request = json.dumps({
            "selectionId": selection["data"]["selectionId"],
            "confirmLargeFiles": True,
            "duplicateMode": "overwrite",
        })
        started = json.loads(self.bridge.startFileImport(request))
        self.assertTrue(started["ok"])
        self.assertEqual(started["data"]["state"], "queued")
        self.assertFalse(self.bridge._import_thread.daemon)

        deadline = time.time() + 5
        while finished_spy.count() == 0 and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        self.assertGreaterEqual(progress_spy.count(), 2)
        self.assertEqual(finished_spy.count(), 1)
        finished = json.loads(finished_spy.at(0)[0])
        self.assertEqual(finished["schemaVersion"], SCHEMA_VERSION)
        self.assertEqual(finished["state"], "completed")
        self.assertEqual(finished["succeeded"], 1)
        self.assertTrue(finished["openAfterImportBookId"])
        self.assertNotIn(os.fspath(self.source), json.dumps(finished, ensure_ascii=False))

    def test_import_slots_reject_invalid_or_expired_requests_safely(self):
        invalid = json.loads(self.bridge.startPasteImport("not-json"))
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["error"]["code"], "INVALID_REQUEST")

        expired = json.loads(self.bridge.startFileImport(json.dumps({
            "selectionId": "missing",
            "confirmLargeFiles": True,
            "duplicateMode": "overwrite",
        })))
        self.assertFalse(expired["ok"])
        self.assertEqual(expired["error"]["code"], "SELECTION_EXPIRED")

    def test_slow_import_runs_off_the_qt_calling_thread(self):
        started = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        worker_thread_ids = []

        class SlowImporter:
            def import_pasted_text(self, _title, _text, _cancel, _progress):
                worker_thread_ids.append(threading.get_ident())
                started.set()
                release.wait(2)
                return {
                    "state": "completed",
                    "total": 1,
                    "processed": 1,
                    "succeeded": 1,
                    "failed": 0,
                    "lastImportedBookId": "book-id",
                    "openAfterImportBookId": "book-id",
                    "results": [{
                        "name": "粘贴文本",
                        "status": "succeeded",
                        "bookId": "book-id",
                        "error": None,
                    }],
                }

        bridge = DesktopBridge(self.window, importer=SlowImporter())
        main_thread_id = threading.get_ident()
        before = time.perf_counter()
        response = json.loads(bridge.startPasteImport(json.dumps({
            "title": "标题",
            "text": "正文",
        })))
        elapsed = time.perf_counter() - before

        self.assertTrue(response["ok"])
        self.assertLess(elapsed, 0.2)
        self.assertTrue(started.wait(1))
        self.assertNotEqual(worker_thread_ids, [main_thread_id])
        self.assertFalse(bridge._import_thread.daemon)
        release.set()
        bridge._import_thread.join(2)
        bridge._drain_import_events()


if __name__ == "__main__":
    unittest.main()
