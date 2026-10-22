"""Background chapter preparation over the existing Edge/Kokoro synthesis queues.

Only this service owns job progress; it never binds or controls a reader session.
Manifests use relative cache paths so they can travel with data backups.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import tts_engine
from .book_loader import BookContent, parse_book
from .feature_store import FeatureError, read_library
from .textproc import clean_to_orig
from .kokoro_service import normal_cache_path

INDEX_VERSION = 1
SPLIT_VERSION = "next-chunk-v1"
MIN_FREE_BYTES = 32 * 1024**2


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class _EdgeFiles(tts_engine.WholeBookCacher):
    """Reuse the established cache layout; managed writes also prove their text."""
    def __init__(self, book, bid, root, voice, rate):
        super().__init__(book, bid, root, voice, rate, preset_tasks=[])

    def write_verified(self, chapter, offset, text, audio):
        path = Path(self._path(chapter, offset))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        metadata = Path(str(path) + ".meta.json")
        try:
            temporary.write_bytes(audio)
            # Remove stale proof before publishing a changed audio file. A reader
            # sees no managed audio until the matching proof is atomically ready.
            _atomic_json(metadata, {"version": INDEX_VERSION, "textSha256": _hash(text.encode("utf-8")), "audioSha256": "pending"})
            os.replace(temporary, path)
            _atomic_json(metadata, {"version": INDEX_VERSION, "textSha256": _hash(text.encode("utf-8")), "audioSha256": _hash(audio)})
        finally:
            temporary.unlink(missing_ok=True)
        return path


class OfflineCacheService:
    """One bounded background job runner. Public queries never scan audio files."""
    def __init__(self, data_root, kokoro=None, *, cache_root=None, notify=None,
                 loader=None, protected=None, edge_synth=None, disk_free=None):
        self.root = Path(data_root)
        self.library_path = self.root / "library.json"
        settings = read_library(self.library_path).get("settings", {})
        self.cache_root = Path(cache_root or settings.get("tts_cache_dir") or self.root / "tts_cache").resolve()
        self.index = self.root / "offline-jobs-v1.json"
        self.kokoro = kokoro
        self.notify = notify or (lambda state: None)
        self.loader = loader or self._load_book
        # A host can conservatively protect all files of its active book.
        self.protected = protected or (lambda job: False)
        self.edge_synth = edge_synth or (lambda text, voice, rate: tts_engine._synth_audio_governed(text, voice, rate, purpose="cache"))
        self.disk_free = disk_free or (lambda path: shutil.disk_usage(path).free)
        self.lock = threading.RLock()
        self.closed = False
        self._last_persist = 0
        self.jobs = {}
        self._books = {}
        self._queue = queue.Queue()
        self._load_index()
        self.thread = threading.Thread(target=self._loop, name="offline-chapters", daemon=True)
        self.thread.start()

    def _load_index(self):
        if not self.index.is_file():
            return
        try:
            payload = json.loads(self.index.read_text(encoding="utf-8"))
            if payload.get("version") != INDEX_VERSION or not isinstance(payload.get("jobs"), dict):
                raise ValueError()
            for identifier, job in payload["jobs"].items():
                if not isinstance(job, dict) or job.get("jobId") != identifier or not isinstance(job.get("tasks", []), list):
                    raise ValueError()
                # A restart has not verified on-disk hashes or current book text.
                job.update(state="paused", verified=False, operation="prepare", revision=0,
                           message="重启后待校验，继续时检查正文和音频。", error=None)
                self.jobs[identifier] = job
        except (OSError, ValueError, TypeError):
            raise FeatureError("CACHE_INDEX_INVALID", "离线章节清单损坏，未覆盖原文件。")

    def _load_book(self, book_id):
        data = read_library(self.library_path)
        meta = data["books"].get(book_id)
        if not isinstance(meta, dict):
            raise FeatureError("BOOK_NOT_FOUND", "书籍已不在书架中。")
        cache = Path(data.get("settings", {}).get("cache_dir") or self.root / "cache") / (book_id + ".json")
        if cache.is_file():
            try:
                return BookContent.from_dict(json.loads(cache.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError):
                pass
        for key in ("path", "source_bak"):
            if isinstance(meta.get(key), str) and Path(meta[key]).is_file():
                return parse_book(meta[key])
        raise FeatureError("BOOK_CONTENT_UNAVAILABLE", "正文无法读取，未创建离线音频。")

    def create(self, book_id, chapter_indices, backend, voice_id, rate, *, book=None):
        if not isinstance(book_id, str) or not book_id or any(x in book_id for x in ("/", "\\", ":")) or book_id in {".", ".."}:
            raise FeatureError("INVALID_REQUEST", "书籍编号无效。")
        if backend not in {"edge", "kokoro"}:
            raise FeatureError("CACHE_UNSUPPORTED", "SAPI不支持预生成，可继续实时朗读。")
        if type(rate) is not int or not 80 <= rate <= 400:
            raise FeatureError("INVALID_REQUEST", "语速须为80–400的整数。")
        if not isinstance(chapter_indices, list) or not chapter_indices or any(type(i) is not int or i < 0 for i in chapter_indices):
            raise FeatureError("INVALID_REQUEST", "请明确选择至少一个章节。")
        if backend == "edge" and voice_id not in {entry[0] for entry in tts_engine.EDGE_VOICES}:
            raise FeatureError("VOICE_INVALID", "Edge音色无效。")
        if backend == "kokoro" and (self.kokoro is None or voice_id not in {v["id"] for v in self.kokoro.voices()}):
            raise FeatureError("VOICE_INVALID", "Kokoro音色无效。")
        chapters = sorted(set(chapter_indices))
        model = dict(self.kokoro.package) if backend == "kokoro" else {}
        config = {"bookId": book_id, "chapterIndices": chapters, "backend": backend, "voiceId": voice_id, "rate": rate,
                  "modelId": model.get("modelId", ""), "modelSha256": model.get("sha256", ""), "splitVersion": SPLIT_VERSION, "cacheVersion": INDEX_VERSION}
        key = _hash(json.dumps(config, sort_keys=True).encode())
        with self.lock:
            self._ensure_open()
            existing = next((j for j in self.jobs.values() if j.get("configKey") == key and j["state"] in {"queued", "preparing", "running"}), None)
            if existing is not None:
                return self._public(existing)
            # Reuse a stable same-configuration job, but always revalidate content.
            job = next((j for j in self.jobs.values() if j.get("configKey") == key), None)
            if job is None:
                identifier = uuid.uuid4().hex
                job = {**config, "jobId": identifier, "configKey": key, "tasks": [], "fingerprint": "", "total": 0, "done": 0, "bytes": 0, "chapters": [], "revision": 0}
                self.jobs[identifier] = job
            if book is not None:
                self._books[job["jobId"]] = book
            return self._schedule_locked(job, "prepare")

    def state(self):
        with self.lock:
            return {"jobs": [self._public(job) for job in self.jobs.values()], "cacheRoot": str(self.cache_root)}

    def control(self, job_id, command, *, confirmed=False):
        with self.lock:
            self._ensure_open()
            job = self.jobs.get(job_id)
            if job is None:
                raise FeatureError("CACHE_JOB_NOT_FOUND", "离线任务不存在。")
            if command in {"pause", "cancel"}:
                job["revision"] += 1
                job.update(state="paused" if command == "pause" else "cancelled", message="已暂停" if command == "pause" else "已取消，保留已生成片段。", error=None)
                self._persist_locked()
                self._notify_locked(job)
                return self._public(job)
            if command not in {"resume", "verify", "repair", "clean"}:
                raise FeatureError("INVALID_REQUEST", "缓存操作无效。")
            if command == "clean" and confirmed is not True:
                raise FeatureError("CACHE_CONFIRM_REQUIRED", "请先确认清理此任务的已选章节音频。")
            if job["state"] in {"queued", "preparing", "running"}:
                if command in {"resume", "repair"}:
                    return self._public(job)
                raise FeatureError("CACHE_BUSY", "请先暂停任务，再校验或清理。")
            return self._schedule_locked(job, "clean" if command == "clean" else "verify" if command == "verify" else "prepare")

    def _schedule_locked(self, job, operation):
        job["revision"] += 1
        job.update(state="queued", operation=operation, verified=False, error=None, message="等待后台处理。")
        self._persist_locked()
        self._queue.put((job["jobId"], job["revision"]))
        self._notify_locked(job)
        return self._public(job)

    def _public(self, job):
        return {key: value for key, value in job.items() if key not in {"tasks", "revision", "operation", "configKey"}}

    def _persist_locked(self):
        _atomic_json(self.index, {"version": INDEX_VERSION, "jobs": self.jobs})
        self._last_persist = time.monotonic()

    def _notify_locked(self, job):
        self.notify(self._public(job))

    def _valid(self, job, revision):
        with self.lock:
            return not self.closed and job["revision"] == revision and job["state"] not in {"paused", "cancelled", "error"}

    def _loop(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            identifier, revision = item
            with self.lock:
                job = self.jobs[identifier]
                if not self._valid(job, revision):
                    continue
                job["state"] = "preparing"
                self._notify_locked(job)
            try:
                if job["operation"] == "clean":
                    self._clean(job, revision)
                else:
                    self._run(job, revision)
            except Exception as exc:
                with self.lock:
                    if self._valid(job, revision):
                        code = getattr(exc, "code", "CACHE_FAILED")
                        paused = isinstance(exc, tts_engine.EdgeSynthesisError) or code in {"CACHE_NO_SPACE", "MODEL_CHANGED", "MODEL_NOT_READY"}
                        message = "服务繁忙，已暂停，可稍后继续。" if isinstance(exc, tts_engine.EdgeSynthesisError) else getattr(exc, "user_message", "离线准备失败，请检查磁盘或重试。")
                        job.update(state="paused" if paused else "error", verified=False, message=message,
                                   error={"code": "EDGE_BUSY" if isinstance(exc, tts_engine.EdgeSynthesisError) else code, "message": message, "retryable": True})
                        self._persist_locked()
                        self._notify_locked(job)

    def _model_matches(self, job):
        if job["backend"] != "kokoro":
            return
        if self.kokoro.package["sha256"] != job["modelSha256"]:
            raise FeatureError("MODEL_CHANGED", "模型已切换，已暂停旧模型的章节任务。", True)
        if self.kokoro.snapshot()["status"] != "ready":
            raise FeatureError("MODEL_NOT_READY", "请先下载或导入Kokoro模型包。", True)

    def _safe_path(self, name):
        if not isinstance(name, str) or not name or "\\" in name or ":" in name:
            raise FeatureError("CACHE_PATH_INVALID", "缓存路径无效，未修改文件。")
        path = (self.cache_root / name).resolve()
        if not path.is_relative_to(self.cache_root) or path == self.cache_root or path.suffix not in {".mp3", ".wav"}:
            raise FeatureError("CACHE_PATH_INVALID", "缓存路径超出选定目录，未修改文件。")
        return path

    def _task_path(self, job, task):
        chapter, offset, text = task.get("chapterIndex"), task.get("offset"), task.get("text")
        if type(chapter) is not int or chapter not in job["chapterIndices"] or type(offset) is not int or offset < 0 or not isinstance(text, str) or task.get("textSha256") != _hash(text.encode("utf-8")):
            raise FeatureError("CACHE_PATH_INVALID", "离线片段与所选章节不匹配，未修改文件。")
        if job["backend"] == "edge":
            expected = f"{job['bookId']}/{tts_engine._sanitize_name(job['voiceId'])}/{job['rate']}/{chapter:04d}_{offset:08d}.mp3"
        else:
            expected = normal_cache_path(self.kokoro.cache_path_for(text, job["voiceId"], job["rate"], package={"modelId": job["modelId"], "sha256": job["modelSha256"]})).relative_to(self.cache_root).as_posix()
        if task.get("path") != expected:
            raise FeatureError("CACHE_PATH_INVALID", "缓存路径与任务参数不匹配，未修改文件。")
        return self._safe_path(expected)

    def _task_valid(self, task, job):
        backend = job["backend"]
        path = self._task_path(job, task)
        try:
            if not path.is_file() or path.stat().st_size <= (44 if backend == "kokoro" else 0):
                return False
            digest = _hash(path.read_bytes())
            if backend == "edge":
                metadata = json.loads(Path(str(path) + ".meta.json").read_text(encoding="utf-8"))
                return metadata.get("textSha256") == task["textSha256"] and metadata.get("audioSha256") == digest
            return task.get("audioSha256") == digest
        except (OSError, ValueError, KeyError):
            return False

    def _tasks_for(self, job, book):
        if any(index >= len(book.chapters) for index in job["chapterIndices"]):
            raise FeatureError("INVALID_REQUEST", "所选章节已不存在，请重新选择。")
        tasks = []
        edge = _EdgeFiles(book, job["bookId"], str(self.cache_root), job["voiceId"], job["rate"]) if job["backend"] == "edge" else None
        fingerprint = hashlib.sha256()
        for index in job["chapterIndices"]:
            chapter = book.chapters[index]
            fingerprint.update(json.dumps([index, chapter.title, chapter.content], ensure_ascii=False).encode("utf-8"))
            clean, mapping = chapter.tts_content()
            offset = 0
            while offset < len(clean):
                text, following, relative = tts_engine.SpeechController._next_chunk(clean, offset)
                if following <= offset or not text:
                    break
                original_offset = clean_to_orig(mapping, offset + relative, len(chapter.content))
                path = Path(edge._path(index, original_offset)) if edge else self.kokoro.cache_path_for(text, job["voiceId"], job["rate"], package={"modelId": job["modelId"], "sha256": job["modelSha256"]})
                tasks.append({"chapterIndex": index, "offset": original_offset, "text": text, "textSha256": _hash(text.encode("utf-8")),
                              "path": normal_cache_path(path).relative_to(self.cache_root).as_posix(), "done": False, "bytes": 0})
                offset = following
        return tasks, fingerprint.hexdigest(), edge

    def _progress_locked(self, job):
        chapters = {index: {"index": index, "total": 0, "done": 0} for index in job["chapterIndices"]}
        unique = {}
        done = 0
        for task in job["tasks"]:
            chapter = chapters[task["chapterIndex"]]
            chapter["total"] += 1
            if task.get("done"):
                done += 1
                chapter["done"] += 1
                unique[task["path"]] = task.get("bytes", 0)
        job.update(total=len(job["tasks"]), done=done, bytes=sum(unique.values()), chapters=list(chapters.values()))

    def _retain_job_paths(self, job, revision, *, existing_only=False):
        # Keep the generation check and persistent reference write indivisible
        # with close/pause. In particular, a slow path scan may finish after close.
        with self.lock:
            if not self._valid(job, revision):
                return False
            grouped = {index: [] for index in job["chapterIndices"]}
            for task in job["tasks"]:
                path = self._task_path(job, task)
                if not existing_only or path.is_file():
                    grouped[task["chapterIndex"]].append(path)
            for index, paths in grouped.items():
                self.kokoro.retain_paths(paths, job["jobId"] + ":" + str(index))
            return True

    def _invalidate_edge_conflicts_locked(self, job, task):
        for other in self.jobs.values():
            if other is job or other["backend"] != "edge":
                continue
            conflicts = [entry for entry in other.get("tasks", []) if entry.get("path") == task["path"] and entry.get("textSha256") != task["textSha256"]]
            if conflicts:
                for entry in conflicts:
                    entry.update(done=False, bytes=0)
                other.update(verified=False, message="正文已变更，此任务需重新校验。")
                if other["state"] == "completed":
                    other["state"] = "paused"
                self._progress_locked(other)
                self._notify_locked(other)

    def _run(self, job, revision):
        book = self._books.get(job["jobId"]) or self.loader(job["bookId"])
        tasks, fingerprint, edge = self._tasks_for(job, book)
        old_tasks = {(task.get("chapterIndex"), task.get("offset"), task.get("textSha256")): task for task in job.get("tasks", [])}
        for task in tasks:
            previous = old_tasks.get((task["chapterIndex"], task["offset"], task["textSha256"]))
            if previous and previous.get("path") == task["path"]:
                task["audioSha256"] = previous.get("audioSha256")
        with self.lock:
            if not self._valid(job, revision):
                return
            job.update(tasks=tasks, fingerprint=fingerprint, bookTitle=book.title, state="running")
            self._progress_locked(job)
            self._persist_locked()
        if job["backend"] == "kokoro" and not self._retain_job_paths(job, revision):
            return
        chapter_progress = {chapter["index"]: chapter for chapter in job["chapters"]}
        counted_paths = set()
        for task_index, task in enumerate(tasks):
            if not self._valid(job, revision):
                return
            valid = self._task_valid(task, job)
            if not valid and job["operation"] != "verify":
                self._model_matches(job)
                with self.lock:
                    if not self._valid(job, revision):
                        return
                    self.cache_root.mkdir(parents=True, exist_ok=True)
                if self.disk_free(self.cache_root) < MIN_FREE_BYTES + max(1024 * 1024, len(task["text"]) * 12000):
                    raise FeatureError("CACHE_NO_SPACE", "磁盘空间不足，已暂停并保留完成片段。", True)
                if edge is not None:
                    audio = self.edge_synth(task["text"], job["voiceId"], job["rate"])
                    if not audio:
                        raise FeatureError("CACHE_EMPTY_AUDIO", "未生成音频，请稍后重试。", True)
                    with self.lock:
                        if not self._valid(job, revision):
                            return
                        self._invalidate_edge_conflicts_locked(job, task)
                        path = edge.write_verified(task["chapterIndex"], task["offset"], task["text"], audio)
                else:
                    path = self._safe_path(task["path"])
                    with self.lock:
                        if not self._valid(job, revision):
                            return
                        with self.kokoro.lock:
                            self._model_matches(job)
                            future = self.kokoro.request(task["text"], job["voiceId"], job["rate"], priority=30)
                    while True:
                        if not self._valid(job, revision):
                            return  # Never cancel a Future also used by foreground speech.
                        self._model_matches(job)
                        try:
                            result = future.result(timeout=.1)
                            break
                        except concurrent.futures.TimeoutError:
                            continue
                    self._model_matches(job)
                    if normal_cache_path(result) != normal_cache_path(path):
                        raise FeatureError("MODEL_CHANGED", "模型或缓存目录已改变，任务已暂停。", True)
                digest = _hash(path.read_bytes())
                with self.lock:
                    if not self._valid(job, revision):
                        return
                    task["audioSha256"] = digest
                valid = self._task_valid(task, job)
                if not valid:
                    raise FeatureError("CACHE_WRITE_FAILED", "音频落盘校验失败，未计为完成。", True)
            with self.lock:
                if not self._valid(job, revision):
                    return
                task["done"] = valid
                task["bytes"] = self._safe_path(task["path"]).stat().st_size if valid else 0
                if valid:
                    job["done"] += 1
                    chapter_progress[task["chapterIndex"]]["done"] += 1
                    if task["path"] not in counted_paths:
                        counted_paths.add(task["path"])
                        job["bytes"] += task["bytes"]
                if (task_index + 1) % 20 == 0 or time.monotonic() - self._last_persist > 5:
                    self._persist_locked()
                self._notify_locked(job)
        with self.lock:
            if self._valid(job, revision):
                complete = job["done"] == job["total"]
                job.update(state="completed" if complete else "paused", verified=complete,
                           message="所选章节已校验，可使用该音色和语速播放。" if complete else "存在缺失或旧缓存，点击检查并补齐。")
                self._persist_locked()
                self._notify_locked(job)

    def _clean(self, job, revision):
        with self.lock:
            if not self._valid(job, revision):
                return
            if self.protected(self._public(job)):
                raise FeatureError("CACHE_IN_USE", "此书正在播放或暂停，请先停止后再清理。", True)
            # Validate every path before the first mutation.
            paths = {task["path"]: self._task_path(job, task) for task in job.get("tasks", [])}
            if job["backend"] == "kokoro":
                for index in job["chapterIndices"]:
                    self.kokoro.release_reference(job["jobId"] + ":" + str(index))
            deleted, shared = 0, 0
            for name, path in paths.items():
                if not self._valid(job, revision):
                    return
                referenced = any(other["jobId"] != job["jobId"] and any(t.get("path") == name for t in other.get("tasks", [])) for other in self.jobs.values())
                if referenced or job["backend"] == "kokoro" and self.kokoro.is_retained(path):
                    shared += 1
                    continue
                if path.is_file():
                    if self.protected(self._public(job)):
                        if job["backend"] == "kokoro":
                            self._retain_job_paths(job, revision, existing_only=True)
                        raise FeatureError("CACHE_IN_USE", "播放已开始，已停止清理剩余文件。", True)
                    try:
                        path.unlink()
                        Path(str(path) + ".meta.json").unlink(missing_ok=True)
                        deleted += 1
                    except PermissionError:
                        shared += 1  # Windows may have opened the audio file.
            job.update(state="cancelled", tasks=[], total=0, done=0, bytes=0, chapters=[], verified=False,
                       message=f"已清理{deleted}个文件，保留{shared}个共享或占用文件。", error=None)
            self._persist_locked()
            self._notify_locked(job)

    def _ensure_open(self):
        if self.closed:
            raise FeatureError("CACHE_CLOSED", "离线任务服务已关闭。")

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                for job in self.jobs.values():
                    if job["state"] in {"queued", "preparing", "running"}:
                        job["revision"] += 1
                        job.update(state="paused", verified=False, message="应用已关闭，继续时重新校验。")
                self._persist_locked()
                self._queue.put(None)
        self.thread.join(timeout=.5)
        return not self.thread.is_alive()
