# -*- coding: utf-8 -*-
"""TTS 朗读引擎（v3）。

v3 新增双后端：
- backend="sapi"：Windows 系统语音（pyttsx3/SAPI5），离线可用，音质一般；
- backend="edge"：Edge 神经语音（edge-tts，免费、无需密钥、音质接近豆包级），
  朗读时需联网。通过 set_voice 传入的语音 ID 自动识别后端。

架构（v2 起保持不变）：
- 全程只有一个常驻工作线程，语音引擎/音频只在该线程内使用；
- GUI 线程只通过状态标志（idle/playing/paused）+ 条件变量通信；
- 朗读按句推进；暂停/停止由工作线程内打断；
- edge 后端用「预取下一句」隐藏网络生成延迟，句间不卡顿；
- edge 生成失败自动回退到系统语音。
"""
import os
import json

import asyncio
from collections import OrderedDict
from contextlib import contextmanager
import logging
from logging.handlers import RotatingFileHandler
import queue
import random
import re
import tempfile
import threading
import time

try:
    import pyttsx3
except Exception:  # pragma: no cover
    pyttsx3 = None

try:
    import edge_tts
except Exception:  # pragma: no cover
    edge_tts = None

import ctypes
try:
    from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
    _HAS_PYCAW = True
except Exception:
    _HAS_PYCAW = False
from ctypes import wintypes

try:
    import pyttsx3
except Exception:  # pragma: no cover
    pyttsx3 = None
from .textproc import clean_to_orig, orig_to_clean

_SENT_END = re.compile(r"(?<=[。！？!?；;])")
_NEXT_BOUNDARY = re.compile(r"[。！？!?；;\n]")

_MAX_CHUNK = 160
_EDGE_SYNTH_TIMEOUT_SECONDS = 30.0
_EDGE_SYNTH_ATTEMPT_TIMEOUT_SECONDS = 20.0
_EDGE_SYNTH_ATTEMPTS = 2
_EDGE_RETRY_DELAY_SECONDS = 0.35
_EDGE_REQUEST_MIN_INTERVAL_SECONDS = 1.0
_EDGE_BACKOFF_MAX_SECONDS = 120.0
_EDGE_BUFFERING_NOTICE_SECONDS = 1.5
_EDGE_RECOVERY_INITIAL_SECONDS = 30.0
_EDGE_RECOVERY_MAX_SECONDS = 300.0
_EDGE_AUDIO_CACHE_ITEMS = 24
_EDGE_AUDIO_CACHE_BYTES = 16 * 1024 * 1024
_EDGE_DIAGNOSTIC_LOG_BYTES = 2 * 1024 * 1024

LOGGER = logging.getLogger(__name__)


def configure_edge_diagnostics(data_root):
    """Persist bounded Edge diagnostics without正文、令牌或完整请求 URL。"""
    log_dir = os.path.join(os.fspath(data_root), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "edge-tts.log")
    normalized = os.path.normcase(os.path.abspath(log_path))
    for handler in LOGGER.handlers:
        if getattr(handler, "_qyreader_edge_log", None) == normalized:
            return log_path
    handler = RotatingFileHandler(
        log_path,
        maxBytes=_EDGE_DIAGNOSTIC_LOG_BYTES,
        backupCount=3,
        encoding="utf-8",
    )
    handler._qyreader_edge_log = normalized
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    return log_path


class EdgeSynthesisError(RuntimeError):
    """A sanitized Edge failure safe to expose to the UI and diagnostic log."""

    def __init__(self, details):
        self.details = dict(details or {})
        super().__init__(self.details.get("category") or "edge_synthesis_failed")


def _edge_exception_details(exc, *, attempt=None, purpose="playback"):
    if isinstance(exc, EdgeSynthesisError):
        details = dict(exc.details)
        if attempt is not None:
            details["attempt"] = int(attempt)
        details.setdefault("purpose", purpose)
        return details

    chain = []
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = getattr(current, "__cause__", None) or getattr(
            current, "__context__", None
        )

    status_code = None
    headers = None
    status_exception = None
    for item in chain:
        status = getattr(item, "status", None)
        if status is None:
            status = getattr(item, "status_code", None)
        try:
            status = int(status) if status is not None else None
        except (TypeError, ValueError):
            status = None
        if status is not None:
            status_code = status
            headers = getattr(item, "headers", None)
            status_exception = item
            break

    retry_after = None
    if headers is not None:
        try:
            value = headers.get("Retry-After")
            retry_after = max(0.0, float(value)) if value is not None else None
        except (AttributeError, TypeError, ValueError):
            retry_after = None

    exception = status_exception or (chain[-1] if chain else exc)
    exception_type = type(exception).__name__
    names = " ".join(type(item).__name__.lower() for item in chain)
    if status_code == 429:
        category = "rate_limited"
    elif status_code == 403:
        category = "access_denied"
    elif status_code in {500, 502, 503, 504}:
        category = "service_unavailable"
    elif status_code is not None:
        category = "http_error"
    elif "timeout" in names:
        category = "timeout"
    elif "noaudioreceived" in names:
        category = "no_audio"
    elif any(token in names for token in ("connection", "connector", "websocket")):
        category = "connection"
    else:
        category = "unknown"

    details = {
        "category": category,
        "exceptionType": exception_type,
        "statusCode": status_code,
        "retryAfterSeconds": retry_after,
        "purpose": str(purpose or "playback"),
    }
    if attempt is not None:
        details["attempt"] = int(attempt)
    return details


class _EdgeRequestGovernor:
    """Serialize Edge WebSockets and apply process-wide adaptive cooldowns."""

    _PRIORITIES = {"playback": 0, "recovery": 1, "prefetch": 2, "cache": 3}

    def __init__(self, min_interval=_EDGE_REQUEST_MIN_INTERVAL_SECONDS):
        self._cv = threading.Condition()
        self._min_interval = max(0.0, float(min_interval))
        self._busy = False
        self._waiters = []
        self._sequence = 0
        self._next_allowed_at = 0.0
        self._backoff_until = 0.0
        self._failure_streak = 0

    @contextmanager
    def slot(self, timeout, purpose):
        deadline = time.monotonic() + max(0.01, float(timeout))
        priority = self._PRIORITIES.get(str(purpose), 2)
        marker = object()
        with self._cv:
            self._sequence += 1
            ticket = (priority, self._sequence, marker)
            self._waiters.append(ticket)
            while True:
                now = time.monotonic()
                allowed_at = max(self._next_allowed_at, self._backoff_until)
                first = min(self._waiters, key=lambda item: (item[0], item[1]))
                if not self._busy and first[2] is marker and now >= allowed_at:
                    self._waiters.remove(ticket)
                    self._busy = True
                    break
                remaining = deadline - now
                if remaining <= 0:
                    self._waiters.remove(ticket)
                    self._cv.notify_all()
                    raise TimeoutError("等待 Edge 合成请求调度超时")
                wait_for = remaining
                if not self._busy and first[2] is marker and allowed_at > now:
                    wait_for = min(wait_for, allowed_at - now)
                self._cv.wait(timeout=max(0.01, wait_for))
        try:
            yield max(0.01, deadline - time.monotonic())
        finally:
            with self._cv:
                self._busy = False
                self._next_allowed_at = max(
                    self._next_allowed_at,
                    time.monotonic() + self._min_interval,
                )
                self._cv.notify_all()

    def report_success(self):
        with self._cv:
            self._failure_streak = 0

    def report_failure(self, details):
        category = str((details or {}).get("category") or "unknown")
        if category not in {
            "rate_limited",
            "access_denied",
            "service_unavailable",
            "timeout",
        }:
            return 0.0
        with self._cv:
            self._failure_streak += 1
            base = {
                "rate_limited": 15.0,
                "access_denied": 15.0,
                "service_unavailable": 5.0,
                "timeout": 2.0,
            }[category]
            retry_after = (details or {}).get("retryAfterSeconds")
            try:
                retry_after = max(0.0, float(retry_after))
            except (TypeError, ValueError):
                retry_after = 0.0
            delay = max(base * (2 ** (self._failure_streak - 1)), retry_after)
            delay = min(_EDGE_BACKOFF_MAX_SECONDS, delay)
            delay += random.uniform(0.0, min(2.0, delay * 0.15))
            self._backoff_until = max(self._backoff_until, time.monotonic() + delay)
            self._cv.notify_all()
            return delay


_EDGE_REQUEST_GOVERNOR = _EdgeRequestGovernor()


def _install_sapi_stream_events():
    """Keep SAPI's stream identity through pyttsx3's mutable utterance queue."""
    from pyttsx3.drivers import sapi5

    if getattr(sapi5.SAPI5Driver, "_dd_stream_events_installed", False):
        return

    def say_with_stream(self, text):
        self._proxy.setBusy(True)
        self._proxy.notify("started-utterance")
        self._speaking = True
        self._current_text = text
        stream = int(self._tts.Speak(str(text).encode("utf-8").decode("utf-8"), 1))
        self._dd_current_stream = stream
        self._proxy.notify("sapi-stream-queued", stream_number=stream)

    sink = sapi5.SAPI5DriverEventSink
    original_start = sink._ISpeechVoiceEvents_StartStream
    original_word = sink._ISpeechVoiceEvents_Word
    original_end = sink._ISpeechVoiceEvents_EndStream

    def is_current(event_sink, stream_number):
        return int(stream_number) == getattr(event_sink._driver, "_dd_current_stream", None)

    def start_for_current(self, stream_number, stream_position):
        if is_current(self, stream_number):
            return original_start(self, stream_number, stream_position)

    def word_for_current(self, stream_number, stream_position, char, length):
        if is_current(self, stream_number):
            self._driver._proxy.notify(
                "sapi-stream-word", stream_number=int(stream_number),
                location=char, length=length,
            )
            return original_word(self, stream_number, stream_position, char, length)

    def end_for_current(self, stream_number, stream_position):
        if is_current(self, stream_number):
            self._driver._proxy.notify(
                "sapi-stream-end", stream_number=int(stream_number),
                completed=not self._driver._stopping,
            )
            return original_end(self, stream_number, stream_position)

    sapi5.SAPI5Driver.say = say_with_stream
    sink._ISpeechVoiceEvents_StartStream = start_for_current
    sink._ISpeechVoiceEvents_Word = word_for_current
    sink._ISpeechVoiceEvents_EndStream = end_for_current
    sapi5.SAPI5Driver._dd_stream_events_installed = True

# 免费优质中文 Edge 语音（音色自然，接近豆包级）
EDGE_VOICES = [
    ("zh-CN-XiaoxiaoNeural", "晓晓·女声·温柔"),
    ("zh-CN-XiaoyiNeural", "晓伊·女声·活泼"),
    ("zh-CN-YunxiNeural", "云希·男声·阳光"),
    ("zh-CN-YunjianNeural", "云健·男声·沉稳"),
    ("zh-CN-YunyangNeural", "云扬·男声·新闻"),
    ("zh-CN-YunxiaNeural", "云夏·童声"),
    ("zh-TW-HsiaoChenNeural", "晓臻·女声·台湾腔"),
    ("zh-HK-HiuMaanNeural", "晓曼·女声·粤语"),
    ("zh-CN-liaoning-XiaobeiNeural", "晓北·女声·东北腔"),
]


