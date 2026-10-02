import unittest

from novelreader.qt_rendering import configure_rendering


class QtRenderingTests(unittest.TestCase):
    def test_explicit_software_mode_disables_both_layers_without_unsafe_flags(self):
        environment = {"QYREADER_RENDER_MODE": "software", "QTWEBENGINE_CHROMIUM_FLAGS": '--remote-allow-origins=* --custom="two words"'}
        self.assertEqual(configure_rendering(environment, "win32"), "software")
        self.assertEqual(environment["QT_QUICK_BACKEND"], "software")
        self.assertEqual(environment["QTWEBENGINE_CHROMIUM_FLAGS"],
                         '--remote-allow-origins=* --custom="two words" --disable-gpu')
        self.assertNotIn("--single-process", environment["QTWEBENGINE_CHROMIUM_FLAGS"])
        self.assertNotIn("--no-sandbox", environment["QTWEBENGINE_CHROMIUM_FLAGS"])
        before = dict(environment)
        configure_rendering(environment, "win32")
        self.assertEqual(environment, before)

    def test_default_windows_uses_raster_composition_without_forcing_chromium_gpu_off(self):
        environment = {"QTWEBENGINE_CHROMIUM_FLAGS": '--custom="two words"'}
        self.assertEqual(configure_rendering(environment, "win32"), "software-composition")
        self.assertEqual(environment["QT_QUICK_BACKEND"], "software")
        self.assertEqual(environment["QTWEBENGINE_CHROMIUM_FLAGS"], '--custom="two words"')
        before = dict(environment)
        configure_rendering(environment, "win32")
        self.assertEqual(environment, before)

    def test_non_windows_explicit_hardware_and_external_backend_preserve_environment(self):
        for platform, environment in (("linux", {}),
                                      ("win32", {"QYREADER_RENDER_MODE": "hardware"}),
                                      ("win32", {"QTWEBENGINE_CHROMIUM_FLAGS": "--custom", "QT_QUICK_BACKEND": "custom"})):
            before = dict(environment)
            self.assertEqual(configure_rendering(environment, platform), "system")
            self.assertEqual(environment, before)

    def test_existing_disable_gpu_is_not_duplicated(self):
        environment = {"QYREADER_RENDER_MODE": "software", "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu --remote-allow-origins=*"}
        configure_rendering(environment, "win32")
        self.assertEqual(environment["QTWEBENGINE_CHROMIUM_FLAGS"], "--disable-gpu --remote-allow-origins=*")


if __name__ == "__main__":
    unittest.main()
