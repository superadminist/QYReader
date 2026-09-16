# -*- coding: utf-8 -*-
"""UI 无关的阅读朗读协调器。

本类不创建 ``SpeechController``，只包装宿主注入的唯一实例。调用方必须只通过
``drain_events`` 消费该实例的事件队列，避免主阅读器、播放条等各自 drain。
"""
from __future__ import annotations

import bisect
import threading
import uuid
from collections import deque

from .textproc import clean_to_orig


SCHEMA_VERSION = 2
PLAYBACK_COMMANDS = frozenset(
    {"play", "pause", "stop", "previousSentence", "nextSentence"}
)


class PlaybackService:
    """把一个阅读会话绑定到宿主提供的唯一 ``SpeechController``。"""

    def __init__(self, speech_controller):
        if speech_controller is None:
            raise ValueError("speech_controller is required")
        self._speech = speech_controller
        self._lock = threading.RLock()
        self._session_id = ""
        self._book_id = ""
        self._book = None
        self._chapter_index = 0
        self._char_offset = 0
        self._status = "idle"
        self._sentence = None
        self._fallback_active = False
        self._active_backend = None
        self._generation = self._speech.generation()
        self._sequence = 0
        self._command_id = ""
        self._terminal_generation = None
        self._pending_events = deque()
        self._deferred_sentence_start = None
        self._sentence_cache = {}
        self._closed = False

    @property
    def speech_controller(self):
        return self._speech

    def session_identity(self):
        with self._lock:
            return {"sessionId": self._session_id, "bookId": self._book_id}

    def bind_session(
        self,
        session_id,
        book_id,
        book,
        chapter_index=0,
        char_offset=0,
    ):
        """绑定唯一当前阅读会话，并使上一朗读 generation 失效。"""
        if not session_id or not book_id or book is None or not book.chapters:
            raise ValueError("reader session, book id and content are required")
        with self._lock:
            self._ensure_open()
            self._generation = self._speech.stop()
            self._session_id = str(session_id)
            self._book_id = str(book_id)
            self._book = book
            self._sentence_cache.clear()
            self._chapter_index, self._char_offset = self._clamp_position(
                chapter_index, char_offset
            )
            self._status = "idle"
            self._sentence = None
            self._fallback_active = False
            self._active_backend = None
            self._command_id = ""
            self._terminal_generation = None
            self._pending_events.clear()
            self._deferred_sentence_start = None
            self._speech.set_book_id(self._book_id)
            self._prepare_position()
            return self.snapshot()

    def set_position(self, chapter_index, char_offset, restart_playing=False):
        """同步阅读位置；显式导航可从新位置继续正在进行的朗读。"""
        with self._lock:
            self._ensure_bound()
            if self._status == "playing" and not restart_playing:
                return self._position()
            self._chapter_index, self._char_offset = self._clamp_position(
                chapter_index, char_offset
            )
            self._sentence = None
            if self._status == "playing":
                self._generation = self._speech.start(
                    self._book, self._chapter_index, self._char_offset
                )
                self._fallback_active = False
                self._active_backend = self._speech.backend()
                self._terminal_generation = None
                self._queue_event("state")
            elif self._status == "paused":
                self._generation = self._speech.stop()
                self._active_backend = None
                self._terminal_generation = None
                self._queue_event("state")
            elif self._status in {"finished", "error"}:
                self._status = "idle"
                self._active_backend = None
                self._fallback_active = False
            if self._status != "playing":
                self._prepare_position()
            return self._position()

    def control(self, command, command_id=None, session_id=None):
        """接受冻结契约中的五种 ReaderPlaybackCommand。"""
        if command not in PLAYBACK_COMMANDS:
            raise ValueError("unsupported playback command")
        command_id = str(command_id or uuid.uuid4().hex)
        with self._lock:
            self._ensure_bound()
            if session_id is not None and str(session_id) != self._session_id:
                raise RuntimeError("reader session is not bound")
            # A sentence can start between the last Qt poll and this Pause
            # click. Keep the last visible lyric while flushing that queued
            # start; publish it only after audio is confirmed on Resume.
            self._flush_speech_events(defer_sentence_start=command == "pause")
            self._command_id = command_id
            if command == "play":
                accepted = self._play()
            elif command == "pause":
                accepted = self._pause()
            elif command == "stop":
                accepted = self._stop()
            else:
                accepted = self._step_sentence(-1 if command == "previousSentence" else 1)
            return {"commandId": command_id, "accepted": bool(accepted)}

    def snapshot(self):
        with self._lock:
            requested = self._speech.backend()
            return {
                "status": self._status,
                "position": self._position(),
                "sentence": dict(self._sentence) if self._sentence else None,
                "requestedBackend": requested,
                "activeBackend": self._active_backend,
                "fallbackActive": self._fallback_active,
            }

    def prepare_current(self):
        """Warm the bound position without creating another playback state."""
        with self._lock:
            if self._book is not None and self._status != "playing":
                self._prepare_position()

    def floating_context(self):
        """Return the adjacent three-sentence view without eagerly scanning text.

        Sentence boundaries are cached per chapter and are only built when the
        floating reader asks for them.  The floating window therefore consumes
        the same position and sentence state as the main reader without adding
        a second event-drain path.
        """
        with self._lock:
            if self._book is None:
                return {
                    "chapterIndex": 0,
                    "chapterTitle": "",
                    "previous": None,
                    "current": None,
                    "next": None,
                }
            chapter_index = self._chapter_index
            if self._sentence is not None and self._status in {"playing", "paused"}:
                # Pending navigation must not replace the last audible lyric,
                # including when the next sentence belongs to another chapter.
                chapter_index = self._sentence["chapterIndex"]
            chapter = self._book.chapters[chapter_index]
            entries = self._sentence_entries(chapter_index)
            if not entries:
                return {
                    "chapterIndex": chapter_index,
                    "chapterTitle": str(chapter.title or f"第 {chapter_index + 1} 章"),
                    "previous": None,
                    "current": None,
                    "next": None,
                }
            anchor_offset = self._char_offset
            if (
                self._sentence is not None
                and self._sentence.get("chapterIndex") == chapter_index
            ):
                # ``sentenceDone`` advances persisted progress before the next
                # audio sentence starts.  Keep the visible lyric anchored to
                # the sentence that is still on screen until ``sentenceStart``
                # selects its successor.
                anchor_offset = self._sentence.get("startOffset", anchor_offset)
            starts = [entry[0] for entry in entries]
            current_index = max(
                0,
                min(len(entries) - 1, bisect.bisect_right(starts, anchor_offset) - 1),
            )
            current = self._sentence_payload(chapter_index, entries[current_index])
            return {
                "chapterIndex": chapter_index,
                "chapterTitle": str(chapter.title or f"第 {chapter_index + 1} 章"),
                "previous": self._relative_sentence(chapter_index, current_index, -1),
                "current": current,
                "next": self._relative_sentence(chapter_index, current_index, 1),
            }

    def drain_events(self):
        """唯一底层 drain 入口，返回冻结的 ReaderPlaybackEvent 快照。"""
        with self._lock:
            self._ensure_open()
            self._flush_speech_events()
            output = list(self._pending_events)
            self._pending_events.clear()
            return output

    def refresh_speech(self, restart_current=False):
        """Apply speech changes to the one active session without a second controller."""
        with self._lock:
            if self._book is None:
                return self.snapshot()
            if not restart_current or self._status not in {"playing", "paused"}:
                self._prepare_position()
                return self.snapshot()
            chapter_index = self._chapter_index
            char_offset = self._char_offset
            if self._sentence is not None:
                chapter_index = int(self._sentence.get("chapterIndex", chapter_index))
                char_offset = int(self._sentence.get("startOffset", char_offset))
            self._chapter_index, self._char_offset = self._clamp_position(
                chapter_index, char_offset
            )
            self._deferred_sentence_start = None
            self._terminal_generation = None
            if self._status == "playing":
                self._generation = self._speech.start(
                    self._book, self._chapter_index, self._char_offset
                )
                self._fallback_active = False
                self._active_backend = self._speech.backend()
            else:
                # A logically paused session must stay paused.  Stop the old
                # audio generation so the next Play starts this sentence with
                # the newly selected voice/rate.
                self._generation = self._speech.stop()
                self._active_backend = None
            self._queue_event("state")
            return self.snapshot()

    def shutdown(self, timeout=2.0):
        """停止唯一控制器；等待有上限，返回工作线程是否已退出。"""
        with self._lock:
            if self._closed:
                return True
            self._closed = True
            self._status = "idle"
            self._sentence = None
            self._active_backend = None
            self._fallback_active = False
        return self._speech.shutdown(timeout)

    def _play(self):
        if self._status == "playing":
            return False
        resumed = False
        if self._status == "paused" and self._speech.resume():
            self._status = "playing"
            resumed = True
        else:
            self._generation = self._speech.start(
                self._book, self._chapter_index, self._char_offset
            )
            self._status = "playing"
        self._terminal_generation = None
        if not resumed:
            self._fallback_active = False
            self._active_backend = self._speech.backend()
        # Do not publish a deferred audio-start on the UI's Resume click.
        # Edge/MCI confirms the actual resume from its worker thread; SAPI
        # announces the restarted utterance with a fresh sentence_start.
        if self._active_backend != "edge":
            self._deferred_sentence_start = None
        self._queue_event("state")
        return True

    def _prepare_position(self):
        prepare = getattr(self._speech, "prepare", None)
        if callable(prepare):
            prepare(self._book, self._chapter_index, self._char_offset)

    def _pause(self):
        if self._status != "playing" or not self._speech.pause():
            return False
        self._status = "paused"
        self._queue_event("state")
        return True

    def _stop(self):
        if self._status not in {"playing", "paused", "error"} and not self._speech.is_active():
            return False
        self._generation = self._speech.stop()
        self._terminal_generation = None
        self._status = "idle"
        self._sentence = None
        self._fallback_active = False
        self._active_backend = None
        self._deferred_sentence_start = None
        self._queue_event("state")
        return True

    def _step_sentence(self, delta):
        target = self._adjacent_position(delta)
        if target is None:
            return False
        chapter_index, char_offset, _sentence = target
        active = self._speech.is_active()
        self._chapter_index = chapter_index
        self._char_offset = char_offset
        if not active:
            self._sentence = None
        self._deferred_sentence_start = None
        self._fallback_active = False
        self._terminal_generation = None
        if active:
            self._generation = self._speech.start(
                self._book, chapter_index, char_offset
            )
            self._status = "playing"
            self._active_backend = self._speech.backend()
        else:
            self._status = "idle"
            self._active_backend = None
        self._queue_event("state")
        return True

    def _consume_raw_event(self, raw, defer_sentence_start=False):
        generation = raw.get("generation")
        if generation != self._generation:
            return None
        event_type = raw.get("type")
        if event_type == "sentence_start":
            if self._status == "paused" or (defer_sentence_start and self._status == "playing"):
                # A start event can race with the 25 ms Qt polling boundary
                # or be queued just before Pause. Keep the last visible lyric
                # until resumed audio confirms the next sentence.
                self._deferred_sentence_start = dict(raw)
                return None
            chapter_index = int(raw["chapter_idx"])
            start = int(raw["char_offset"])
            end = int(raw["char_end"])
            self._chapter_index, self._char_offset = self._clamp_position(
                chapter_index, start
            )
            self._sentence = {
                "chapterIndex": self._chapter_index,
                "startOffset": self._char_offset,
                "endOffset": max(self._char_offset, end),
                "text": str(raw.get("text", "")),
            }
            self._status = "playing" if self._speech.is_playing() else self._status
            if not self._fallback_active:
                self._active_backend = self._speech.backend()
            return self._event("sentenceStart")
        if event_type == "sentence_resume":
            if defer_sentence_start:
                return None
            deferred = self._deferred_sentence_start
            self._deferred_sentence_start = None
            if deferred is not None and self._status == "playing":
                return self._consume_raw_event(deferred)
            return None
        if event_type == "sentence_done":
            self._chapter_index, self._char_offset = self._clamp_position(
                raw["chapter_idx"], raw["char_offset"]
            )
            return self._event("sentenceDone")
        if event_type == "buffering":
            return self._event("buffering")
        if event_type == "edge_recovered":
            self._fallback_active = False
            self._active_backend = str(raw.get("backend") or "edge")
            return self._event("recovered")
        if event_type == "chapter":
            chapter_index = int(raw.get("chapter_idx", 0))
            if 0 <= chapter_index < len(self._book.chapters):
                self._chapter_index = chapter_index
                self._char_offset = 0
                self._sentence = None
                return self._event("state")
            return None
        if event_type == "finished":
            self._chapter_index = len(self._book.chapters) - 1
            self._char_offset = len(self._book.chapters[self._chapter_index].content)
            self._status = "finished"
            self._sentence = None
            self._fallback_active = False
            self._active_backend = None
            self._terminal_generation = generation
            return self._event("finished")
        if event_type == "error":
            error = {
                "code": str(raw.get("code") or "TTS_FAILED"),
                "message": str(raw.get("message") or "朗读出错"),
                "retryable": bool(raw.get("retryable", True)),
            }
            fallback_backend = raw.get("fallback_backend")
            if fallback_backend:
                self._fallback_active = True
                self._active_backend = str(fallback_backend)
                return self._event("fallback", error)
            self._status = "error"
            self._active_backend = None
            self._terminal_generation = generation
            return self._event("error", error)
        if event_type == "stopped":
            if self._terminal_generation == generation:
                return None
            self._status = "idle"
            self._sentence = None
            self._fallback_active = False
            self._active_backend = None
            return self._event("state")
        return None

    def _flush_speech_events(self, defer_sentence_start=False):
        for raw in self._speech.drain():
            event = self._consume_raw_event(raw, defer_sentence_start)
            if event is not None:
                self._pending_events.append(event)

    def _queue_event(self, reason, error=None):
        self._pending_events.append(self._event(reason, error))

    def _event(self, reason, error=None):
        self._sequence += 1
        return {
            "schemaVersion": SCHEMA_VERSION,
            "sessionId": self._session_id,
            "bookId": self._book_id,
            "sequence": self._sequence,
            "commandId": self._command_id,
            "reason": reason,
            "playback": self.snapshot(),
            "error": error,
        }

    def _position(self):
        if self._book is None:
            return {"chapterIndex": 0, "charOffset": 0, "progressPercent": 0.0}
        absolute = self._book.cum[self._chapter_index] + self._char_offset
        percent = absolute / self._book.total_chars * 100 if self._book.total_chars else 0.0
        return {
            "chapterIndex": self._chapter_index,
            "charOffset": self._char_offset,
            "progressPercent": round(max(0.0, min(100.0, percent)), 3),
        }

    def _clamp_position(self, chapter_index, char_offset):
        chapter_index = max(0, min(int(chapter_index), len(self._book.chapters) - 1))
        content = self._book.chapters[chapter_index].content
        char_offset = max(0, min(int(char_offset), len(content)))
        return chapter_index, char_offset

    def _sentence_entries(self, chapter_index):
        cached = self._sentence_cache.get(chapter_index)
        if cached is not None:
            return cached
        chapter = self._book.chapters[chapter_index]
        clean_text, cmap = chapter.tts_content()
        entries = []
        clean_offset = 0
        while clean_offset < len(clean_text):
            text, next_offset, relative_start = self._speech._next_chunk(
                clean_text, clean_offset
            )
            if not text or next_offset <= clean_offset:
                break
            start = clean_to_orig(
                cmap, clean_offset + relative_start, len(chapter.content)
            )
            end = clean_to_orig(cmap, next_offset, len(chapter.content))
            entries.append((start, max(start, end), text))
            clean_offset = next_offset
        self._sentence_cache[chapter_index] = entries
        return entries

    def _adjacent_position(self, delta):
        entries = self._sentence_entries(self._chapter_index)
        if not entries:
            return None
        starts = [entry[0] for entry in entries]
        current = max(0, bisect.bisect_right(starts, self._char_offset) - 1)
        target = current + delta
        chapter_index = self._chapter_index
        if target < 0:
            if chapter_index == 0:
                return None
            chapter_index -= 1
            entries = self._sentence_entries(chapter_index)
            if not entries:
                return None
            target = len(entries) - 1
        elif target >= len(entries):
            if chapter_index >= len(self._book.chapters) - 1:
                return None
            chapter_index += 1
            entries = self._sentence_entries(chapter_index)
            if not entries:
                return None
            target = 0
        start, end, text = entries[target]
        sentence = {
            "chapterIndex": chapter_index,
            "startOffset": start,
            "endOffset": end,
            "text": text,
        }
        return chapter_index, start, sentence

    @staticmethod
    def _sentence_payload(chapter_index, entry):
        start, end, text = entry
        return {
            "chapterIndex": chapter_index,
            "startOffset": start,
            "endOffset": end,
            "text": text,
        }

    def _relative_sentence(self, chapter_index, sentence_index, delta):
        target_chapter = chapter_index
        target_index = sentence_index + delta
        entries = self._sentence_entries(target_chapter)
        if target_index < 0:
            while True:
                target_chapter -= 1
                if target_chapter < 0:
                    return None
                entries = self._sentence_entries(target_chapter)
                if entries:
                    break
            target_index = len(entries) - 1
        elif target_index >= len(entries):
            while True:
                target_chapter += 1
                if target_chapter >= len(self._book.chapters):
                    return None
                entries = self._sentence_entries(target_chapter)
                if entries:
                    break
            target_index = 0
        return self._sentence_payload(target_chapter, entries[target_index])

    def _ensure_bound(self):
        self._ensure_open()
        if self._book is None or not self._session_id:
            raise RuntimeError("reader session is not bound")

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError("playback service is closed")