def split_sentences(text):
    """把正文切成朗读用的小句：优先按句末标点，长句按逗号/换行二次切分。"""
    parts = _SENT_END.split(text)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        for sub in re.split(r"\n+", p):
            sub = sub.strip()
            if not sub:
                continue
            out.extend(_hard_split(sub))
    return out


def _hard_split(s):
    if len(s) <= _MAX_CHUNK:
        return [s]
    out = []
    start = 0
    total = len(s)
    while total - start > _MAX_CHUNK:
        limit = start + _MAX_CHUNK
        cut = s.rfind("，", start, limit)
        if cut < start + _MAX_CHUNK // 2:
            cut = s.rfind(",", start, limit)
        if cut < start + _MAX_CHUNK // 2:
            cut = limit
        out.append(s[start:cut])
        start = cut
    out.append(s[start:])
    return out


def _sanitize_name(s):
    """把语音 ID 等转成安全的文件名片段。"""
    return re.sub(r"[^A-Za-z0-9_\-]", "_", str(s)) or "default"


def synth_audio(text, voice, rate=200, timeout=None):
    """用 Edge 神经语音把一句文本合成为 MP3 字节（独立事件循环，线程安全）。"""
    if edge_tts is None:
        raise RuntimeError("edge-tts 未安装")
    rate_adj = int((max(80, min(400, int(rate))) - 200) / 2)
    buf = bytearray()

    async def _gen():
        c = edge_tts.Communicate(text, voice, rate=f"{rate_adj:+d}%")
        async for chunk in c.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])

    loop = asyncio.new_event_loop()
    try:
        # edge-tts has per-socket timeouts, but one synthesis can otherwise
        # remain silent for about a minute while the controller still reports
        # ``playing``.  Keep a bounded whole-request deadline so a stalled
        # network request reaches the existing one-time SAPI fallback.
        request_timeout = (
            _EDGE_SYNTH_TIMEOUT_SECONDS if timeout is None else max(0.01, float(timeout))
        )
        loop.run_until_complete(asyncio.wait_for(_gen(), timeout=request_timeout))
    finally:
        loop.close()
    return bytes(buf)


def _synth_audio_governed(text, voice, rate=200, timeout=None, purpose="playback"):
    """Run one sanitized, process-wide governed Edge request."""
    request_timeout = (
        _EDGE_SYNTH_TIMEOUT_SECONDS if timeout is None else max(0.01, float(timeout))
    )
    try:
        with _EDGE_REQUEST_GOVERNOR.slot(request_timeout, purpose) as remaining:
            try:
                audio = synth_audio(
                    text,
                    voice,
                    rate,
                    timeout=min(request_timeout, remaining),
                )
                if not audio:
                    raise EdgeSynthesisError({
                        "category": "no_audio",
                        "exceptionType": "EmptyAudio",
                        "statusCode": None,
                        "retryAfterSeconds": None,
                        "purpose": purpose,
                    })
            except Exception as exc:
                details = _edge_exception_details(exc, purpose=purpose)
                details["cooldownSeconds"] = round(
                    _EDGE_REQUEST_GOVERNOR.report_failure(details), 3
                )
                LOGGER.warning(
                    "edge_synthesis_failure %s",
                    json.dumps(details, ensure_ascii=True, sort_keys=True),
                )
                raise EdgeSynthesisError(details) from exc
            _EDGE_REQUEST_GOVERNOR.report_success()
            return audio
    except EdgeSynthesisError:
        raise
    except Exception as exc:
        details = _edge_exception_details(exc, purpose=purpose)
        details["cooldownSeconds"] = round(
            _EDGE_REQUEST_GOVERNOR.report_failure(details), 3
        )
        LOGGER.warning(
            "edge_synthesis_failure %s",
            json.dumps(details, ensure_ascii=True, sort_keys=True),
        )
        raise EdgeSynthesisError(details) from exc


class _EdgePrefetch:
    """后台批量预取后续句子的音频，缓存最多 MAX_AHEAD 句，句间零卡顿。

    Multiple workers reserve sentences in order and synthesize them concurrently.
    Results are keyed by clean-text offset, so playback still consumes them in
    exact reading order even when a later network request finishes first.
    """

    MAX_AHEAD = 3
    WORKERS = 1

    def __init__(self, synth_fn, content, start_off, limit=MAX_AHEAD, autostart=True):
        self._synth = synth_fn
        self._content = content
        self._limit = limit
        self._lock = threading.Lock()
        self._ready = threading.Condition()
        self._results = {}
        self._last_failures = {}
        self._slots = threading.Semaphore(limit)
        self._next_off = start_off
        self._stopped = threading.Event()
        self._workers = [
            threading.Thread(target=self._run, daemon=True)
            for _ in range(min(self.WORKERS, limit))
        ]
        self._started = False
        if autostart:
            self.start()

    def start(self):
        """Start workers once, allowing the current sentence to take priority."""
        with self._lock:
            if self._started or self._stopped.is_set():
                return
            self._started = True
            workers = list(self._workers)
        for worker in workers:
            worker.start()

    def _run(self):
        try:
            while not self._stopped.is_set():
                if not self._slots.acquire(timeout=0.2):
                    continue
                with self._lock:
                    off = self._next_off
                    text, nxt, _ = SpeechController._next_chunk(self._content, off)
                    if not text or nxt <= off:
                        self._slots.release()
                        return
                    self._next_off = nxt
                try:
                    audio = self._synth(text)
                    failure = None
                except Exception as exc:
                    audio = None
                    failure = _edge_exception_details(exc, purpose="prefetch")
                with self._ready:
                    self._results[off] = (text, audio, failure)
                    self._ready.notify_all()
                if failure is not None:
                    # Preserve the failed sentence for ordered consumption but
                    # stop opening more WebSockets behind a rejected request.
                    return
        except Exception:
            pass

    def get(self, timeout=None):
        """取一句已预取的音频，返回 (text, audio)；超时返回 None。"""
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._ready:
            while not self._stopped.is_set():
                if self._results:
                    off = min(self._results)
                    text, audio, failure = self._results.pop(off)
                    if failure:
                        self._last_failures[off] = failure
                    self._slots.release()
                    self._ready.notify_all()
                    return text, audio
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._ready.wait(timeout=remaining)
        return None

    def get_expected(self, expected_off, expected_text, timeout=None):
        """Wait for one exact sentence while retaining out-of-order results.

        Returns ``(ready, audio)``.  ``ready`` is true for both successful and
        failed synthesis, so a failed network request never becomes a phantom
        queue timeout.  Later sentences remain buffered until their turn.
        """
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._ready:
            while not self._stopped.is_set():
                stale = [off for off in self._results if off < expected_off]
                for off in stale:
                    self._results.pop(off, None)
                    self._slots.release()
                if expected_off in self._results:
                    text, audio, failure = self._results.pop(expected_off)
                    if failure:
                        self._last_failures[expected_off] = failure
                    self._slots.release()
                    self._ready.notify_all()
                    return text == expected_text, audio if text == expected_text else None
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False, None
                self._ready.wait(timeout=remaining)
        return False, None

    def ready_count(self):
        with self._ready:
            return len(self._results)

    def failure_for(self, expected_off):
        with self._ready:
            return self._last_failures.pop(expected_off, None)

    def close(self):
        self._stopped.set()
        with self._ready:
            self._ready.notify_all()


