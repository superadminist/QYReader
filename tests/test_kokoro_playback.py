"""Kokoro scheduling checks using ready/pending WAV futures, without a model."""
import concurrent.futures
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from novelreader.book_loader import BookContent, Chapter
from novelreader.playback_service import PlaybackService
from novelreader.tts_engine import SpeechController


VOICE = "kokoro:v1.0:zf_xiaobei"


def make_book(*contents):
    return BookContent("调度测试", "", "txt", [
        Chapter(f"第 {index + 1} 章", text) for index, text in enumerate(contents)
    ])


class FakeKokoro:
    def __init__(self, path, pending=False):
        self.path = path
        self.pending = pending
        self.requests = []
        self.futures = {}
        self.requested = threading.Event()
        self.preload = mock.Mock()
        self.cancel_pending = mock.Mock(side_effect=self._cancel)

    def request(self, text, voice, rate, *, priority=0):
        self.requests.append((text, voice, rate, priority))
        if text not in self.futures:
            future = concurrent.futures.Future()
            if not self.pending:
                future.set_result(self.path)
            self.futures[text] = future
        self.requested.set()
        return self.futures[text]

    def _cancel(self):
        for future in self.futures.values():
            if not future.done():
                future.cancel()


class KokoroPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "fixture.wav"
        self.path.write_bytes(b"ready-wav-fixture")

    def controller(self, service, book=None, state="playing"):
        speech = SpeechController()
        speech.set_kokoro_service(service)
        speech.set_voice(VOICE)
        speech._book = book or make_book("当前句。")
        speech._state = state
        speech._gen = 7
        self.addCleanup(speech.shutdown)
        return speech

    def test_prepare_warms_model_without_synthesis_or_audio_events(self):
        service = FakeKokoro(self.path)
        speech = self.controller(service, state="idle")
        with mock.patch.object(speech, "_ensure_thread"):
            speech.prepare(make_book("第一句。"), 0, 0)
        service.preload.assert_called_once_with()
        self.assertEqual(service.requests, [])
        self.assertEqual(speech.drain(), [])
        self.assertTrue(speech.is_stopped())
        self.assertFalse(speech.is_audible())

    def test_unavailable_preload_does_not_prevent_binding_book(self):
        service = FakeKokoro(self.path)
        service.preload.side_effect = RuntimeError("model not ready")
        speech = self.controller(service, state="idle")
        playback = PlaybackService(speech)
        with mock.patch.object(speech, "_ensure_thread"):
            snapshot = playback.bind_session("session", "book", make_book("第一句。"))
        self.assertEqual(snapshot["status"], "idle")
        self.assertEqual(service.requests, [])
        self.assertEqual(speech.drain(), [])

    def test_current_sentence_has_priority_over_bounded_cross_chapter_lookahead(self):
        service = FakeKokoro(self.path)
        book = make_book("当前句。下一句。", "", "第三句。第四句。第五句。")
        speech = self.controller(service, book)
        event = {"type": "sentence_start", "chapter_idx": 0, "char_offset": 0}
        with mock.patch.object(speech, "_speak_edge_play", return_value=True) as play:
            self.assertTrue(speech._speak_kokoro("当前句。", 7, book.chapters[0].content, 4, event, book, 0))
        self.assertEqual(service.requests, [
            ("当前句。", VOICE, 200, 0),
            ("下一句。", VOICE, 200, 10),
            ("第三句。", VOICE, 200, 10),
            ("第四句。", VOICE, 200, 10),
        ])
        play.assert_called_once_with(self.path.read_bytes(), 7, event, backend="kokoro")
        # Synthesis admission does not move the lyric before the player starts.
        self.assertEqual(speech.drain(), [])

    def test_pause_keeps_inflight_sentence_and_resume_uses_its_ready_audio(self):
        service = FakeKokoro(self.path, pending=True)
        speech = self.controller(service, state="paused")
        event = {"type": "sentence_start", "char_offset": 0}
        finished = threading.Event()
        result = []
        with mock.patch.object(speech, "_speak_edge_play", return_value=True) as play:
            def speak():
                try:
                    result.append(speech._speak_kokoro("当前句。", 7, "当前句。", 4, event))
                finally:
                    finished.set()

            worker = threading.Thread(target=speak)
            worker.start()
            try:
                self.assertTrue(service.requested.wait(1))
                # A pending sentence stays quiet even beyond the buffering delay.
                self.assertFalse(finished.wait(.35))
                self.assertEqual(speech.drain(), [])
                service.futures["当前句。"].set_result(self.path)
                self.assertFalse(finished.wait(.05))
                play.assert_not_called()
                self.assertTrue(speech.resume())
                self.assertTrue(finished.wait(1))
                self.assertEqual(result, [True])
                play.assert_called_once_with(self.path.read_bytes(), 7, event, backend="kokoro")
                self.assertEqual(len(service.requests), 1)
                service.cancel_pending.assert_not_called()
            finally:
                speech.stop()
                worker.join(1)
            self.assertFalse(worker.is_alive())

    def test_stop_pending_sentence_returns_without_starting_audio(self):
        service = FakeKokoro(self.path, pending=True)
        speech = self.controller(service)
        result = []
        with mock.patch.object(speech, "_speak_edge_play", return_value=True) as play:
            worker = threading.Thread(target=lambda: result.append(
                speech._speak_kokoro("当前句。", 7, "当前句。", 4, {"type": "sentence_start"})
            ))
            worker.start()
            try:
                self.assertTrue(service.requested.wait(1))
                speech.stop()
            finally:
                worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result, [False])
            play.assert_not_called()
            self.assertFalse(speech.is_audible())

    def test_old_generation_cannot_refill_queue_during_stop(self):
        service = FakeKokoro(self.path)
        speech = self.controller(service)
        cancelling, release = threading.Event(), threading.Event()

        def cancel():
            cancelling.set()
            release.wait(2)

        service.cancel_pending.side_effect = cancel
        stopper = threading.Thread(target=speech.stop)
        result = []
        speaker = threading.Thread(target=lambda: result.append(
            speech._speak_kokoro("当前句。", 7, "当前句。下一句。", 4, {"type": "sentence_start"})
        ))
        with mock.patch.object(speech, "_speak_edge_play", return_value=True) as play:
            stopper.start()
            try:
                self.assertTrue(cancelling.wait(1))
                speaker.start()
                self.assertFalse(service.requested.wait(.05))
            finally:
                release.set()
                stopper.join(1)
                if speaker.ident is not None:
                    speaker.join(1)
            self.assertFalse(stopper.is_alive())
            self.assertFalse(speaker.is_alive())
            self.assertEqual(result, [False])
            self.assertEqual(service.requests, [])
            play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
