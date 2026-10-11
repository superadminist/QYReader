"""One local clock for both surfaces; committed intervals survive a crash."""
from __future__ import annotations

import datetime as dt
import sqlite3
import time
from pathlib import Path


class ActivityService:
    IDLE_SECONDS = 300

    def __init__(self, path, monotonic=time.monotonic, wall=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS daily (date TEXT PRIMARY KEY, reading REAL NOT NULL, listening REAL NOT NULL, overlap REAL NOT NULL)")
        self.db.commit()
        self.clock, self.wall = monotonic, wall
        self.last, self.last_wall = self.clock(), self.wall()
        self.last_commit = self.last
        self.activity = {}
        self.flags = (False, False)
        self.pending = {}

    def report(self, surface, session_id, visible, input_sequence):
        if surface not in {"main", "floating"} or not isinstance(input_sequence, int) or input_sequence < 0:
            return
        now = self.clock()
        previous = self.activity.get(surface)
        active_at = now if previous is None or previous[0] != session_id or previous[3] != input_sequence else previous[2]
        self.activity[surface] = (str(session_id), bool(visible), active_at, input_sequence)

    def record_audio(self, active, at):
        now = self.clock()
        at = max(self.last, min(now, float(at)))
        duration = at - self.last
        if duration <= 15:
            self._add(self.last_wall, duration, *self.flags)
        self.last_wall += duration
        self.last = at
        self.flags = (self.flags[0], bool(active))
        self.flush()

    def tick(self, foreground_surface=None, speaking=False, purpose="book", book_id=""):
        now, wall = self.clock(), self.wall()
        duration = max(0, now - self.last)
        # Detect suspend / clock jumps. Never charge the time while the process slept.
        if duration <= 15 and abs((wall - self.last_wall) - duration) < 2:
            self._add(self.last_wall, duration, *self.flags)
        self.last, self.last_wall = now, wall
        activity = self.activity.get(foreground_surface)
        reading = bool(purpose == "book" and activity and activity[0] and activity[1] and now - activity[2] < self.IDLE_SECONDS)
        listening = self.flags[1] if speaking is None else bool(speaking and purpose == "book" and book_id)
        new_flags = (reading, listening)
        changed = new_flags != self.flags
        self.flags = new_flags
        if changed or now - self.last_commit >= 5:
            self.flush()
        return reading

    def _add(self, start, seconds, reading, listening):
        if not reading and not listening:
            return
        end = start + seconds
        while start < end:
            local = dt.datetime.fromtimestamp(start)
            tomorrow = (local.date() + dt.timedelta(days=1))
            boundary = dt.datetime.combine(tomorrow, dt.time()).timestamp()
            stop = min(boundary, end)
            values = self.pending.setdefault(local.date().isoformat(), [0., 0., 0.])
            millis = (stop - start) * 1000
            values[0] += millis if reading else 0
            values[1] += millis if listening else 0
            values[2] += millis if reading and listening else 0
            start = stop

    def flush(self):
        if self.pending:
            with self.db:
                for date, values in self.pending.items():
                    self.db.execute("INSERT INTO daily VALUES(?,?,?,?) ON CONFLICT(date) DO UPDATE SET reading=reading+excluded.reading,listening=listening+excluded.listening,overlap=overlap+excluded.overlap", (date, *values))
            self.pending.clear()
        self.last_commit = self.clock()

    @staticmethod
    def _summary(reading, listening, overlap):
        return {"readingMs": round(reading), "listeningMs": round(listening), "overlapMs": round(overlap), "totalMs": round(reading + listening - overlap)}

    def state(self):
        rows = {date: list(values) for date, *values in self.db.execute("SELECT date,reading,listening,overlap FROM daily")}
        for date, values in self.pending.items():
            previous = rows.setdefault(date, [0., 0., 0.])
            for i, value in enumerate(values):
                previous[i] += value
        total = [sum(values[i] for values in rows.values()) for i in range(3)]
        return {"today": self._summary(*rows.get(dt.datetime.fromtimestamp(self.wall()).date().isoformat(), [0, 0, 0])),
                "total": self._summary(*total), "days": [{"date": date, **self._summary(*values)} for date, values in sorted(rows.items())]}

    def close(self):
        self.tick()
        self.flush()
        self.db.close()
