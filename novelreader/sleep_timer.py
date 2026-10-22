"""In-memory sleep plan shared by the coordinator and speech worker."""
import math
import threading
import time


class SleepTimer:
    def __init__(self, clock=time.time):
        self.clock = clock  # wall deadline also expires across system suspend
        self.lock = threading.RLock()
        self.mode = "off"
        self.deadline = None
        self.book_id = ""
        self.chapter = None
        self.book = None
        self.reason = ""
        self.version = 0

    def set(self, mode, minutes=None, book_id="", chapter=None, book=None):
        if mode not in {"off", "minutes", "chapter"}:
            raise ValueError("定时模式无效。")
        if mode == "minutes" and (type(minutes) is not int or not 1 <= minutes <= 720):
            raise ValueError("请输入 1–720 的整数分钟。")
        if mode == "chapter" and book is None:
            raise ValueError("请先打开书籍。")
        with self.lock:
            self.mode = mode
            self.deadline = self.clock() + minutes * 60 if mode == "minutes" else None
            self.book_id, self.chapter, self.book = book_id, chapter, book
            self.reason = "cancelled" if mode == "off" else ""
            self.version += 1
        return self.snapshot()

    def cancel(self, reason):
        with self.lock:
            if self.mode == "off":
                return
            self.mode, self.deadline, self.book = "off", None, None
            self.reason = reason
            self.version += 1

    def expired(self):
        with self.lock:
            return self.mode == "minutes" and self.clock() >= self.deadline

    def chapter_version(self, book, chapter):
        with self.lock:
            return self.version if self.mode == "chapter" and self.book is book and self.chapter == chapter else None

    def snapshot(self):
        with self.lock:
            return {"mode": self.mode, "remainingMs": max(0, math.ceil((self.deadline - self.clock()) * 1000)) if self.deadline is not None else 0,
                    "bookId": self.book_id, "chapterIndex": self.chapter, "endReason": self.reason, "version": self.version}
