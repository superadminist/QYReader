import threading
import unittest

from novelreader.progress_writer import ProgressWriter


class ProgressWriterTests(unittest.TestCase):
    def test_rapid_updates_are_coalesced_and_close_flushes_the_latest(self):
        saved = []
        writer = ProgressWriter(lambda book, position: saved.append((book, position)), interval=60)
        for offset in range(200):
            writer.submit("a", {"charOffset": offset})
        writer.submit("b", {"charOffset": 9})
        self.assertEqual(saved, [])
        writer.close()
        self.assertEqual(saved, [("a", {"charOffset": 199}), ("b", {"charOffset": 9})])

    def test_slow_disk_does_not_block_new_position_updates(self):
        entered = threading.Event()
        release = threading.Event()
        saved = []
        def save(book, position):
            entered.set()
            if not release.wait(2):
                raise TimeoutError("test writer was not released")
            saved.append(position["charOffset"])
        writer = ProgressWriter(save, interval=60)
        self.addCleanup(writer.close)
        self.addCleanup(release.set)
        writer.submit("a", {"charOffset": 1})
        writer.request_flush()
        self.assertTrue(entered.wait(2))
        writer.submit("a", {"charOffset": 2})
        writer.submit("a", {"charOffset": 3})
        release.set()
        writer.flush()
        self.assertEqual(saved, [1, 3])

    def test_failed_flush_is_reported_and_can_retry_without_losing_latest(self):
        saved = []
        failing = [True]
        def save(book, position):
            if failing[0]:
                raise OSError("disk unavailable")
            saved.append(position["charOffset"])
        writer = ProgressWriter(save, interval=60)
        self.addCleanup(writer.close)
        writer.submit("a", {"charOffset": 2})
        with self.assertRaises(OSError):
            writer.flush()
        self.assertIsInstance(writer.drain_errors()[0], OSError)
        writer.submit("a", {"charOffset": 7})
        failing[0] = False
        writer.flush()
        self.assertEqual(saved, [7])

    def test_continuous_updates_do_not_postpone_periodic_saving_forever(self):
        saved = threading.Event()
        writer = ProgressWriter(lambda *args: saved.set(), interval=0.03)
        self.addCleanup(writer.close)
        writer.submit("a", {"charOffset": 1})
        for offset in range(2, 40):
            if saved.wait(0.005):
                break
            writer.submit("a", {"charOffset": offset})
        self.assertTrue(saved.wait(2))


if __name__ == "__main__":
    unittest.main()
