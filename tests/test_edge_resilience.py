"""Offline regression coverage for Edge admission, recovery and batch playback."""
import threading
import types
import unittest
from unittest import mock

from novelreader import tts_engine as tts
from tests.test_playback_service import make_book


class EdgeResilienceTests(unittest.TestCase):
    def setUp(self):
        self.governor = tts._EdgeRequestGovernor(min_interval=0)
        patcher = mock.patch.object(tts, "_EDGE_REQUEST_GOVERNOR", self.governor)
        patcher.start()
        self.addCleanup(patcher.stop)
        # A forgotten network stub must fail locally instead of calling Edge.
        patcher = mock.patch.object(tts, "edge_tts", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def controller(self):
        controller = tts.SpeechController()
        controller.set_voice("zh-CN-XiaoxiaoNeural")
        self.addCleanup(controller.shutdown)
        return controller

    def test_cooldown_fails_fast_without_extending_it_and_expires(self):
        with mock.patch.object(tts.time, "monotonic", return_value=100), mock.patch.object(tts.random, "uniform", return_value=0):
            self.governor.report_failure({"category": "rate_limited", "retryAfterSeconds": 600})
            until = self.governor._backoff_until
            with mock.patch.object(tts, "synth_audio") as raw:
                for _ in range(3):
                    with self.assertRaises(tts.EdgeSchedulingError) as raised:
                        tts._synth_audio_governed("test", "voice")
                    self.assertEqual(raised.exception.details["category"], "cooldown")
                raw.assert_not_called()
            self.assertEqual(until, 700)
            self.assertEqual(self.governor._backoff_until, until)
            self.assertEqual(self.governor._failure_streak, 1)
            self.assertEqual(self.governor._waiters, [])
        with mock.patch.object(tts.time, "monotonic", return_value=701), mock.patch.object(tts, "synth_audio", return_value=b"audio") as raw:
            self.assertEqual(tts._synth_audio_governed("test", "voice"), b"audio")
            raw.assert_called_once()

    def test_queue_timeout_does_not_become_a_network_failure(self):
        self.governor._busy = True
        with mock.patch.object(tts, "synth_audio") as raw:
            with self.assertRaises(tts.EdgeSchedulingError) as raised:
                tts._synth_audio_governed("test", "voice", timeout=0.01)
            raw.assert_not_called()
        self.assertEqual(raised.exception.details["category"], "queue_timeout")
        self.assertEqual(self.governor._failure_streak, 0)
        self.assertEqual(self.governor._backoff_until, 0)
        self.assertEqual(self.governor._waiters, [])

    def test_retry_after_http_date_and_server_delay_are_respected(self):
        error = RuntimeError()
        error.status = 429
        error.headers = {"Retry-After": "Fri, 02 Oct 2026 01:10:00 GMT"}
        with mock.patch.object(tts, "datetime") as clock:
            from datetime import datetime, timezone
            clock.now.return_value = datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)
            details = tts._edge_exception_details(error)
        self.assertEqual(details["retryAfterSeconds"], 600)
        with mock.patch.object(tts.random, "uniform", return_value=0):
            self.assertEqual(self.governor.report_failure(details), 600)
            self.assertEqual(self.governor.report_failure({"category": "access_denied"}), 300)

    def test_connection_failure_cools_down_without_immediate_retry(self):
        controller = self.controller()
        with mock.patch.object(tts, "synth_audio", side_effect=ConnectionError) as raw:
            with self.assertRaises(tts.EdgeSynthesisError):
                controller._edge_synthesize("test")
        raw.assert_called_once()
        self.assertGreater(self.governor.cooldown_remaining(), 0)

    def test_recovery_is_one_uncached_request_with_recovery_priority(self):
        controller = self.controller()
        controller._remember_edge_audio(("synthesis", controller._edge_voice, 200, "test"), b"cached")
        error = tts.EdgeSynthesisError({"category": "unknown"})
        with mock.patch.object(tts, "_synth_audio_governed", side_effect=error) as request:
            with controller._edge_request_context("recovery"):
                with self.assertRaises(tts.EdgeSynthesisError):
                    controller._edge_synthesize("test")
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["purpose"], "recovery")

    def test_recovery_scheduling_retains_backoff_after_brief_success(self):
        controller = self.controller()
        with mock.patch.object(tts.time, "monotonic", return_value=100), mock.patch.object(tts.random, "uniform", return_value=0):
            controller._schedule_edge_recovery_locked({"category": "access_denied"})
            self.assertEqual(controller._edge_recovery_due_at, 400)
            controller._edge_recovered_at = 90
            controller._schedule_edge_recovery_locked({"category": "timeout"})
            self.assertEqual(controller._edge_recovery_due_at, 700)
            controller._schedule_edge_recovery_locked({"category": "rate_limited", "retryAfterSeconds": 1800})
            self.assertEqual(controller._edge_recovery_due_at, 1900)

    def test_failed_probes_back_off_and_success_does_not_reset_the_interval(self):
        controller = self.controller()
        controller._gen = 5
        controller._edge_session_fallback = True
        with mock.patch.object(tts.time, "monotonic", return_value=100), mock.patch.object(tts.random, "uniform", return_value=0):
            controller._schedule_edge_recovery_locked()
            for delay in (60, 120):
                ready = threading.Event()
                ready.set()
                controller._edge_recovery_event = ready
                controller._edge_recovery_key = (5, controller._edge_recovery_token, controller._edge_voice, 200)
                controller._edge_recovery_audio = None
                controller._edge_recovery_details = {"category": "timeout"}
                self.assertFalse(controller._consume_edge_recovery_result(5))
                self.assertEqual(controller._edge_recovery_due_at, 100 + delay)
            ready = threading.Event()
            ready.set()
            controller._edge_recovery_event = ready
            controller._edge_recovery_key = (5, controller._edge_recovery_token, controller._edge_voice, 200)
            controller._edge_recovery_audio = b"audio"
            self.assertTrue(controller._consume_edge_recovery_result(5))
            self.assertEqual(controller._edge_recovery_backoff, 120)
            controller._schedule_edge_recovery_locked({"category": "timeout"})
            self.assertEqual(controller._edge_recovery_due_at, 340)

    def test_probe_waits_for_governor_and_keeps_one_inflight_request(self):
        controller = self.controller()
        controller._book = make_book()
        controller._gen = 8
        controller._state = "playing"
        controller._edge_session_fallback = True
        controller._edge_recovery_due_at = 1
        release = threading.Event()
        started = threading.Event()

        def synthesize(text):
            started.set()
            release.wait(1)
            return b"audio"

        controller._edge_synthesize = mock.Mock(side_effect=synthesize)
        with mock.patch.object(tts.time, "monotonic", return_value=100):
            self.governor._backoff_until = 200
            self.assertFalse(controller._ensure_edge_recovery_probe("test", 8))
            controller._edge_synthesize.assert_not_called()
            self.assertEqual(controller._edge_recovery_due_at, 200)
            self.governor._backoff_until = 0
            controller._edge_recovery_due_at = 1
            self.assertTrue(controller._ensure_edge_recovery_probe("test", 8))
        try:
            self.assertTrue(started.wait(1))
            self.assertFalse(controller._ensure_edge_recovery_probe("test", 8))
            ready = controller._edge_recovery_event
        finally:
            release.set()
        self.assertTrue(ready.wait(1))
        controller._edge_synthesize.assert_called_once()

    @staticmethod
    def metadata(texts):
        return [{"text": text, "offset": i * 10000000, "duration": 5000000} for i, text in enumerate(texts)]

    def test_batch_mapping_keeps_sentence_ranges_and_rejects_incomplete_words(self):
        segments = tts._edge_batch_ranges(["第一句。", "第二句！", "第三句？"], b"mp3", self.metadata(["第一句", "第二句", "第三句"]))
        self.assertEqual([(s.start_ms, s.end_ms) for s in segments], [(0, 1000), (1000, 2000), (2000, None)])
        self.assertTrue(all(s == b"mp3" for s in segments))
        for metadata in ([], self.metadata(["错误", "第二句", "第三句"]), self.metadata(["第一句第二句", "第三句"])):
            with self.assertRaises(tts.EdgeBatchMappingError):
                tts._edge_batch_ranges(["第一句。", "第二句！", "第三句？"], b"mp3", metadata)

    def test_three_prefetched_sentences_use_one_request_and_reuse_cached_ranges(self):
        controller = self.controller()
        requests = []

        def raw(text, voice, rate=200, timeout=None, boundaries=None):
            requests.append(text)
            boundaries.extend(self.metadata(text.split("\n")))
            return b"combined-mp3"

        content = "第一句。\n 第二句！ 第三句？"
        with mock.patch.object(tts, "synth_audio", side_effect=raw):
            prefetch = controller._new_edge_prefetch(content, 0, 0)
            try:
                for off, text in ((0, "第一句。"), (6, "第二句！"), (11, "第三句？")):
                    ready, segment = prefetch.get_expected(off, text, timeout=1)
                    self.assertTrue(ready)
                    self.assertIsInstance(segment, tts._EdgeSentenceAudio)
                self.assertEqual(len(requests), 1)
                cached = controller._edge_synthesize("第二句！")
                self.assertEqual((cached.start_ms, cached.end_ms), (1000, 2000))
                self.assertEqual(len(requests), 1)
            finally:
                prefetch.close()
            # Restarting prefetch also reuses audio for sentences never consumed.
            prefetch = controller._new_edge_prefetch(content, 0, 0)
            try:
                self.assertTrue(prefetch.get_expected(0, "第一句。", timeout=1)[0])
                self.assertEqual(len(requests), 1)
            finally:
                prefetch.close()

    def test_batch_stream_requests_word_metadata(self):
        options = []

        class Communicate:
            def __init__(self, text, voice, **kwargs):
                options.append(kwargs)

            async def stream(self):
                yield {"type": "audio", "data": b"mp3"}
                yield {"type": "WordBoundary", "text": "first", "offset": 0, "duration": 1}
                yield {"type": "WordBoundary", "text": "second", "offset": 10000000, "duration": 1}

        controller = self.controller()
        with mock.patch.object(tts, "edge_tts", types.SimpleNamespace(Communicate=Communicate)):
            segments = controller._edge_synthesize_batch(["first.", "second!"])
        self.assertEqual(options[0]["boundary"], "WordBoundary")
        self.assertEqual(segments[0].end_ms, 1000)

    def test_missing_metadata_disables_batching_and_falls_back_to_single_requests(self):
        controller = self.controller()
        with mock.patch.object(tts, "synth_audio", return_value=b"audio") as raw:
            self.assertEqual(controller._edge_synthesize_batch(["first.", "second!"]), [b"audio", b"audio"])
            self.assertEqual(raw.call_count, 3)
            self.assertEqual(controller._edge_synthesize_batch(["third.", "fourth!"]), [b"audio", b"audio"])
            self.assertEqual(raw.call_count, 5)

    def test_cached_sentences_are_excluded_from_batch_request(self):
        controller = self.controller()
        controller._remember_edge_audio(("synthesis", controller._edge_voice, 200, "第二句！"), b"cached")
        batches = []
        controller._edge_synthesize_batch = lambda texts: batches.append(texts) or [b"new"] * len(texts)
        prefetch = controller._new_edge_prefetch("第一句。第二句！第三句？", 0, 0)
        try:
            self.assertEqual(prefetch.get_expected(4, "第二句！", timeout=1), (True, b"cached"))
            self.assertEqual(batches, [["第一句。", "第三句？"]])
        finally:
            prefetch.close()

    def test_prefetch_cache_failure_is_ordered_and_does_not_discard_a_cached_sentence(self):
        def fail(texts):
            raise tts.EdgeSynthesisError({"category": "rate_limited", "statusCode": 429})

        prefetch = tts._EdgePrefetch(lambda text: b"single", "第一句。第二句！第三句？", 0,
                                     batch_fn=fail, cached_fn=lambda off, text: b"cached" if off == 0 else None)
        try:
            self.assertEqual(prefetch.get_expected(0, "第一句。", timeout=1), (True, b"cached"))
            self.assertEqual(prefetch.get_expected(4, "第二句！", timeout=1), (True, None))
            self.assertEqual(prefetch.failure_for(4)["statusCode"], 429)
        finally:
            prefetch.close()

    def test_disk_cache_uses_original_offsets_without_opening_a_network_request(self):
        controller = self.controller()
        book = make_book("第一句。\n 第二句！", "")
        with mock.patch.object(controller, "_cached_audio", return_value=b"disk") as disk, mock.patch.object(tts, "synth_audio") as raw:
            prefetch = controller._new_edge_prefetch(book.chapters[0].tts_content()[0], 4, 0, book=book)
            try:
                self.assertEqual(prefetch.get_expected(4, "第二句！", timeout=1), (True, b"disk"))
                self.assertEqual(disk.call_args.args, (0, 6))
                raw.assert_not_called()
            finally:
                prefetch.close()

    def test_batch_stays_bounded_and_preserves_end_of_chapter(self):
        batches = []
        texts = ["甲" * 120 + "。", "乙" * 120 + "。", "丙" * 120 + "。"]
        prefetch = tts._EdgePrefetch(lambda text: b"single", "".join(texts), 0,
                                     batch_fn=lambda texts: batches.append(texts) or [b"batch"] * len(texts))
        try:
            for off, text in zip((0, 121, 242), texts):
                self.assertTrue(prefetch.get_expected(off, text, timeout=1)[0])
            self.assertTrue(all(sum(map(len, batch)) <= 320 for batch in batches))
            self.assertEqual(batches, [texts[:2]])
            self.assertEqual(tts.SpeechController._next_chunk("end", 3), ("", 3, 0))
        finally:
            prefetch.close()

    def test_batch_playback_and_resume_keep_the_sentence_end_limit(self):
        controller = self.controller()
        controller._book = make_book()
        controller._state = "paused"
        controller._gen = 9
        ranges = []

        def resume_during_wait(*args):
            controller._state = "playing"
            controller._resume_counter += 1

        with (
            mock.patch.object(tts, "_mci_open"), mock.patch.object(tts, "_mci_close"),
            mock.patch.object(tts, "_mci_stop"), mock.patch.object(tts, "_mci_pause"),
            mock.patch.object(tts, "_mci_set_volume"), mock.patch.object(tts, "_set_process_volume"),
            mock.patch.object(tts, "_mci_playing", side_effect=[True, False]),
            mock.patch.object(tts, "_mci_play_range", side_effect=lambda a, b: ranges.append((a, b))),
            mock.patch.object(controller._cv, "wait", side_effect=resume_during_wait),
        ):
            self.assertTrue(controller._speak_edge_play(tts._EdgeSentenceAudio(b"mp3", 1000, 2000), 9,
                                                       {"type": "sentence_start", "text": "second"}))
        self.assertEqual(ranges, [(1000, 2000), (None, 2000)])
        self.assertEqual([e["type"] for e in controller.drain()], ["sentence_start", "sentence_resume"])

    def test_mci_range_command_uses_milliseconds_and_keeps_resume_position(self):
        with mock.patch.object(tts, "_mci_send", return_value=(0, "")) as send:
            tts._mci_play_range(1000, 2000)
            tts._mci_play_range(None, 2000)
        commands = [call.args[0] for call in send.call_args_list]
        self.assertIn("play dd_tts_player from 1000 to 2000", commands)
        self.assertEqual(commands[-1], "play dd_tts_player to 2000")


if __name__ == "__main__":
    unittest.main()
