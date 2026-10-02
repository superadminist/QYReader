# -*- coding: utf-8 -*-
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QObject
from PySide6.QtTest import QSignalSpy

from novelreader.library_service import LibraryQueryService
from novelreader.qt_bridge import DesktopBridge
from novelreader.web_reader import WebArticle, WebReaderError


class WebBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "library.json"
        environment = patch.dict(os.environ, {"DOUBAO_NOVEL_DATA": self.temporary.name})
        environment.start()
        self.addCleanup(environment.stop)

        class Window(QObject):
            def isMaximized(self): return False

        self.window = Window()
        self.bridge = DesktopBridge(self.window, library=LibraryQueryService(self.path))
        self.addCleanup(self.bridge.shutdown)

    def finish(self, spy):
        self.bridge._import_thread.join(3)
        self.bridge._drain_import_events()
        self.assertEqual(spy.count(), 1)
        return json.loads(spy.at(0)[0])

    def test_public_slot_and_successful_background_import(self):
        signatures = {bytes(self.bridge.metaObject().method(i).methodSignature()).decode()
                      for i in range(self.bridge.metaObject().methodCount())}
        self.assertIn("startWebImport(QString)", signatures)
        self.assertTrue(json.loads(self.bridge.getInitialState())["data"]["capabilities"]["webImport"])
        spy = QSignalSpy(self.bridge.importFinished)
        threads = []
        def fetch(url, _cancel):
            threads.append(threading.get_ident())
            return WebArticle(url, "网页标题", "网页正文，用于验证 Bridge 导入与阅读器打开。")
        with patch("novelreader.web_reader.fetch_article", side_effect=fetch):
            response = json.loads(self.bridge.startWebImport(json.dumps({"url": "https://example.com/article"})))
            self.assertTrue(response["ok"])
            result = self.finish(spy)
        self.assertNotEqual(threads[0], threading.get_ident())
        self.assertEqual(result["succeeded"], 1)
        self.assertTrue(result["openAfterImportBookId"])
        self.assertEqual(self.bridge._reader.open_book(result["openAfterImportBookId"])["book"]["title"], "网页标题")

    def test_invalid_requests_and_http_failure_are_observable(self):
        for request in ("not-json", "{}", '{"url":"file:///c:/private"}'):
            self.assertFalse(json.loads(self.bridge.startWebImport(request))["ok"])
        spy = QSignalSpy(self.bridge.importFinished)
        with patch("novelreader.web_reader.fetch_article", side_effect=WebReaderError("WEB_HTTP_ERROR", "网页访问失败（HTTP 403）。")):
            self.bridge.startWebImport('{"url":"https://example.com/article"}')
            result = self.finish(spy)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["results"][0]["error"]["code"], "WEB_HTTP_ERROR")
        self.assertEqual(result["openAfterImportBookId"], "")
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
