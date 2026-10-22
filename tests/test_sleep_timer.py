import unittest
from unittest.mock import patch
from novelreader.playback_service import PlaybackService
from novelreader.tts_engine import SpeechController
from test_playback_service import FakeSpeechController, make_book

class SleepTimerTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.speech = FakeSpeechController()
        self.service = PlaybackService(self.speech, clock=lambda: self.now)
        self.book = make_book()
        self.service.bind_session("s", "b", self.book)

    def test_deadline_pause_replace_resume_and_stale_events(self):
        for backend in ("sapi", "edge", "kokoro"):
            self.speech._backend = backend
            self.service.control("play")
            self.service.set_sleep_timer("minutes", 15)
            self.service.control("pause")
            self.now += 800
            self.assertFalse(self.service.tick_sleep_timer())
            self.service.set_sleep_timer("minutes", 1)
            gen = self.speech.generation()
            self.now += 65
            self.assertFalse(self.service.control("play")["accepted"])
            self.assertEqual(self.service.snapshot()["status"], "idle")
            self.speech.emit({"type": "sentence_start", "generation": gen, "chapter_idx": 0, "char_offset": 4, "char_end": 8})
            self.service.drain_events()
            self.assertEqual(self.service.snapshot()["position"]["charOffset"], 0)
            self.assertEqual(self.service.snapshot()["sleepTimer"]["endReason"], "expired")

    def test_validation_cancel_and_navigation(self):
        for invalid in (0, 721, 1.5, True, "15", None):
            with self.assertRaises(ValueError): self.service.set_sleep_timer("minutes", invalid)
        for valid in (15, 30, 60, 720):
            self.assertEqual(self.service.set_sleep_timer("minutes", valid)["remainingMs"], valid * 60000)
        self.service.set_sleep_timer("chapter")
        self.service.set_position(0, 4)
        self.assertEqual(self.service.snapshot()["sleepTimer"]["mode"], "chapter")
        self.service.set_position(1, 0)
        self.assertEqual(self.service.snapshot()["sleepTimer"]["endReason"], "chapterChanged")
        self.service.set_sleep_timer("minutes", 15)
        self.service.bind_session("s2", "b2", self.book)
        self.assertEqual(self.service.snapshot()["sleepTimer"]["mode"], "minutes")
        self.service.control("stop")
        self.assertEqual(self.service.snapshot()["sleepTimer"]["mode"], "off")

    def test_worker_blocks_before_next_chapter_for_every_backend(self):
        for backend in ("sapi", "edge", "kokoro"):
            for ci, text in ((0, "第一句。"), (0, "   "), (1, "最后一句。")):
                book = make_book(first=text) if ci == 0 else make_book(second=text)
                speech = SpeechController()
                service = PlaybackService(speech)
                with patch.object(speech, "prepare"):
                    service.bind_session("s", "b", book, ci, 0)
                service.set_sleep_timer("chapter")
                speech._backend = backend
                speech._book, speech._state = book, "playing"
                service._status = "playing"
                speech._sentence_gap = 0
                spoken = []
                def speak(*args):
                    spoken.append(args[0]); return True
                with patch.object(speech, "_speak_sapi", side_effect=speak), patch.object(speech, "_speak_edge", side_effect=speak), patch.object(speech, "_speak_kokoro", side_effect=speak):
                    speech._run_session(book, ci, 0, speech.generation())
                events = service.drain_events()
                self.assertEqual(len(spoken), 0 if not text.strip() else 1)
                self.assertIn("sleepStopped", [e["reason"] for e in events])
                self.assertEqual(service.snapshot()["position"]["chapterIndex"], ci)
                self.assertEqual(service.snapshot()["position"]["charOffset"], len(book.chapters[ci].content))
                self.assertEqual(service.snapshot()["status"], "idle")

if __name__ == "__main__": unittest.main()
