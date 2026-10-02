"""Coalesce reading progress off the Qt thread, with explicit flush boundaries."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable


class ProgressWriter:
    def __init__(self, save: Callable, interval: float = 5.0):
        self._save = save
        self._interval = interval
        self._condition = threading.Condition()
        self._pending = {}
        self._revision = 0
        self._attempted = 0
        self._force = False
        self._closing = False
        self._error = None
        self._errors = []
        self._thread = threading.Thread(target=self._run, name="reader-progress", daemon=True)
        self._thread.start()

    def submit(self, book_id, position):
        with self._condition:
            if self._closing:
                raise RuntimeError("progress writer is closed")
            self._revision += 1
            self._pending[book_id] = (self._revision, dict(position))
            self._condition.notify_all()

    def flush(self):
        with self._condition:
            target = self._revision
            # Failed writes remain queued for a later retry, including flush.
            if self._pending:
                self._attempted = min(self._attempted, target - 1)
                self._force = True
                self._condition.notify_all()
            self._condition.wait_for(lambda: self._attempted >= target)
            if self._error is not None:
                raise self._error

    def request_flush(self):
        """Start a save now without making a playback/UI command wait for disk."""
        with self._condition:
            self._force = True
            self._condition.notify_all()

    def drain_errors(self):
        with self._condition:
            errors, self._errors = self._errors, []
            return errors

    def close(self):
        try:
            self.flush()
        finally:
            with self._condition:
                self._closing = True
                self._condition.notify_all()
            self._thread.join()

    def _run(self):
        deadline = None
        while True:
            with self._condition:
                while not self._closing:
                    if not self._pending:
                        deadline = None
                        self._condition.wait()
                        continue
                    if deadline is None:
                        deadline = time.monotonic() + self._interval
                    delay = deadline - time.monotonic()
                    if self._force or delay <= 0:
                        break
                    self._condition.wait(delay)
                if self._closing:
                    return
                batch, self._pending = self._pending, {}
                revision = max(item[0] for item in batch.values())
                self._force = False
                deadline = None
            failed = {}
            error = None
            for book_id, item in batch.items():
                try:
                    self._save(book_id, item[1])
                except Exception as exc:
                    failed[book_id] = item
                    error = exc
            with self._condition:
                for book_id, item in failed.items():
                    self._pending.setdefault(book_id, item)
                self._error = error
                if error is not None:
                    self._errors.append(error)
                self._attempted = max(self._attempted, revision)
                self._condition.notify_all()
