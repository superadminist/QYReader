import unittest

from novelreader.qt_rendering import configure_rendering


class QtRenderingTests(unittest.TestCase):
    def test_windows_disables_both_gpu_composition_layers_without_unsafe_flags(self):
        environment = {"QTWEBENGINE_CHROMIUM_FLAGS": '--remote-allow-origins=* --custom="two words"'}
        self.assertEqual(configure_rendering(environment, "win32"), "software")
        self.assertEqual(environment["QT_QUICK_BACKEND"], "software")
        self.assertEqual(environment["QTWEBENGINE_CHROMIUM_FLAGS"],
                         '--remote-allow-origins=* --custom="two words" --disable-gpu')
        self.assertNotIn("--single-process", environment["QTWEBENGINE_CHROMIUM_FLAGS"])
        self.assertNotIn("--no-sandbox", environment["QTWEBENGINE_CHROMIUM_FLAGS"])
        before = dict(environment)
        configure_rendering(environment, "win32")
        self.assertEqual(environment, before)

    def test_other_platforms_and_diagnostic_hardware_mode_preserve_environment(self):
        for platform, environment in (("linux", {}), ("win32", {"QYREADER_RENDER_MODE": "hardware"})):
            before = dict(environment)
            self.assertEqual(configure_rendering(environment, platform), "system")
            self.assertEqual(environment, before)

    def test_existing_disable_gpu_is_not_duplicated(self):
        environment = {"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu --remote-allow-origins=*"}
        configure_rendering(environment, "win32")
        self.assertEqual(environment["QTWEBENGINE_CHROMIUM_FLAGS"], "--disable-gpu --remote-allow-origins=*")


if __name__ == "__main__":
    unittest.main()