class WholeBookCacher:
    """整本语音缓存：后台多线程把全书逐句合成并落盘。

    设计要点（保证「缓存期间不影响正常朗读」）：
    - 完全独立于朗读工作线程：不使用 pygame / pyttsx3，不占用朗读音频资源；
    - 单线程低优先级缓存，所有 Edge 请求再由进程级调度器统一串行；
    - 文件先写临时名再 os.replace 原子发布，朗读线程永远读不到半截文件；
    - 朗读侧按 (章节, 句偏移, 语音, 语速, 书籍) 命中缓存则直接播放，整本缓存完成后朗读零网络延迟；
    - 支持暂停/继续、章节选择、续传（已缓存文件自动跳过）、容量统计、完成后自动关机。
    """

    WORKERS = 1
    SAVE_INTERVAL = 50  # 每完成 N 个任务保存一次进度

    def __init__(self, book, book_id, cache_root, voice, rate, chapter_indices=None,
                 bump_cb=None, size_cb=None, flush_cb=None, preset_tasks=None):
        self._book = book
        self._book_id = str(book_id or "book")
        # 每本书一个顶层目录：<cache_root>/<book_id>/<语音>/<语速>/
        self._dir = os.path.join(
            cache_root, self._book_id, _sanitize_name(voice), str(int(rate))
        )
        self._voice = voice
        self._rate = int(rate)
        self._bump_cb = bump_cb   # 写文件后回调（大小索引增量）
        self._size_cb = size_cb   # 查询该书已缓存大小（读索引）
        self._flush_cb = flush_cb # 完成/暂停/取消时回调（大小索引落盘）
        self._chapter_indices = chapter_indices  # set[int] 或 None=全部
        self._tasks = []  # [(ci, off, text)]，由后台线程构建
        self._total = 0
        self._done = 0
        self._next = 0
        self._completed = set()  # 已完成任务索引（持久化）
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self._pause_evt = threading.Event()
        self._pause_evt.set()  # 默认运行
        self._state = "idle"  # idle / building / caching / paused / done / cancelled
        self._auto_shutdown = False
        self._shutdown_posted = False
        self._last_save = 0
        self._bytes_written = 0  # 本轮实际写入的音频字节（持久化大小用）
        self._build_ready = threading.Event()  # 任务列表构建完成信号
        self._build_error = None
        if preset_tasks is not None:
            # 验证补全模式：直接使用预置的缺失任务列表，不重新构建
            with self._lock:
                self._tasks = list(preset_tasks)
                self._total = len(self._tasks)
            self._build_ready.set()
        else:
            # 任务列表在后台线程构建：百万字长篇小说逐章切句耗时，不能阻塞 GUI 线程
            threading.Thread(target=self._build_tasks_bg, daemon=True).start()

    def _progress_path(self):
        return os.path.join(self._dir, "progress.json")

    def _load_progress(self):
        """加载持久化进度，返回 (done_count, completed_set) 或 None。"""
        try:
            p = self._progress_path()
            if not os.path.exists(p):
                return None
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 只有任务总数匹配时才复用进度（章节选择变化时重置）
            if data.get("total") != self._total:
                return None
            if data.get("book_id") != self._book_id:
                return None
            if data.get("voice") != self._voice or data.get("rate") != self._rate:
                return None
            completed = set(data.get("completed", []))
            done = data.get("done", len(completed))
            return done, completed
        except Exception:
            return None

    def _save_progress(self, state=None):
        """保存当前进度到 progress.json。"""
        try:
            os.makedirs(self._dir, exist_ok=True)
            with self._lock:
                done = self._done
                completed = sorted(self._completed)
                total = self._total
                cur_state = state or self._state
            data = {
                "book_id": self._book_id,
                "voice": self._voice,
                "rate": self._rate,
                "total": total,
                "done": done,
                "completed": completed,
                "state": cur_state,
                "updated_at": time.time(),
            }
            tmp = self._progress_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self._progress_path())
        except Exception:
            pass

        if self._flush_cb is not None:
            try:
                self._flush_cb()
            except Exception:
                pass

    def _build_tasks(self):
        for ci, ch in enumerate(self._book.chapters):
            if self._chapter_indices is not None and ci not in self._chapter_indices:
                continue
            # 与朗读侧一致：在「纯净文本」上切句合成（去连续标点/空白/颜文字），
            # 文件仍按「原文偏移」命名，保证朗读时缓存可命中。
            clean_text, cmap = ch.tts_content()
            orig_len = len(ch.content)
            # 一次性切分整章全部句子（O(n)），避免逐句调用 _next_chunk
            # 导致的对剩余文本反复切片（O(n²)，百万字书会卡几十秒）。
            # _next_chunk 的切分规则与 split_sentences 完全一致，结果可互相命中。
            clean_off = 0
            for text in split_sentences(clean_text):
                if not text:
                    continue
                start = clean_text.find(text, clean_off)
                if start < 0:
                    start = clean_off
                orig_off = clean_to_orig(cmap, start, orig_len)
                self._tasks.append((ci, orig_off, text))
                clean_off = start + len(text)

    def _build_tasks_bg(self):
        """后台构建任务列表（逐章切句），完成后置 build_ready 信号。"""
        try:
            self._build_tasks()
            with self._lock:
                self._total = len(self._tasks)
        except Exception as e:
            with self._lock:
                self._build_error = e
        finally:
            self._build_ready.set()

    def start(self, resume=False):
        """开始缓存。立即返回（不阻塞 GUI），后台等待任务构建完成后再开跑。

        resume=True 时从持久化进度继续（跳过已完成任务）。
        """
        with self._lock:
            if self._state == "caching":
                return
            if self._state == "done":
                return
            self._state = "caching"
            self._cancelled.clear()
            self._pause_evt.set()
        os.makedirs(self._dir, exist_ok=True)
        threading.Thread(target=self._init_and_run, args=(resume,), daemon=True).start()

    def _init_and_run(self, resume):
        """在后台线程中：等待任务构建完成 → 初始化进度 → 启动工作线程。"""
        self._build_ready.wait()
        with self._lock:
            if self._build_error is not None:
                self._state = "cancelled"
                return
            total = self._total
        if total == 0:
            with self._lock:
                self._state = "done"
            self._save_progress("done")
            return

        if resume:
            prog = self._load_progress()
            if prog is not None:
                done, completed = prog
                with self._lock:
                    self._done = done
                    self._completed = set(completed)
                # 校验 completed：标记完成但实际文件缺失的任务剔除（断网/失败误标，允许补齐）
                if self._completed:
                    bad = []
                    for idx in list(self._completed):
                        ci, off, _text = self._tasks[idx]
                        if not self._file_exists(ci, off):
                            bad.append(idx)
                    for idx in bad:
                        with self._lock:
                            self._completed.discard(idx)
                            if self._done > 0:
                                self._done -= 1
                with self._lock:
                    # 找到第一个未完成的任务索引
                    self._next = 0
                    while self._next < total and self._next in self._completed:
                        self._next += 1
                # 如果全部完成，直接标记 done
                with self._lock:
                    if self._next >= total:
                        self._state = "done"
                if self._next >= total:
                    self._save_progress("done")
                    return
            else:
                # 无持久化进度：从头开始，但仍通过 _file_exists 跳过已缓存文件
                with self._lock:
                    self._done = 0
                    self._next = 0
                    self._completed = set()
        else:
            # 非 resume：从头开始（仍通过 _file_exists 跳过已缓存文件）
            with self._lock:
                self._done = 0
                self._next = 0
                self._completed = set()

        self._spawn_workers()

    def _spawn_workers(self):
        # 固定 WORKERS 个工作线程；任务不足时 worker 会自动退出
        for _ in range(self.WORKERS):
            threading.Thread(target=self._worker, daemon=True).start()

    def pause(self):
        self._pause_evt.clear()
        with self._lock:
            if self._state == "caching":
                self._state = "paused"
        self._save_progress("paused")

    def resume(self):
        if self._state != "paused":
            return self.status()
        self._state = "caching"
        self._pause_evt.set()
        self._spawn_workers()
        return self.status()

    def cancel(self):
        self._cancelled.set()
        self._pause_evt.set()
        with self._lock:
            if self._state in ("caching", "paused"):
                self._state = "cancelled"
        self._save_progress("cancelled")

    def set_auto_shutdown(self, on):
        self._auto_shutdown = bool(on)

    def _worker(self):
        # 等待任务列表构建完成（构建失败则直接退出）
        self._build_ready.wait()
        with self._lock:
            if self._build_error is not None:
                return
        while True:
            if self._cancelled.is_set():
                return
            if not self._pause_evt.wait(timeout=0.2):
                return  # 暂停：退出，等待 resume 重新拉线程
            with self._lock:
                if self._next >= len(self._tasks):
                    break
                idx = self._next
                self._next += 1
            ci, off, text = self._tasks[idx]
            # 已在持久化进度中标记完成的任务直接跳过
            with self._lock:
                already = idx in self._completed
            if already:
                continue
            if self._file_exists(ci, off):
                # 文件已存在（可能是之前缓存的），标记完成
                with self._lock:
                    self._completed.add(idx)
                    self._done += 1
                self._maybe_save()
                continue
            try:
                audio = _synth_audio_governed(
                    text,
                    self._voice,
                    self._rate,
                    purpose="cache",
                )
                if not audio:
                    continue  # 合成失败/空：不标记完成，留待续传重试
                self._write(ci, off, audio)
            except EdgeSynthesisError:
                # Do not walk the rest of the book after the service has begun
                # rejecting requests. With one worker it is safe to put this
                # task back and pause until the user explicitly resumes.
                with self._lock:
                    self._next = min(self._next, idx)
                break
            except Exception:
                continue  # 本地写入等失败：不标记完成，留待续传重试
            with self._lock:
                self._completed.add(idx)
                self._done += 1
            self._maybe_save()
        # 检查是否全部完成（多 worker 竞态：任一 worker 收尾时已全部完成则无条件置 done）
        with self._lock:
            all_done = self._done >= self._total
        if all_done and not self._cancelled.is_set():
            with self._lock:
                self._state = "done"
            self._save_progress("done")
        elif self._state in ("caching", "building") and not self._cancelled.is_set():
            # 有任务因合成失败未完成：转暂停，进度保留，可续传补齐
            with self._lock:
                self._state = "paused"
            self._save_progress("paused")
        if (
            self._state == "done"
            and self._auto_shutdown
            and not self._shutdown_posted
        ):
            self._shutdown_posted = True
            self._post_shutdown()

    def _maybe_save(self):
        """每完成 SAVE_INTERVAL 个任务保存一次进度。"""
        with self._lock:
            done = self._done
        if done - self._last_save >= self.SAVE_INTERVAL:
            self._last_save = done
            self._save_progress()

    def _post_shutdown(self):
        """缓存完成后自动关机：60 秒倒计时，运行 `shutdown /a` 可取消。"""
        try:
            os.system("shutdown /s /t 60")
        except Exception:
            pass

    def _file_exists(self, ci, off):
        try:
            p = self._path(ci, off)
            return os.path.exists(p) and os.path.getsize(p) > 0
        except Exception:
            return False

    def _write(self, ci, off, audio):
        try:
            final = self._path(ci, off)
            tmp = final + ".tmp"
            with open(tmp, "wb") as f:
                f.write(audio)
            os.replace(tmp, final)
            with self._lock:
                self._bytes_written += len(audio)
            if self._bump_cb is not None:
                try:
                    self._bump_cb(self._book_id, self._voice, self._rate, len(audio))
                except Exception:
                    pass
        except Exception:
            pass

    def _path(self, ci, off):
        return os.path.join(self._dir, f"{int(ci):04d}_{int(off):08d}.mp3")

    def disk_used(self):
        """当前书籍缓存目录占用字节数（不含 progress.json）。

        优先读大小索引（不扫盘）；无索引回调时才退化为遍历目录。
        """
        if self._size_cb is not None:
            try:
                return int(self._size_cb(self._book_id) or 0)
            except Exception:
                pass
        total = 0
        try:
            for root, _, files in os.walk(self._dir):
                for f in files:
                    if f == "progress.json" or f.endswith(".tmp"):
                        continue
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except Exception:
                        pass
        except Exception:
            pass
        return total

    def status(self):
        with self._lock:
            return {"state": self._state, "done": self._done, "total": self._total,
                    "bytes_written": self._bytes_written}


