import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from novelreader.app_service import AppPreferencesService
from novelreader.qt_host import DesktopWindow


class FileLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.json"
        self.preferences = AppPreferencesService(self.path)
        self.window = SimpleNamespace(bridge=SimpleNamespace(_app=self.preferences))
        self.directory = Path(self.temp.name) / "中文 路径"
        self.directory.mkdir()
        self.source = self.directory / "原 文本.txt"
        self.source.write_text("文本", encoding="utf-8")

    def test_picker_remembers_confirmed_directory_across_restart_and_cancel(self):
        with patch("novelreader.qt_host.QFileDialog.getOpenFileNames", return_value=([str(self.source)], "")):
            self.assertEqual(DesktopWindow._select_import_files(self.window), [str(self.source)])
        self.window.bridge._app = AppPreferencesService(self.path)
        with patch("novelreader.qt_host.QFileDialog.getOpenFileNames", return_value=([], "")) as picker:
            self.assertEqual(DesktopWindow._select_import_files(self.window), [])
        self.assertEqual(picker.call_args.args[2], str(self.directory))
        self.assertEqual(self.preferences.import_directory(), str(self.directory))

    def test_picker_invalid_directory_falls_back_and_save_failure_keeps_selection(self):
        self.preferences.record_import_directory(str(self.directory / "gone"))
        with patch("novelreader.qt_host.QStandardPaths.writableLocation", return_value=str(self.directory)):
            with patch("novelreader.qt_host.QFileDialog.getOpenFileNames", return_value=([str(self.source)], "")) as picker:
                with patch.object(self.preferences, "record_import_directory", side_effect=OSError("blocked")):
                    self.assertEqual(DesktopWindow._select_import_files(self.window), [str(self.source)])
        self.assertEqual(picker.call_args.args[2], str(self.directory))

    def test_missing_documents_falls_back_to_home(self):
        with patch("novelreader.qt_host.QStandardPaths.writableLocation", return_value=""):
            with patch("novelreader.qt_host.QFileDialog.getOpenFileNames", return_value=([], "")) as picker:
                DesktopWindow._select_import_files(self.window)
        self.assertEqual(picker.call_args.args[2], str(Path.home()))

    def test_explorer_uses_argument_array_and_preserves_unicode_spaces(self):
        with patch("novelreader.qt_host.sys.platform", "win32"):
            with patch("novelreader.qt_host.subprocess.Popen") as launch:
                self.assertTrue(DesktopWindow.revealSourceFile(self.window, str(self.source)))
        self.assertEqual(launch.call_args.args[0], ["explorer.exe", "/select,", str(self.source.resolve())])
        self.assertNotIn("shell", launch.call_args.kwargs)
        self.source.unlink()
        with patch("novelreader.qt_host.subprocess.Popen") as launch:
            self.assertFalse(DesktopWindow.revealSourceFile(self.window, str(self.source)))
            launch.assert_not_called()
