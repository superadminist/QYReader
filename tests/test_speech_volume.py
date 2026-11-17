import unittest
from unittest import mock

from novelreader import tts_engine


class ProcessVolumeCacheTest(unittest.TestCase):
    """Enumerating audio sessions costs 250-480 ms on some machines; the resolved
    control must be reused instead of re-enumerating for every volume change."""

    def setUp(self):
        patcher = mock.patch.object(tts_engine, "_HAS_PYCAW", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        reset = mock.patch.object(tts_engine, "_PROCESS_VOLUME_CONTROL", None)
        reset.start()
        self.addCleanup(reset.stop)
        self.control = mock.Mock()
        session = mock.Mock(ProcessId=4242)
        session._ctl.QueryInterface.return_value = self.control
        self.sessions = mock.Mock(return_value=[session])
        sessions_patch = mock.patch.object(tts_engine.AudioUtilities, "GetAllSessions", self.sessions)
        sessions_patch.start()
        self.addCleanup(sessions_patch.stop)
        pid_patch = mock.patch.object(tts_engine.ctypes.windll.kernel32, "GetCurrentProcessId", return_value=4242)
        pid_patch.start()
        self.addCleanup(pid_patch.stop)

    def test_second_call_reuses_the_resolved_control(self):
        self.assertTrue(tts_engine._set_process_volume(40))
        self.assertTrue(tts_engine._set_process_volume(70))
        self.assertEqual(self.sessions.call_count, 1)
        self.assertEqual([call.args[0] for call in self.control.SetMasterVolume.call_args_list], [0.4, 0.7])

    def test_dead_control_is_re_resolved(self):
        self.assertTrue(tts_engine._set_process_volume(40))
        self.control.SetMasterVolume.side_effect = [OSError("session gone"), None]
        self.assertTrue(tts_engine._set_process_volume(60))
        self.assertEqual(self.sessions.call_count, 2)

    def test_missing_session_is_not_cached(self):
        self.sessions.return_value = []
        self.assertFalse(tts_engine._set_process_volume(40))
        self.assertFalse(tts_engine._set_process_volume(40))
        self.assertEqual(self.sessions.call_count, 2)


class SetVolumeIdempotenceTest(unittest.TestCase):
    """set_volume runs on every book open and every reading-settings patch."""

    def setUp(self):
        self.speech = tts_engine.SpeechController()
        self.process = mock.patch.object(tts_engine, "_set_process_volume", return_value=True).start()
        self.addCleanup(mock.patch.stopall)
        self.mci = mock.patch.object(tts_engine, "_mci_set_volume").start()

    def set_state(self, state):
        self.speech._state = state

    def test_same_value_applies_once(self):
        self.set_state("playing")
        self.speech.set_volume(80)
        self.speech.set_volume(80)
        self.speech.set_volume(80)
        self.assertEqual(self.process.call_count, 1)
        self.assertEqual(self.speech.get_volume(), 80)

    def test_changed_value_applies_again(self):
        self.set_state("playing")
        self.speech.set_volume(80)
        self.speech.set_volume(55)
        self.assertEqual([call.args[0] for call in self.process.call_args_list], [80, 55])

    def test_failure_is_retried_on_the_next_call(self):
        self.set_state("playing")
        self.process.return_value = False
        self.mci.side_effect = OSError("no mci alias")
        self.speech.set_volume(80)
        self.speech.set_volume(80)
        self.assertEqual(self.process.call_count, 2)

    def test_mci_fallback_marks_the_value_as_applied(self):
        self.set_state("playing")
        self.process.return_value = False
        self.speech.set_volume(30)
        self.speech.set_volume(30)
        self.assertEqual(self.process.call_count, 1)
        self.assertEqual(self.mci.call_count, 1)


class SetVolumeDeferralTest(unittest.TestCase):
    """Silent state changes must not enumerate audio sessions: that path is the
    book-open path, where a 250-480 ms enumeration blocks the Qt main thread for
    nothing. The value is applied at the next playback start instead."""

    def setUp(self):
        self.speech = tts_engine.SpeechController()
        self.process = mock.patch.object(tts_engine, "_set_process_volume", return_value=True).start()
        self.mci = mock.patch.object(tts_engine, "_mci_set_volume").start()
        self.addCleanup(mock.patch.stopall)

    def test_idle_change_does_not_touch_the_os(self):
        self.speech.set_volume(80)
        self.assertEqual(self.process.call_count, 0)
        self.assertEqual(self.mci.call_count, 0)
        self.assertEqual(self.speech.get_volume(), 80)

    def test_pending_value_lands_once_at_playback_start(self):
        self.speech.set_volume(80)
        self.speech.set_volume(60)
        self.speech.set_volume(40)
        self.assertEqual(self.process.call_count, 0)
        self.assertTrue(self.speech._apply_pending_volume())
        self.assertEqual([call.args[0] for call in self.process.call_args_list], [40])
        self.speech._apply_pending_volume()
        self.assertEqual(self.process.call_count, 1)

    def test_paused_counts_as_audible(self):
        self.speech._state = "paused"
        self.speech.set_volume(70)
        self.assertEqual([call.args[0] for call in self.process.call_args_list], [70])

    def test_next_playback_applies_the_value_changed_after_stop(self):
        self.speech._state = "playing"
        self.speech.set_volume(80)
        self.assertEqual(self.process.call_count, 1)
        self.speech._state = "idle"
        self.speech.set_volume(55)
        self.assertEqual(self.process.call_count, 1)
        self.speech._apply_pending_volume()
        self.assertEqual([call.args[0] for call in self.process.call_args_list], [80, 55])

    def test_deferred_value_keeps_retrying_until_it_lands(self):
        self.process.return_value = False
        self.mci.side_effect = OSError("no mci alias")
        self.speech.set_volume(45)
        self.assertFalse(self.speech._apply_pending_volume())
        self.assertFalse(self.speech._apply_pending_volume())
        self.assertEqual(self.process.call_count, 2)
        self.process.return_value = True
        self.assertTrue(self.speech._apply_pending_volume())
        self.assertTrue(self.speech._apply_pending_volume())
        self.assertEqual(self.process.call_count, 3)


class SapiPlaybackVolumeTest(unittest.TestCase):
    """SAPI playback never goes through _speak_edge_play, so its only chance to
    apply a volume changed while silent is the start of a sentence."""

    def setUp(self):
        self.speech = tts_engine.SpeechController()
        original_pending = self.speech._apply_pending_volume
        self.pending = mock.Mock(side_effect=original_pending)
        self.speech._apply_pending_volume = self.pending
        self.speech._sync_props = mock.Mock()
        calls = {"n": 0}

        def _stop_after_the_sentence_is_queued(gen):
            calls["n"] += 1
            return calls["n"] > 1

        self.speech._should_stop = _stop_after_the_sentence_is_queued
        self.engine = mock.Mock()
        self.speech._engine = self.engine
        self.speech._ensure_engine = mock.Mock()
        self.addCleanup(mock.patch.stopall)

    def test_volume_is_applied_before_the_sentence_is_queued(self):
        self.assertTrue(self.speech._speak_sapi("一句话", 1))
        self.assertEqual(self.pending.call_count, 1)
        self.assertEqual(self.engine.say.call_count, 1)

    def test_apply_happens_before_say(self):
        order = []
        self.pending.side_effect = lambda: order.append("volume") or True
        self.engine.say.side_effect = lambda *a, **kw: order.append("say")
        self.speech._speak_sapi("一句话", 1)
        self.assertEqual(order, ["volume", "say"])


if __name__ == "__main__":
    unittest.main()