class SpeechController:
    _SAPI_INTERRUPTED = object()

    def __init__(self):
        self._cv = threading.Condition()
        self._state = "idle"  # idle / playing / paused
        self._engine = None
        self._sapi_rebuild = False
        self._thread = None
        self._ready = None
        self._book = None
        self._ci = 0
        self._off = 0
        self._gen = 0  # 会话代号：每次 start 自增
        self._resume_counter = 0
        self._queue = queue.Queue()
        self._pending_voice = None  # SAPI 语音
        self._applied_voice = None
        self._applied_rate = None
        self._rate = 200
        self._volume = 100
        self._sentence_gap = 0.10
        self._backend = "sapi"
        self._edge_voice = "zh-CN-XiaoxiaoNeural"
        self._active_sentence_backend = "sapi"
        self._edge_prefetch = None
        self._edge_fail_posted = False
        self._edge_session_fallback = False
        self._edge_recovery_token = 0
        self._edge_recovery_due_at = 0.0
        self._edge_recovery_backoff = _EDGE_RECOVERY_INITIAL_SECONDS
        self._edge_recovery_key = None
        self._edge_recovery_audio = None
        self._edge_recovery_event = None
        self._edge_prime_token = 0
        self._edge_prime_key = None
        self._edge_prime_audio = None
        self._edge_prime_failure = None
        self._edge_prime_event = None
        self._edge_prime_prefetch = None
        self._edge_audio_cache = OrderedDict()
        self._edge_audio_cache_bytes = 0
        self._warm_sapi_requested = False
        self._tts_cache_dir = None
        self._book_id = "book"
        # 整本语音缓存：按 book_id 管理，每本书独立缓存器，互不阻塞（支持多书同时缓存）
        self._book_cachers = {}
        self._book_cachers_lock = threading.Lock()
        # 音频缓存大小索引（避免反复遍历数万细碎 mp3 文件）
        self._size_entries = None   # 懒加载：{key: {"size","t"}}
        self._size_dirty = False
        self._size_bumps = 0
        self._size_lock = threading.RLock()  # 可重入：bump/load 嵌套 with 不锁死
        # 整本缓存「完成态」文件数校验：后台单线程逐本执行（主线程只读集合，绝不扫描磁盘）
        self._hist_done_checked = set()
        self._hist_done_downgraded = set()
        self._hist_check_lock = threading.Lock()
        self._hist_check_queue = []
        self._hist_check_worker = None
        self._closed = False

    # ---------- 事件 ----------
    def _post(self, evt, generation=None):
        if generation is not None:
            evt.setdefault("generation", generation)
        self._queue.put(evt)

    def drain(self):
        out = []
        while True:
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return out

    # ---------- 状态 ----------
    def is_playing(self):
        with self._cv:
            return self._state == "playing"

    def is_paused(self):
        with self._cv:
            return self._state == "paused"

    def is_active(self):
        with self._cv:
            return self._state in ("playing", "paused")

    def is_stopped(self):
        with self._cv:
            return self._state == "idle"

    def generation(self):
        with self._cv:
            return self._gen

    def backend(self):
        with self._cv:
            return self._backend

    # ---------- 对外设置（只存值，工作线程应用） ----------
    def set_voice(self, voice_id):
        with self._cv:
            previous = (self._backend, self._pending_voice, self._edge_voice)
            if not voice_id:
                self._backend = "sapi"
                self._pending_voice = None
            elif "HKEY" in voice_id or "TTS_MS" in voice_id or "SOFTWARE" in voice_id:
                # 系统 SAPI 语音
                self._backend = "sapi"
                self._pending_voice = voice_id
            else:
                # Edge 神经语音（zh-CN-XiaoxiaoNeural 等）
                self._backend = "edge"
                self._edge_voice = voice_id
            if previous != (self._backend, self._pending_voice, self._edge_voice):
                self._invalidate_edge_prime_locked()

    def set_rate(self, rate):
        with self._cv:
            rate = int(rate)
            if rate != self._rate:
                self._rate = rate
                self._invalidate_edge_prime_locked()

    def set_sentence_gap(self, gap):
        """句子之间的停顿间隔（秒），默认 0.10。"""
        with self._cv:
            self._sentence_gap = max(0.0, float(gap))

    def set_volume(self, volume):
        """设置本程序音量（0-100），即时应用到当前进程音频会话。"""
        self._volume = max(0, min(100, int(volume)))
        # 优先使用 Core Audio（pycaw），失败则回退 MCI
        if not _set_process_volume(self._volume):
            try:
                _mci_set_volume(self._volume)
            except Exception:
                pass

    def get_volume(self):
        return self._volume

    def prefetch_progress(self):
        """返回 Edge 后端当前预取缓存进度 (已缓存句数, 上限)；非 Edge 或未朗读返回 None。"""
        with self._cv:
            if self._backend != "edge":
                return None
            pf = self._edge_prefetch
        if pf is None:
            return None
        try:
            return (pf.ready_count(), _EdgePrefetch.MAX_AHEAD)
        except Exception:  # pragma: no cover
            return None

    # ---------- 整本语音缓存 ----------
    def set_tts_cache_dir(self, path):
        self._tts_size_persist()  # 切换前把脏索引落盘到旧目录（转移时随目录带走）
        self._tts_cache_dir = path
        with self._size_lock:
            self._size_entries = None  # 目录切换后重新懒加载
            self._size_dirty = False

    def set_book_id(self, book_id):
        with self._cv:
            book_id = str(book_id or "book")
            if book_id != self._book_id:
                self._book_id = book_id
                self._invalidate_edge_prime_locked()

    def prepare(self, book, chapter_idx, char_offset):
        """Warm the selected backend for the next play without changing state.

        SAPI initialization stays on the one speech worker.  Edge synthesis is
        single-flight and keyed by book, voice, rate and exact sentence, so a
        play click can reuse the already-running request instead of starting a
        duplicate network call.
        """
        if book is None or not getattr(book, "chapters", None):
            return
        self._ensure_thread()
        with self._cv:
            backend = self._backend
            if backend == "sapi":
                self._warm_sapi_requested = True
                self._cv.notify_all()
                return
            voice = self._edge_voice
            rate = int(self._rate)
            book_id = self._book_id
        try:
            ci = max(0, min(int(chapter_idx), len(book.chapters) - 1))
            content, cmap = book.chapters[ci].tts_content()
            original = book.chapters[ci].content
            clean_offset = (
                orig_to_clean(cmap, int(char_offset))
                if int(char_offset) < len(original)
                else len(content)
            )
            text, next_clean, sentence_start = self._next_chunk(content, clean_offset)
            if not text:
                return
            original_offset = clean_to_orig(
                cmap, clean_offset + sentence_start, len(original)
            )
        except (AttributeError, IndexError, TypeError, ValueError):
            return
        key = (book_id, voice, rate, ci, original_offset, text)
        with self._cv:
            if self._edge_prime_key == key and self._edge_prime_event is not None:
                return
            self._invalidate_edge_prime_locked()
            token = self._edge_prime_token
            ready = threading.Event()
            self._edge_prime_key = key
            self._edge_prime_failure = None
            self._edge_prime_event = ready
            self._edge_prime_prefetch = _EdgePrefetch(
                self._edge_synthesize,
                content,
                next_clean,
                _EdgePrefetch.MAX_AHEAD,
                autostart=False,
            )
            prime_prefetch = self._edge_prime_prefetch
        cached = self._memory_edge_audio(key) or self._cached_audio(ci, original_offset)
        if cached:
            self._remember_edge_audio(key, cached)
            with self._cv:
                if token == self._edge_prime_token and key == self._edge_prime_key:
                    self._edge_prime_audio = cached
                ready.set()
            prime_prefetch.start()
            return
        prime_thread = threading.Thread(
            target=self._prime_edge_sentence,
            args=(token, key, text, ready),
            name="dd-edge-prime",
            daemon=True,
        )
        # Give the sentence the user is waiting for the first connection slot,
        # then fill the smaller lookahead window while its audio is playing.
        prime_thread.start()

    def _prime_edge_sentence(self, token, key, text, ready):
        try:
            audio = self._edge_synthesize(text)
            failure = None
        except Exception as exc:
            audio = None
            failure = _edge_exception_details(exc, purpose="playback")
        with self._cv:
            if token == self._edge_prime_token and key == self._edge_prime_key:
                self._edge_prime_audio = audio
                self._edge_prime_failure = failure
                prefetch = self._edge_prime_prefetch
            else:
                prefetch = None
            ready.set()
        if prefetch is not None and audio:
            prefetch.start()

    def _invalidate_edge_prime_locked(self):
        prefetch = self._edge_prime_prefetch
        self._edge_prime_token += 1
        self._edge_prime_key = None
        self._edge_prime_audio = None
        self._edge_prime_failure = None
        self._edge_prime_event = None
        self._edge_prime_prefetch = None
        if prefetch is not None:
            try:
                prefetch.close()
            except Exception:
                pass

    def _memory_edge_audio(self, key):
        """Return one recently generated sentence and refresh its LRU position."""
        with self._cv:
            audio = self._edge_audio_cache.pop(key, None)
            if audio:
                self._edge_audio_cache[key] = audio
            return audio

    def _remember_edge_audio(self, key, audio):
        """Keep recent audio for pause/restart without another network request."""
        if not audio:
            return
        audio = bytes(audio)
        with self._cv:
            previous = self._edge_audio_cache.pop(key, None)
            if previous:
                self._edge_audio_cache_bytes -= len(previous)
            self._edge_audio_cache[key] = audio
            self._edge_audio_cache_bytes += len(audio)
            while self._edge_audio_cache and (
                len(self._edge_audio_cache) > _EDGE_AUDIO_CACHE_ITEMS
                or self._edge_audio_cache_bytes > _EDGE_AUDIO_CACHE_BYTES
            ):
                _, removed = self._edge_audio_cache.popitem(last=False)
                self._edge_audio_cache_bytes -= len(removed)

    def _edge_prime_result(self, ci, off, text, timeout=0.10):
        with self._cv:
            key = (
                self._book_id,
                self._edge_voice,
                int(self._rate),
                int(ci),
                int(off),
                text,
            )
            if key != self._edge_prime_key or self._edge_prime_event is None:
                return False, False, None, None, None
            token = self._edge_prime_token
            ready = self._edge_prime_event
        ready.wait(timeout=max(0.0, float(timeout)))
        with self._cv:
            if token != self._edge_prime_token or key != self._edge_prime_key:
                return False, False, None, None, None
            if not ready.is_set():
                return True, False, None, None, None
            audio = self._edge_prime_audio
            failure = self._edge_prime_failure
            prefetch = self._edge_prime_prefetch
            self._edge_prime_key = None
            self._edge_prime_audio = None
            self._edge_prime_failure = None
            self._edge_prime_event = None
            self._edge_prime_prefetch = None
            return True, True, audio, prefetch, failure

    def _cacher_for(self, book_id=None):
        """按 book_id 取缓存器；未指定时用当前书 id。"""
        bid = str(book_id or self._book_id or "book")
        with self._book_cachers_lock:
            return self._book_cachers.get(bid)

    def _cached_audio(self, ci, off):
        """按 (章节, 句偏移, 语音, 语速, 书籍) 查找整本缓存中的 MP3；未命中返回 None。"""
        if not self._tts_cache_dir:
            return None
        with self._cv:
            voice = self._edge_voice
            rate = int(self._rate)
        bid = self._book_id or "book"
        d = os.path.join(self._tts_cache_dir, bid, _sanitize_name(voice), str(rate))
        p = os.path.join(d, f"{int(ci):04d}_{int(off):08d}.mp3")
        try:
            if os.path.exists(p) and os.path.getsize(p) > 0:
                with open(p, "rb") as f:
                    return f.read()
        except Exception:
            pass
        return None

    def start_book_cache(self, book, book_id, chapter_indices=None, resume=False):
        """开启整本语音缓存（仅 Edge 后端），可按章节子集缓存。

        多书独立：每本书一个缓存器（keyed by book_id），第一本书缓存进行中
        也可以同时缓存第二本，互不干扰。resume=True 从持久化进度继续。
        返回状态 dict。
        """
        if self._backend != "edge":
            return {"state": "unsupported"}
        if not self._tts_cache_dir or not book or not book.chapters:
            return {"state": "unavailable"}
        bid = str(book_id or "book")
        self._book_id = bid  # 同步当前书 id，保证后续查询/控制落在本书
        with self._cv:
            voice = self._edge_voice
            rate = int(self._rate)
        with self._book_cachers_lock:
            cacher = self._book_cachers.get(bid)
            if cacher is not None:
                st = cacher.status()
                # 同书正在缓存：幂等返回，不重复启动
                if st["state"] == "caching":
                    return st
                same_sel = self._same_chapter_sel(cacher._chapter_indices, chapter_indices)
                # 同书已暂停且要求续传且章节选择未变：直接恢复（保留内存进度）
                if st["state"] == "paused" and resume and same_sel:
                    return cacher.resume()
                # 同书已完成且章节选择未变：幂等返回完成状态
                if st["state"] == "done" and same_sel:
                    return st
                # 其余情况（章节选择变化 / 暂停后显式重来 / 取消后重来）：重建 cacher，
                # 保证任务列表与本次选择一致（旧 done 任务列表会阻断新选择）
            cacher = WholeBookCacher(
                book, bid, self._tts_cache_dir, voice, rate, chapter_indices,
                bump_cb=self._tts_size_bump, size_cb=self.tts_cache_size,
                flush_cb=self._tts_size_persist,
            )
            self._book_cachers[bid] = cacher
        cacher.start(resume=resume)
        return cacher.status()

    @staticmethod
    def _same_chapter_sel(a, b):
        """章节选择是否相同：None 表示全选，与全选集合等价。"""
        a = a if a is None else set(a)
        b = b if b is None else set(b)
        return a == b

    def get_book_cache_progress(self, book, book_id):
        """返回缓存进度（优先读活跃 cacher 真实状态，无活跃任务时回退持久化进度）。"""
        bid = str(book_id or "")
        # 优先：当前有活跃 cacher（正在缓存/暂停/完成），直接读真实状态
        active = self._book_cachers.get(bid)
        if active is not None:
            st = active.status()
            return {"done": st.get("done", 0), "total": st.get("total", 0),
                    "state": st.get("state", "paused")}
        # 回退：读 progress.json（已暂停的历史任务）
        if not self._tts_cache_dir or not book:
            return None
        with self._cv:
            voice = self._edge_voice
            rate = int(self._rate)
        try:
            cacher = WholeBookCacher(book, book_id, self._tts_cache_dir, voice, rate, None)
            cacher._build_ready.wait(timeout=60)
            prog = cacher._load_progress()
            if prog is None:
                return None
            done, completed = prog
            return {"done": done, "total": cacher._total, "state": "paused"}
        except Exception:
            return None

    def verify_book_cache(self, book, book_id):
        """验证整本语音缓存完整性：按当前分章/语音/语速重建任务列表，
        扫描磁盘 mp3，返回缺失任务明细（供补全按钮使用）。

        返回 dict: {total, missing_count, missing(list[(ci,off,text)]),
                    chapters{ci:缺数}, complete, dir}，异常时含 error。
        """
        if not self._tts_cache_dir or not book or not book.chapters:
            return {"error": "unavailable"}
        bid = str(book_id or "book")
        with self._cv:
            voice = self._edge_voice
            rate = int(self._rate)
        root = os.path.join(self._tts_cache_dir, bid, _sanitize_name(voice), str(rate))
        # 与 WholeBookCacher._build_tasks 完全一致的任务构建（同一套切分/偏移规则）
        tasks = []
        for ci, ch in enumerate(book.chapters):
            clean_text, cmap = ch.tts_content()
            orig_len = len(ch.content)
            clean_off = 0
            for text in split_sentences(clean_text):
                if not text:
                    continue
                start = clean_text.find(text, clean_off)
                if start < 0:
                    start = clean_off
                orig_off = clean_to_orig(cmap, start, orig_len)
                tasks.append((ci, orig_off, text))
                clean_off = start + len(text)
        missing = []
        ch_counts = {}
        for ci, off, text in tasks:
            try:
                p = os.path.join(root, "%04d_%08d.mp3" % (int(ci), int(off)))
                if os.path.isfile(p) and os.path.getsize(p) > 0:
                    continue
            except Exception:
                pass
            missing.append((ci, off, text))
            ch_counts[ci] = ch_counts.get(ci, 0) + 1
        return {
            "total": len(tasks),
            "missing_count": len(missing),
            "missing": missing,
            "chapters": ch_counts,
            "complete": not missing,
            "dir": root,
        }

    def fill_missing_cache(self, book, book_id, missing_tasks):
        """只缓存验证发现的缺失任务（补全模式），不重新下载已缓存部分。

        使用 preset_tasks 让缓存器直接处理缺失任务列表。返回状态 dict。
        """
        if self._backend != "edge":
            return {"state": "unsupported"}
        if not self._tts_cache_dir or not book or not book.chapters or not missing_tasks:
            return {"state": "unavailable"}
        bid = str(book_id or "book")
        self._book_id = bid
        with self._cv:
            voice = self._edge_voice
            rate = int(self._rate)
        with self._book_cachers_lock:
            cacher = self._book_cachers.get(bid)
            if cacher is not None and cacher.status()["state"] in ("caching", "building"):
                return cacher.status()  # 补全任务已在跑，幂等返回
            cacher = WholeBookCacher(
                book, bid, self._tts_cache_dir, voice, rate,
                bump_cb=self._tts_size_bump, size_cb=self.tts_cache_size,
                flush_cb=self._tts_size_persist, preset_tasks=missing_tasks,
            )
            self._book_cachers[bid] = cacher
        cacher.start(resume=False)
        return cacher.status()

    def pause_book_cache(self, book_id=None):
        cacher = self._cacher_for(book_id)
        if cacher is not None:
            return cacher.pause()
        return None

    def resume_book_cache(self, book_id=None):
        cacher = self._cacher_for(book_id)
        if cacher is not None:
            return cacher.resume()
        return None

    def cancel_book_cache(self, book_id=None):
        cacher = self._cacher_for(book_id)
        if cacher is not None:
            cacher.cancel()
            return cacher.status()
        return None

    def pause_all_book_cache(self):
        """关闭程序时暂停所有正在进行的缓存，保留进度供下次续传。"""
        with self._book_cachers_lock:
            cachers = list(self._book_cachers.values())
        for c in cachers:
            try:
                c.pause()
            except Exception:
                pass
        self._tts_size_persist()

    def set_book_cache_auto_shutdown(self, on, book_id=None):
        cacher = self._cacher_for(book_id)
        if cacher is not None:
            cacher.set_auto_shutdown(bool(on))

    def book_cache_disk_used(self, book_id=None):
        """当前书籍音频缓存占用字节数（读大小索引，不扫盘）。"""
        return self.tts_cache_size(book_id)
    # ---------- 音频缓存大小索引（避免反复遍历数万细碎 mp3） ----------
    def _tts_size_load(self):
        with self._size_lock:
            if self._size_entries is None:
                from .storage import load_tts_size_index
                root = self._tts_cache_dir or ""
                self._size_entries = load_tts_size_index(root)
            return self._size_entries

    def _tts_size_persist(self):
        with self._size_lock:
            if self._size_entries is not None and self._size_dirty:
                from .storage import save_tts_size_index
                save_tts_size_index(self._tts_cache_dir or "", self._size_entries)
                self._size_dirty = False

    def _tts_size_bump(self, bid, voice, rate, delta):
        """缓存写文件成功后增量累加大小（每 50 次落盘一次）。"""
        try:
            with self._size_lock:
                entries = self._tts_size_load()
                key = f"{str(bid)}/{voice}/{int(rate)}"
                e = entries.get(key) or {"size": 0, "t": time.time()}
                e["size"] = int(e.get("size", 0)) + int(delta)
                e["t"] = time.time()
                entries[key] = e
                self._size_dirty = True
                self._size_bumps += 1
                if self._size_bumps % 50 == 0:
                    self._tts_size_persist()
        except Exception:
            pass

    def tts_cache_size(self, book_id=None):
        """返回音频缓存大小（字节）。

        book_id 为空 = 全部书之和；给定 book_id = 该书所有语音/语速之和。
        纯读索引，不扫盘；由启动时的后台校准 + 缓存中增量维护保证准确性。
        """
        try:
            with self._size_lock:
                entries = self._tts_size_load()
                if book_id is not None:
                    key = str(book_id) + "/"
                    total = sum(
                        int(e.get("size", 0))
                        for k, e in entries.items()
                        if k.startswith(key)
                    )
                else:
                    total = sum(int(e.get("size", 0)) for e in entries.values())
            return total
        except Exception:
            return 0

    def tts_cache_calibrate(self, book_id=None):
        """后台一次性校准音频缓存大小（扫盘）并写索引。

        返回 {bid: size}。仅用于启动迁移后 / 切换缓存目录 / 转移缓存后，
        正常使用中由增量维护保持准确，不重复扫盘。
        """
        try:
            from .storage import calibrate_tts_size
            result = calibrate_tts_size(self._tts_cache_dir or "", book_id)
            with self._size_lock:
                self._size_entries = None  # 强制下次懒加载新索引
            return result
        except Exception:
            return {}

    def tts_cache_invalidate(self, book_id=None):
        """清除某本书（或全部）的音频缓存大小索引条目（删除/转移缓存后调用）。

        条目清空后直接删除索引文件本身（连同 .tmp），避免残留几百字节的
        .tts_sizes.json 配置文件。
        """
        try:
            with self._size_lock:
                entries = self._tts_size_load()
                if book_id is not None:
                    key = str(book_id) + "/"
                    for k in [k for k in list(entries) if k.startswith(key)]:
                        entries.pop(k, None)
                else:
                    entries.clear()
                if not entries:
                    # 索引已空：删除索引文件本身，目录保持干净，不写空索引
                    from .storage import tts_size_index_path
                    root = self._tts_cache_dir or ""
                    for p in (tts_size_index_path(root),
                              tts_size_index_path(root) + ".tmp"):
                        try:
                            if os.path.exists(p):
                                os.remove(p)
                        except Exception:
                            pass
                    self._size_entries = {}  # 内存置空，避免下次 load 读到旧数据
                    self._size_dirty = False
                else:
                    self._size_dirty = True
                    self._tts_size_persist()
        except Exception:
            pass

    # ---------- 整本语音缓存 ----------

    def book_cache_status(self, book_id=None):
        cacher = self._cacher_for(book_id)
        if cacher is None:
            return None
        return cacher.status()

    def book_cache_history(self, book_id=None):
        """返回该书的历史缓存进度（读 progress.json 索引，不扫 mp3 文件）。

        即使没有正在运行/刚启动的缓存任务（如重启软件、任务已结束），
        也能返回上次缓存的 done/total/state，供下载管理器显示"已下载 xx%"。
        无任何历史进度时返回 None。
        """
        bid = str(book_id or self._book_id or "book")
        # 优先：当前有活跃 cacher（正在缓存/暂停/刚完成），直接返回真实状态，不读 progress.json
        active = self._book_cachers.get(bid)
        if active is not None:
            st = active.status()
            return {
                "state": st.get("state", "paused"),
                "done": int(st.get("done", 0)),
                "total": int(st.get("total", 0)),
                "bytes_written": int(st.get("bytes_written", 0)),
                "history": False,
            }
        root = os.path.join(self._tts_cache_dir or "", bid)
        best = None
        best_dir = None
        try:
            if os.path.isdir(root):
                for v in os.listdir(root):
                    vd = os.path.join(root, v)
                    if not os.path.isdir(vd):
                        continue
                    for r in os.listdir(vd):
                        pp = os.path.join(vd, r, "progress.json")
                        if not os.path.isfile(pp):
                            continue
                        try:
                            with open(pp, "r", encoding="utf-8") as f:
                                d = json.load(f)
                            if (best is None
                                    or (d.get("updated_at") or 0) > (best.get("updated_at") or 0)):
                                best = d
                                best_dir = os.path.join(vd, r)
                        except Exception:
                            pass
        except Exception:
            return None
        if best is None:
            return None
        # 无 active 任务时不可能真的在缓存/构建：归一化为 paused
        st = best.get("state", "paused")
        if st in ("caching", "building", "idle"):
            st = "paused"
        if st == "done":
            # 完成态校验完全在后台单线程执行；主线程只读结果集合，绝不扫描磁盘
            if best_dir in self._hist_done_downgraded:
                st = "paused"  # 后台已确认文件不足 → 降级可续传
            elif best_dir not in self._hist_done_checked:
                # 首次遇到：标记已计划校验 + 入队后台校验，本次保守返回 paused（允许用户点继续触发补齐）
                with self._hist_check_lock:
                    if best_dir not in self._hist_done_checked:
                        self._hist_done_checked.add(best_dir)
                        self._hist_check_queue.append(best_dir)
                        self._ensure_hist_check_worker()
                st = "paused"
        return {
            "state": st,
            "done": int(best.get("done", 0)),
            "total": int(best.get("total", 0)),
            "bytes_written": 0,
            "history": True,
        }

    def _ensure_hist_check_worker(self):
        """确保完成态校验后台线程在跑（单线程逐本校验，串行不拉满硬盘）。"""
        if self._hist_check_worker is not None and self._hist_check_worker.is_alive():
            return
        self._hist_check_worker = threading.Thread(target=self._hist_check_loop, daemon=True)
        self._hist_check_worker.start()

    def _hist_check_loop(self):
        """后台单线程：逐本统计 mp3 文件数，与 progress.done 对比，不足则记入降级集合。"""
        while True:
            with self._hist_check_lock:
                if not self._hist_check_queue:
                    return
                best_dir = self._hist_check_queue.pop(0)
            try:
                if not os.path.isdir(best_dir):
                    continue
                nfiles = sum(1 for f in os.listdir(best_dir) if f.endswith(".mp3"))
                # 读该目录 progress.json 的 done 作对比
                pp = os.path.join(best_dir, "progress.json")
                done = 0
                if os.path.isfile(pp):
                    try:
                        with open(pp, "r", encoding="utf-8") as f:
                            done = int(json.load(f).get("done", 0) or 0)
                    except Exception:
                        done = 0
                if done and nfiles < done * 0.98:
                    with self._hist_check_lock:
                        self._hist_done_downgraded.add(best_dir)
            except Exception:
                pass

    def chapters_cached_status(self, book, book_id):
        """返回每章是否已完全缓存的 dict {chapter_idx: bool}。

        用于「继续上次下载」：只选中未缓存的章节，避免全书重新下载的观感。
        """
        if not self._tts_cache_dir or not book or not book.chapters:
            return {}
        with self._cv:
            voice = self._edge_voice
            rate = int(self._rate)
        bid = str(book_id or "book")
        d = os.path.join(self._tts_cache_dir, bid, _sanitize_name(voice), str(rate))
        result = {}
        for ci, ch in enumerate(book.chapters):
            try:
                clean_text, cmap = ch.tts_content()
                orig_len = len(ch.content)
                clean_off = 0
                total = 0
                cached = 0
                while clean_off < len(clean_text):
                    text, nxt, _ = SpeechController._next_chunk(clean_text, clean_off)
                    if not text or nxt <= clean_off:
                        break
                    orig_off = clean_to_orig(cmap, clean_off, orig_len)
                    total += 1
                    p = os.path.join(d, f"{int(ci):04d}_{int(orig_off):08d}.mp3")
                    if os.path.exists(p) and os.path.getsize(p) > 0:
                        cached += 1
                    clean_off = nxt
                result[ci] = (total > 0 and cached >= total)
            except Exception:
                result[ci] = False
        return result

    @staticmethod
    def list_edge_voices():
        return list(EDGE_VOICES)

    @staticmethod
    def list_voices():
        """在临时线程中枚举系统语音，避免与工作线程的 COM 对象冲突。"""
        out = []

        def work():
            try:
                if pyttsx3 is None:
                    return
                e = pyttsx3.init()
                try:
                    out.extend(v.id for v in e.getProperty("voices"))
                finally:
                    try:
                        e.stop()
                    except Exception:
                        pass
            except Exception:
                pass

        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(timeout=10)
        return out

    # ---------- 控制（GUI 线程调用） ----------
    def start(self, book, chapter_idx, char_offset):
        self._ensure_thread()
        with self._cv:
            if self._closed:
                raise RuntimeError("SpeechController 已关闭")
            self._book = book
            self._ci = int(chapter_idx)
            self._off = int(char_offset)
            self._gen += 1
            self._state = "playing"
            self._cv.notify_all()
            return self._gen

    def pause(self):
        with self._cv:
            if self._state == "playing":
                self._state = "paused"
                self._cv.notify_all()
                return True
            return False

    def resume(self):
        with self._cv:
            if self._state == "paused":
                self._state = "playing"
                self._resume_counter += 1
                self._cv.notify_all()
                return True
            return False

    def stop(self):
        with self._cv:
            self._book = None
            self._state = "idle"
            self._gen += 1
            self._reset_edge_recovery_locked()
            self._cv.notify_all()
            return self._gen

    def shutdown(self, timeout=2.0):
        """有界停止朗读线程；SAPI/COM/MCI 的释放仍由工作线程完成。"""
        with self._cv:
            self._closed = True
            self._book = None
            self._state = "idle"
            self._gen += 1
            self._invalidate_edge_prime_locked()
            self._reset_edge_recovery_locked()
            self._cv.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout)))
        return thread is None or not thread.is_alive()

    def _ensure_thread(self):
        with self._cv:
            if self._closed:
                raise RuntimeError("SpeechController 已关闭")
            if self._thread is not None and self._thread.is_alive():
                return
            self._ready = threading.Event()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            ready = self._ready
        ready.wait(timeout=10)

    # ---------- 工作线程 ----------
    def _loop(self):
        if self._ready is not None:
            self._ready.set()
        try:
            while True:
                with self._cv:
                    while (
                        self._book is None
                        and not self._warm_sapi_requested
                        and not self._closed
                    ):
                        self._cv.wait()
                    if self._closed:
                        return
                    warm_sapi = self._book is None and self._warm_sapi_requested
                    if warm_sapi:
                        self._warm_sapi_requested = False
                    else:
                        book = self._book
                        ci = self._ci
                        off = self._off
                        gen = self._gen
                        self._state = "playing"
                if warm_sapi:
                    try:
                        self._ensure_engine()
                        if self._engine is not None:
                            self._sync_props()
                    except Exception:
                        # A failed warm-up is retried through the normal speak
                        # path, which already reports a structured error.
                        pass
                    continue
                try:
                    self._run_session(book, ci, off, gen)
                except Exception as e:  # pragma: no cover
                    self._post(
                        {
                            "type": "error",
                            "code": "TTS_FAILED",
                            "message": f"朗读出错：{e}",
                            "retryable": True,
                            "fallback_backend": None,
                        },
                        gen,
                    )
                    self._fail_session(gen)
        finally:
            if self._engine is not None:
                try:
                    self._engine.stop()
                except Exception:
                    pass
                try:
                    self._engine.endLoop()
                except Exception:
                    pass
                self._engine = None

    def _ensure_engine(self):
        # 仅 SAPI 后端需要 pyttsx3 引擎；Edge 后端按需初始化 pygame
        if self._engine is None and pyttsx3 is not None:
            _install_sapi_stream_events()
            # pyttsx3.init caches its engine. After a stopped sentence, create
            # a new COM voice so late events from the old one cannot be replayed.
            engine = (pyttsx3.engine.Engine("sapi5") if self._sapi_rebuild
                      else pyttsx3.init())
            engine.startLoop(useDriverLoop=False)
            self._engine = engine
            self._sapi_rebuild = False

    def _discard_sapi_engine(self):
        engine = self._engine
        if engine is None:
            return
        self._engine = None
        self._sapi_rebuild = True
        self._applied_voice = None
        self._applied_rate = None
        try:
            engine.stop()
        except Exception:
            pass
        try:
            engine.endLoop()
        except Exception:
            pass
        driver = getattr(getattr(engine, "proxy", None), "_driver", None)
        if driver is not None:
            try:
                driver._tts.EventInterests = 0
                driver._advise.disconnect()
            except Exception:
                pass

    def _sync_props(self):
        with self._cv:
            v = self._pending_voice
            r = self._rate
        if v and v != self._applied_voice:
            try:
                self._engine.setProperty("voice", v)
                self._applied_voice = v
            except Exception:
                pass
        if r and r != self._applied_rate:
            try:
                self._engine.setProperty("rate", r)
                self._applied_rate = r
            except Exception:
                pass

    def _should_stop(self, gen):
        with self._cv:
            return (
                self._closed
                or self._state == "idle"
                or self._book is None
                or self._gen != gen
            )

    def _fail_session(self, gen):
        with self._cv:
            if self._gen == gen:
                self._book = None
                self._state = "idle"
                self._cv.notify_all()

    # ---------- 朗读会话 ----------
    def _run_session(self, book, ci, off, gen):
        chapters = book.chapters
        self._edge_prefetch = None
        self._edge_fail_posted = False
        self._edge_session_fallback = False
        with self._cv:
            self._reset_edge_recovery_locked()
        try:
            while True:
                if self._should_stop(gen):
                    return
                with self._cv:
                    if self._state == "paused":
                        self._cv.wait()
                        continue
                if ci >= len(chapters):
                    self._post({"type": "finished"}, gen)
                    with self._cv:
                        self._book = None
                        self._state = "idle"
                        self._cv.notify_all()
                    return
                orig_content = chapters[ci].content
                clean_text, cmap = chapters[ci].tts_content()
                # 传入/保存的进度是「原文偏移」，朗读在「纯净文本」上切句，二者互转
                clean_off = (
                    orig_to_clean(cmap, off) if off < len(orig_content) else len(clean_text)
                )
                if clean_off >= len(clean_text):
                    ci += 1
                    off = 0
                    self._post({"type": "chapter", "chapter_idx": ci}, gen)
                    continue
                text, next_clean, sent_start = self._next_chunk(clean_text, clean_off)
                if not text:
                    off = len(orig_content)
                    continue
                # 用当前句文本的实际起始位置（跳过句前空白），而不是 clean_off
                actual_clean_off = clean_off + sent_start
                orig_off = clean_to_orig(cmap, actual_clean_off, len(orig_content))
                next_orig = clean_to_orig(cmap, next_clean, len(orig_content))
                start_event = {
                    "type": "sentence_start",
                    "chapter_idx": ci,
                    "char_offset": orig_off,
                    "char_end": next_orig,
                    "text": text,
                }
                with self._cv:
                    backend = self._backend
                    self._active_sentence_backend = backend
                if backend == "edge":
                    ok = self._speak_edge(
                        text,
                        gen,
                        ci,
                        orig_off,
                        actual_clean_off,
                        clean_text,
                        next_clean,
                        start_event,
                    )
                else:
                    ok = self._speak_sapi(text, gen, start_event)
                if not ok:
                    self._fail_session(gen)
                    return
                if self._should_stop(gen):
                    return
                if ok is self._SAPI_INTERRUPTED:
                    # SAPI stop discarded this utterance.  A fast Resume may
                    # already have restored "playing", so state alone cannot
                    # decide whether this sentence actually finished.
                    continue
                with self._cv:
                    if self._state == "paused":
                        self._cv.wait_for(
                            lambda: self._state != "paused"
                            or self._book is None
                            or self._gen != gen
                        )
                        # The audio finished before Pause reached this branch.
                        # A stopped SAPI utterance took the interrupted path
                        # above; completed audio advances after Resume.
                if self._should_stop(gen):
                    return
                self._post(
                    {"type": "sentence_done", "chapter_idx": ci, "char_offset": next_orig},
                    gen,
                )
                # 句子之间停顿（默认 0.10s），增强朗读节奏
                with self._cv:
                    gap = self._sentence_gap
                if gap > 0:
                    time.sleep(gap)
                off = next_orig
        finally:
            with self._cv:
                self._reset_edge_recovery_locked()
            if self._edge_prefetch is not None:
                try:
                    self._edge_prefetch.close()
                except Exception:
                    pass
                self._edge_prefetch = None
            self._post({"type": "stopped"}, gen)

    @staticmethod
    def _next_chunk(content, offset):
        """从 offset 起只扫描下一句，返回文本、下一偏移和句首相对偏移。

        旧实现每次先切分全部剩余正文，长章节逐句推进时累计为 O(n²)。这里保持
        ``split_sentences`` 的首句规则，但最多只检查一个朗读块，整章累计为 O(n)。
        """
        total = len(content)
        offset = max(0, min(int(offset), total))
        cursor = offset

        while cursor < total:
            # split_sentences 会先 strip，再忽略空行；这里直接跳到首个有效字符。
            while cursor < total and content[cursor].isspace():
                cursor += 1
            if cursor >= total:
                return "", total, 0

            # 句末标点或换行只在首个朗读块范围内才会影响本次结果。边界落在
            # 第 161 个字符及以后时，原规则也会先按 _MAX_CHUNK 硬切。
            limit = min(total, cursor + _MAX_CHUNK)
            match = _NEXT_BOUNDARY.search(content, cursor, limit)
            if match is not None:
                end = match.start() if match.group() == "\n" else match.end()
                text = content[cursor:end].strip()
                if not text:
                    cursor = match.end()
                    continue
                start = content.find(text, cursor, end)
                return text, start + len(text), start - offset

            if total - cursor <= _MAX_CHUNK:
                text = content[cursor:].strip()
                if not text:
                    return "", total, 0
                start = content.find(text, cursor)
                return text, start + len(text), start - offset

            cut = content.rfind("，", cursor, limit)
            if cut < cursor + _MAX_CHUNK // 2:
                cut = content.rfind(",", cursor, limit)
            if cut < cursor + _MAX_CHUNK // 2:
                cut = limit
            return content[cursor:cut], cut, cursor - offset

    # ---------- SAPI 后端 ----------
    def _speak_sapi(self, text, gen, start_event=None):
        """系统语音朗读一句，阻塞到结束或被暂停/停止打断。"""
        if not text:
            return False
        self._active_sentence_backend = "sapi"
        done = threading.Event()
        started = threading.Event()
        interrupted_by_pause = False
        with self._cv:
            resume_counter_at_start = self._resume_counter
        result = {"completed": None, "error": None}
        utterance_name = f"sapi-{gen}-{id(done)}"
        expected_stream = {"number": None}
        stream_tracking = False

        def _on_stream_queued(name=None, stream_number=None, **kw):
            if name == utterance_name:
                expected_stream["number"] = stream_number

        def _on_stream_word(stream_number=None, length=None, **kw):
            if stream_number != expected_stream["number"] or not length:
                return
            if not started.is_set():
                started.set()
                if start_event is not None:
                    self._post(dict(start_event), gen)

        def _on_stream_end(stream_number=None, completed=None, **kw):
            if stream_number == expected_stream["number"]:
                result["completed"] = completed
                done.set()

        def _on_audio_started(name=None, length=None, **kw):
            if stream_tracking:
                return
            # pyttsx3 sends SAPI StartStream on the started-word topic with
            # the utterance name before speech is audible. Its Word events
            # carry the spoken word as name and a positive character length.
            if name == utterance_name or not length:
                return
            if started.is_set():
                return
            started.set()
            if start_event is not None:
                self._post(dict(start_event), gen)

        def _on_finished(name=None, completed=None, **kw):
            if stream_tracking:
                return
            if name != utterance_name:
                return
            result["completed"] = completed
            done.set()

        def _on_error(name=None, exception=None, **kw):
            if name != utterance_name:
                return
            result["error"] = exception or RuntimeError("系统语音驱动出错")
            done.set()

        started_token = None
        finished_token = None
        error_token = None
        stream_tokens = []
        try:
            self._ensure_engine()
            if self._engine is None:
                raise RuntimeError("系统语音不可用")
            self._sync_props()
            driver = getattr(getattr(self._engine, "proxy", None), "_driver", None)
            stream_tracking = bool(
                driver is not None
                and getattr(type(driver), "_dd_stream_events_installed", False)
            )
            if stream_tracking:
                stream_tokens = [
                    self._engine.connect("sapi-stream-queued", _on_stream_queued),
                    self._engine.connect("sapi-stream-word", _on_stream_word),
                    self._engine.connect("sapi-stream-end", _on_stream_end),
                ]
            # SAPI5 emits started-utterance before asynchronous Speak and
            # StartStream before the first word. Publish the sentence only
            # from the first Word callback, closer to audible speech.
            started_token = self._engine.connect("started-word", _on_audio_started)
            finished_token = self._engine.connect("finished-utterance", _on_finished)
            error_token = self._engine.connect("error", _on_error)
            self._engine.say(text, name=utterance_name)
            while not done.is_set():
                if self._should_stop(gen):
                    self._engine.stop()  # 停止/切书：同线程打断
                    break
                with self._cv:
                    if self._state == "paused":
                        interrupted_by_pause = True
                        self._engine.stop()  # 暂停：同线程打断
                        break
                try:
                    self._engine.iterate()
                except Exception as exc:
                    raise RuntimeError("系统语音事件循环失败") from exc
                done.wait(0.02)
            if not done.is_set() and not self._should_stop(gen):
                with self._cv:
                    paused = self._state == "paused"
                if not paused and not interrupted_by_pause:
                    raise RuntimeError("系统语音未确认完成")
            with self._cv:
                paused = self._state == "paused"
                resumed_since_start = self._resume_counter != resume_counter_at_start
            if (
                done.is_set() and result["completed"] is False
                and result["error"] is None
                and (paused or resumed_since_start or interrupted_by_pause)
            ):
                # EndStream can arrive after Pause's stop but before this
                # worker observes the paused state. A fast Resume can even
                # restore playing first. The driver's incomplete result is
                # authoritative: replay this sentence instead of advancing.
                interrupted_by_pause = True
            interrupted = self._should_stop(gen) or paused or interrupted_by_pause
            if result["error"] is not None and not interrupted:
                raise RuntimeError("系统语音驱动出错") from result["error"]
            if done.is_set() and not interrupted:
                if result["completed"] is not True:
                    raise RuntimeError("系统语音未完整读完")
                if not started.is_set():
                    raise RuntimeError("系统语音未确认开始")
        except Exception as e:
            self._post(
                {
                    "type": "error",
                    "code": "SAPI_PLAYBACK_FAILED",
                    "message": f"朗读出错：{e}",
                    "retryable": True,
                    "fallback_backend": None,
                },
                gen,
            )
            return False
        finally:
            for token in (started_token, finished_token, error_token, *stream_tokens):
                if token is None:
                    continue
                try:
                    self._engine.disconnect(token)
                except Exception:
                    pass
            if interrupted_by_pause and stream_tracking:
                self._discard_sapi_engine()
        if interrupted_by_pause:
            return self._SAPI_INTERRUPTED
        return True

    # ---------- Edge 后端 ----------
    def _edge_synthesize(self, text):
        with self._cv:
            voice = self._edge_voice
            rate = self._rate
        deadline = time.monotonic() + _EDGE_SYNTH_TIMEOUT_SECONDS
        last_error = None
        for attempt in range(_EDGE_SYNTH_ATTEMPTS):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                audio = _synth_audio_governed(
                    text,
                    voice,
                    rate,
                    timeout=min(_EDGE_SYNTH_ATTEMPT_TIMEOUT_SECONDS, remaining),
                    purpose="playback",
                )
                if audio:
                    return audio
                last_error = EdgeSynthesisError(
                    {
                        "category": "no_audio",
                        "exceptionType": "EmptyAudio",
                        "statusCode": None,
                        "retryAfterSeconds": None,
                        "purpose": "playback",
                        "attempt": attempt + 1,
                    }
                )
            except Exception as exc:
                details = _edge_exception_details(
                    exc,
                    attempt=attempt + 1,
                    purpose="playback",
                )
                last_error = EdgeSynthesisError(details)
                # A service admission/rate response is authoritative. An
                # immediate second WebSocket only increases the cooldown risk;
                # let SAPI and the low-frequency recovery probe take over.
                if details.get("category") in {
                    "rate_limited",
                    "access_denied",
                    "service_unavailable",
                }:
                    break
            if attempt + 1 < _EDGE_SYNTH_ATTEMPTS:
                remaining = deadline - time.monotonic()
                if remaining <= _EDGE_RETRY_DELAY_SECONDS:
                    break
                time.sleep(_EDGE_RETRY_DELAY_SECONDS)
        if last_error is not None:
            raise last_error
        raise EdgeSynthesisError(
            {
                "category": "timeout",
                "exceptionType": "TimeoutError",
                "statusCode": None,
                "retryAfterSeconds": None,
                "purpose": "playback",
                "attempt": _EDGE_SYNTH_ATTEMPTS,
            }
        )

    def _reset_edge_recovery_locked(self):
        """Invalidate a stale recovery probe while holding ``self._cv``."""
        self._edge_recovery_token += 1
        self._edge_recovery_due_at = 0.0
        self._edge_recovery_backoff = _EDGE_RECOVERY_INITIAL_SECONDS
        self._edge_recovery_key = None
        self._edge_recovery_audio = None
        self._edge_recovery_event = None

    def _schedule_edge_recovery_locked(self):
        """Schedule the first low-frequency probe after a real Edge failure."""
        self._edge_recovery_due_at = (
            time.monotonic() + _EDGE_RECOVERY_INITIAL_SECONDS
        )
        self._edge_recovery_backoff = _EDGE_RECOVERY_INITIAL_SECONDS
        self._edge_recovery_key = None
        self._edge_recovery_audio = None
        self._edge_recovery_event = None

    def _ensure_edge_recovery_probe(self, text, gen):
        """Start at most one background connectivity probe for this session."""
        with self._cv:
            if (
                not self._edge_session_fallback
                or self._gen != gen
                or self._state == "idle"
                or self._book is None
                or self._edge_recovery_event is not None
                or self._edge_recovery_due_at <= 0
                or time.monotonic() < self._edge_recovery_due_at
            ):
                return False
            token = self._edge_recovery_token
            key = (gen, token, self._edge_voice, int(self._rate))
            ready = threading.Event()
            self._edge_recovery_key = key
            self._edge_recovery_audio = None
            self._edge_recovery_event = ready

        def probe():
            try:
                audio = self._edge_synthesize(text)
            except Exception:
                audio = None
            with self._cv:
                if key == self._edge_recovery_key:
                    self._edge_recovery_audio = audio
                    ready.set()

        threading.Thread(
            target=probe,
            name="dd-edge-recovery",
            daemon=True,
        ).start()
        return True

    def _consume_edge_recovery_result(self, gen):
        """Accept a successful probe only at the next sentence boundary."""
        with self._cv:
            ready = self._edge_recovery_event
            key = self._edge_recovery_key
            expected = (
                gen,
                self._edge_recovery_token,
                self._edge_voice,
                int(self._rate),
            )
            if ready is None or not ready.is_set() or key != expected:
                return False
            audio = self._edge_recovery_audio
            self._edge_recovery_key = None
            self._edge_recovery_audio = None
            self._edge_recovery_event = None
            if audio:
                self._edge_session_fallback = False
                self._edge_recovery_due_at = 0.0
                self._edge_recovery_backoff = _EDGE_RECOVERY_INITIAL_SECONDS
                self._edge_fail_posted = False
                return True
            delay = self._edge_recovery_backoff
            self._edge_recovery_due_at = time.monotonic() + delay
            self._edge_recovery_backoff = min(
                _EDGE_RECOVERY_MAX_SECONDS,
                max(_EDGE_RECOVERY_INITIAL_SECONDS, delay * 2),
            )
            return False

    def _speak_edge(
        self,
        text,
        gen,
        ci,
        off,
        clean_off,
        content,
        next_off,
        start_event=None,
    ):
        """Edge 语音：整本缓存命中直接播放；否则批量预取/按需合成；失败回退系统语音。"""
        recovered_from_fallback = False
        failure_details = None
        if self._edge_session_fallback:
            recovered_from_fallback = self._consume_edge_recovery_result(gen)
            if not recovered_from_fallback:
                self._ensure_edge_recovery_probe(text, gen)
                return self._speak_sapi(text, gen, start_event)
        wait_started = time.monotonic()
        buffering_posted = False

        def play_edge(audio_bytes):
            if recovered_from_fallback:
                self._post({"type": "edge_recovered", "backend": "edge"}, gen)
            return self._speak_edge_play(audio_bytes, gen, start_event)

        def report_buffering_if_needed():
            nonlocal buffering_posted
            if (
                not buffering_posted
                and time.monotonic() - wait_started >= _EDGE_BUFFERING_NOTICE_SECONDS
            ):
                buffering_posted = True
                self._post({"type": "buffering"}, gen)

        primed, prime_ready, audio, prime_prefetch, failure_details = self._edge_prime_result(
            ci, off, text
        )
        while primed and not prime_ready and not self._should_stop(gen):
            report_buffering_if_needed()
            primed, prime_ready, audio, prime_prefetch, failure_details = self._edge_prime_result(
                ci, off, text
            )
        if self._should_stop(gen):
            return False
        if prime_prefetch is not None:
            self._edge_prefetch = prime_prefetch
        cache_key = (
            self._book_id,
            self._edge_voice,
            int(self._rate),
            int(ci),
            int(off),
            text,
        )
        if not primed:
            audio = self._memory_edge_audio(cache_key) or self._cached_audio(ci, off)
        if audio:
            self._remember_edge_audio(cache_key, audio)
            if self._edge_prefetch is None:
                self._edge_prefetch = _EdgePrefetch(
                    self._edge_synthesize, content, next_off, _EdgePrefetch.MAX_AHEAD
                )
            return play_edge(audio)
        if primed:
            # The single-flight preparation already failed.  Do not perform
            # the same slow request again before falling back to SAPI.
            audio = None
        elif self._edge_prefetch is None:
            # No idle prime exists (for example, play was requested immediately
            # after binding). Generate the current sentence first so lookahead
            # can never take its connection slot, then prefetch while it plays.
            try:
                audio = self._edge_synthesize(text)
            except Exception as exc:
                audio = None
                failure_details = _edge_exception_details(exc, purpose="playback")
            if audio:
                self._edge_prefetch = _EdgePrefetch(
                    self._edge_synthesize,
                    content,
                    next_off,
                    _EdgePrefetch.MAX_AHEAD,
                )
        else:
            audio = None
            while not self._should_stop(gen):
                ready, audio = self._edge_prefetch.get_expected(
                    clean_off,
                    text,
                    timeout=0.10,
                )
                if ready:
                    if not audio:
                        failure_reader = getattr(
                            self._edge_prefetch, "failure_for", None
                        )
                        if callable(failure_reader):
                            failure_details = failure_reader(clean_off)
                    break
                report_buffering_if_needed()
                with self._cv:
                    if self._state == "paused":
                        self._cv.wait()
            if self._should_stop(gen):
                return False
        if audio:
            self._remember_edge_audio(cache_key, audio)
            return play_edge(audio)
        # A real synthesis failure keeps the existing fallback behavior, but
        # locks the remainder of this session to SAPI to prevent voice flapping.
        self._edge_session_fallback = True
        with self._cv:
            self._schedule_edge_recovery_locked()
        if not self._edge_fail_posted:
            self._edge_fail_posted = True
            self._post(
                {
                    "type": "error",
                    "code": "EDGE_OFFLINE_FALLBACK",
                    "message": "联网语音生成失败，暂时使用系统语音；网络恢复后将自动切回所选音色",
                    "retryable": True,
                    "fallback_backend": "sapi",
                    "details": dict(failure_details or {
                        "category": "unknown",
                        "exceptionType": "UnknownEdgeFailure",
                        "statusCode": None,
                        "retryAfterSeconds": None,
                        "purpose": "playback",
                    }),
                },
                gen,
            )
        if self._edge_prefetch is not None:
            try:
                self._edge_prefetch.close()
            except Exception:
                pass
            self._edge_prefetch = None
        return self._speak_sapi(text, gen, start_event)

    def _speak_edge_play(self, audio, gen, start_event=None):
        """用 Windows MCI（winmm.dll）播放预生成的 MP3，支持暂停/停止（零第三方依赖）。"""
        if not audio:
            return False
        self._active_sentence_backend = "edge"
        tmp_path = None
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp_path = tmp.name
            tmp.write(audio)
            tmp.flush()
            tmp.close()
            _mci_open(tmp_path)
            _mci_set_volume(self._volume)  # MCI 层音量（回退）
            _set_process_volume(self._volume)  # Core Audio 进程音量（主要）
            _mci_play()
            with self._cv:
                seen_resume = self._resume_counter
            if start_event is not None:
                self._post(dict(start_event), gen)
            while _mci_playing():
                with self._cv:
                    if self._state == "idle" or self._book is None or self._gen != gen:
                        _mci_stop()
                        break
                    if self._state == "paused":
                        _mci_pause()
                        self._cv.wait()
                        if self._state == "idle" or self._book is None or self._gen != gen:
                            _mci_stop()
                            break
                        _mci_resume()
                    if self._resume_counter != seen_resume:
                        seen_resume = self._resume_counter
                        # A very fast resume can happen before the worker
                        # reaches the MCI pause branch. Confirm it here too.
                        self._post({"type": "sentence_resume"}, gen)
                time.sleep(0.03)
            _mci_close()
            return True
        except Exception as e:
            self._post(
                {
                    "type": "error",
                    "code": "EDGE_PLAYBACK_FAILED",
                    "message": f"播放出错：{e}",
                    "retryable": True,
                    "fallback_backend": None,
                },
                gen,
            )
            return False
        finally:
            try:
                _mci_stop()
                _mci_close()
            except Exception:
                pass
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass


# ---------- Windows MCI 播放器（winmm.dll，替代 pygame，零依赖） ----------
_MCI_ALIAS = "dd_tts_player"


def _mci_send(cmd):
    """发送 MCI 命令，返回 (错误码, 返回文本)。"""
    buf = ctypes.create_unicode_buffer(512)
    err = ctypes.windll.winmm.mciSendStringW(cmd, buf, 512, 0)
    return err, buf.value


def _mci_open(path):
    _mci_close()
    cmd = f'open "{path}" type mpegvideo alias {_MCI_ALIAS}'
    err, _ = _mci_send(cmd)
    if err != 0:
        raise RuntimeError(f"MCI open 失败 code={err}")


def _mci_set_volume(volume_0_100):
    """设置 MCI 音量（0-100 -> 0-1000）。"""
    v = max(0, min(1000, int(volume_0_100 * 10)))
    _mci_send(f"setaudio {_MCI_ALIAS} volume to {v}")


def _set_process_volume(volume_0_100):
    """通过 Windows Core Audio 设置当前进程音量（0-100）。优先使用 pycaw。"""
    if not _HAS_PYCAW:
        return False
    try:
        volume = max(0.0, min(1.0, volume_0_100 / 100.0))
        pid = ctypes.windll.kernel32.GetCurrentProcessId()
        sessions = AudioUtilities.GetAllSessions()
        for s in sessions:
            if s.ProcessId == pid:
                vol = s._ctl.QueryInterface(ISimpleAudioVolume)
                vol.SetMasterVolume(volume, None)
                return True
        return False
    except Exception:
        return False


def _mci_play():
    err, _ = _mci_send(f"play {_MCI_ALIAS}")
    if err:
        raise RuntimeError(f"MCI play 失败 code={err}")


def _mci_pause():
    _mci_send(f"pause {_MCI_ALIAS}")


def _mci_resume():
    _mci_play()


def _mci_stop():
    _mci_send(f"stop {_MCI_ALIAS}")


def _mci_close():
    _mci_send(f"close {_MCI_ALIAS}")


def _mci_playing():
    """查询是否仍在播放/暂停中。自然播放结束返回 False。"""
    err, mode = _mci_send(f"status {_MCI_ALIAS} mode")
    if err:
        raise RuntimeError(f"MCI status 失败 code={err}")
    mode = mode.strip().lower()
    return mode in ("playing", "paused")

