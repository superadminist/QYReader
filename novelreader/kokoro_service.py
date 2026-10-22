"""Pinned, optional Kokoro v1.0 INT8 package and bounded sentence synthesis."""
from __future__ import annotations

import concurrent.futures
import hashlib
import itertools
import json
import os
import queue
import shutil
import tarfile
import threading
import time
import urllib.request
import urllib.parse
import uuid
from collections import OrderedDict
from pathlib import Path, PurePosixPath

from .feature_store import FeatureError


MODEL_ID = "kokoro-v1.0-int8"
MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-int8-multi-lang-v1_0.tar.bz2"
MODEL_BYTES = 132303094
MODEL_SHA256 = "4c3052abaa60943a341f193888cf6abd68787dae6ab8ae5c925a706caa247e4e"
MODEL_PACKAGES = {
    "int8": {"modelId": MODEL_ID, "url": MODEL_URL, "bytes": MODEL_BYTES, "sha256": MODEL_SHA256},
    "fp32": {"modelId": "kokoro-v1.0-fp32",
             "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-multi-lang-v1_0.tar.bz2",
             "bytes": 349906910,
             "sha256": "c5f7e2d2caf082bc1d20fb70334a61d99d20b484500aad32e7cf84c128ea3298"},
}
CACHE_BYTES = 500 * 1024**2
VOICES = [(45, "zf_xiaobei", "晓北"), (46, "zf_xiaoni", "晓妮"), (47, "zf_xiaoxiao", "晓晓"), (48, "zf_xiaoyi", "晓伊"),
          (49, "zm_yunjian", "云健"), (50, "zm_yunxi", "云希"), (51, "zm_yunxia", "云夏"), (52, "zm_yunyang", "云扬")]


class _SentenceExecutor:
    """One producer, with foreground promotion and a non-blocking shutdown."""
    def __init__(self):
        self.jobs = queue.PriorityQueue()
        self.lock = threading.Lock()
        self.sequence = itertools.count()
        self.pending = {}
        self.closed = False
        self.thread = threading.Thread(target=self._run, name="kokoro-synthesis", daemon=True)
        self.thread.start()

    def submit(self, function, *args, priority=0):
        with self.lock:
            if self.closed:
                raise RuntimeError("离线合成服务已关闭。")
            future = concurrent.futures.Future()
            sequence = next(self.sequence)
            self.pending[future] = (priority, sequence, function, args)
            self.jobs.put((priority, sequence, future))
            return future

    def promote(self, future, priority):
        with self.lock:
            job = self.pending.get(future)
            if job is None or future.done() or priority >= job[0]:
                return
            sequence = next(self.sequence)
            self.pending[future] = (priority, sequence, job[2], job[3])
            self.jobs.put((priority, sequence, future))

    def _run(self):
        while True:
            priority, sequence, future = self.jobs.get()
            if future is None:
                return
            with self.lock:
                job = self.pending.get(future)
                if job is None or job[:2] != (priority, sequence):
                    continue  # A promoted job replaces its earlier queue entry.
                self.pending.pop(future)
            _, _, function, args = job
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(function(*args))
            except Exception as exc:
                future.set_exception(exc)

    def shutdown(self, wait=False, cancel_futures=True):
        with self.lock:
            self.closed = True
            pending = list(self.pending)
            self.pending.clear()
            self.jobs.put((-1, next(self.sequence), None))
        if cancel_futures:
            for future in pending:
                future.cancel()
        if wait:
            self.thread.join()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _cache_path(path):
    """Native WAV writer and Python both need the Windows extended prefix."""
    path = Path(path).absolute()
    if os.name != "nt":
        return path
    value = str(path)
    if value.startswith("\\\\?\\"):
        return path
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


def normal_cache_path(path):
    """Compare standard/extended Windows spellings as the same physical path."""
    value = str(path)
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value).resolve()


def safe_extract(archive, destination, cancelled=lambda: False):
    """Manual extraction also works on Python 3.10: never trust extractall."""
    destination = Path(destination).resolve()
    with tarfile.open(archive, "r:bz2") as source:
        members = source.getmembers()
        if len(members) > 10000 or sum(x.size for x in members) > 2 * 1024**3:
            raise FeatureError("MODEL_ARCHIVE_INVALID", "模型包展开体积或文件数量异常。")
        if shutil.disk_usage(destination.parent).free < sum(x.size for x in members) + 64 * 1024**2:
            raise FeatureError("MODEL_NO_SPACE", "磁盘空间不足，请选择其他模型目录。")
        seen = set()
        for member in members:
            if cancelled():
                raise FeatureError("MODEL_CANCELLED", "已取消模型安装。", True)
            name = member.name
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or not (member.isfile() or member.isdir()):
                raise FeatureError("MODEL_ARCHIVE_INVALID", "模型包包含不安全路径或链接。")
            target = destination.joinpath(*path.parts).resolve()
            if destination != target and destination not in target.parents:
                raise FeatureError("MODEL_ARCHIVE_INVALID", "模型包路径越界。")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                key = os.path.normcase(str(target))
                if key in seen:
                    raise FeatureError("MODEL_ARCHIVE_INVALID", "模型包包含重复文件。")
                seen.add(key)
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as input_file, target.open("xb") as output:
                    shutil.copyfileobj(input_file, output)


def create_engine(directory, threads=2):
    import sherpa_onnx
    directory = Path(directory)
    models = list(directory.glob("*.onnx"))
    required = ["voices.bin", "tokens.txt", "lexicon-zh.txt", "lexicon-us-en.txt"]
    if len(models) != 1 or any(not (directory / name).is_file() for name in required) or not (directory / "espeak-ng-data").is_dir() or not (directory / "dict").is_dir():
        raise FeatureError("MODEL_FILES_INVALID", "模型包缺少必要文件。")
    model = sherpa_onnx.OfflineTtsModelConfig(
        kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
            model=str(models[0]), voices=str(directory / "voices.bin"), tokens=str(directory / "tokens.txt"),
            data_dir=str(directory / "espeak-ng-data"),
            lexicon=",".join(str(directory / x) for x in ["lexicon-us-en.txt", "lexicon-zh.txt"])),
        num_threads=threads, provider="cpu", debug=False)
    rules = ",".join(str(directory / x) for x in ["date-zh.fst", "phone-zh.fst", "number-zh.fst"] if (directory / x).is_file())
    config = sherpa_onnx.OfflineTtsConfig(model=model, rule_fsts=rules, max_num_sentences=1)
    if not config.validate():
        raise FeatureError("MODEL_FILES_INVALID", "模型配置校验失败。")
    engine = sherpa_onnx.OfflineTts(config)
    # The pinned 2026-09 package appends em_santa at 53; original IDs 0-52
    # (including all eight Chinese voices) are explicitly unchanged in its README.
    if engine.num_speakers != 54:
        raise FeatureError("MODEL_VERSION_INVALID", "模型speaker数量不符合Kokoro v1.0。")
    return engine


class KokoroService:
    def __init__(self, data_root, notify=lambda state: None, *, threads=2):
        self.data_root = Path(data_root)
        self.registry = self.data_root / "kokoro-model.json"
        self.variant = "int8"
        self.directory = self.data_root / "models" / "kokoro" / "v1.0" / "int8"
        if self.registry.is_file():
            try:
                saved = json.loads(self.registry.read_text(encoding="utf-8"))
                self.directory = Path(saved["directory"])
                self.variant = saved.get("variant", "int8")
                if self.variant not in MODEL_PACKAGES:
                    self.variant = "int8"
            except (OSError, ValueError, KeyError):
                pass
        self.notify = notify
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.thread = None
        self.executor = _SentenceExecutor()
        self.threads = max(1, int(threads))
        self.engine = None
        self.model_epoch = 0
        self.load_future = None
        self.futures = OrderedDict()
        self._synthesis_context = threading.local()
        self._cache_bytes = None
        self.retention_path = self.data_root / "offline-audio-refs-v1.json"
        self._retained_refs = {}
        self._retained_paths_cache = None
        self._retention_invalid = False
        try:
            if self.retention_path.is_file():
                saved_refs = json.loads(self.retention_path.read_text(encoding="utf-8"))
                if saved_refs.get("version") != 1 or not isinstance(saved_refs.get("refs"), dict):
                    raise ValueError("invalid retention index")
                self._retained_refs = saved_refs["refs"]
        except (OSError, ValueError, TypeError):
            self._retention_invalid = True
        self._cache_root = self.data_root / "tts_cache"
        try:
            settings = json.loads((self.data_root / "library.json").read_text(encoding="utf-8")).get("settings", {})
            custom_cache = settings.get("tts_cache_dir") if isinstance(settings, dict) else None
            if isinstance(custom_cache, str) and custom_cache.strip():
                self._cache_root = Path(custom_cache.strip())
        except (OSError, ValueError, AttributeError):
            pass
        self.cache = _cache_path(self._cache_root / self.package["modelId"])
        self._retained_paths_locked()
        self.state = {"modelId": self.package["modelId"], "variant": self.variant,
                      "status": "ready" if (self.directory / "manifest.json").is_file() else "missing",
                      "jobId": "", "downloadedBytes": 0, "totalBytes": self.package["bytes"], "progressPercent": 0,
                      "installedBytes": 0, "directory": str(self.directory), "message": "", "error": None}
        if self.state["status"] == "ready":
            try:
                self.state["installedBytes"] = json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))["installedBytes"]
            except (OSError, ValueError, KeyError):
                self.state["status"] = "error"

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    @property
    def package(self):
        return MODEL_PACKAGES[self.variant]

    def _state(self, **patch):
        with self.lock:
            self.state.update(patch)
            state = dict(self.state)
        self.notify(state)

    def voices(self):
        ready = self.snapshot()["status"] == "ready"
        return [{"id": f"kokoro:v1.0:{name}", "label": name_cn + " · Kokoro离线", "backend": "kokoro", "requiresNetwork": False,
                 "speakerId": sid, "modelId": self.package["modelId"], "available": ready} for sid, name, name_cn in VOICES]

    def set_variant(self, variant):
        if not isinstance(variant, str) or variant not in MODEL_PACKAGES:
            raise FeatureError("MODEL_VARIANT_INVALID", "请选择INT8或普通版模型。")
        if self.thread and self.thread.is_alive():
            raise FeatureError("MODEL_BUSY", "请先取消或等待模型安装。")
        if variant == self.variant:
            return self.snapshot()
        return self._select_directory(self.directory.parent / variant, variant)

    def set_directory(self, path):
        if self.thread and self.thread.is_alive():
            raise FeatureError("MODEL_BUSY", "请先取消或等待模型安装。")
        directory = Path(path).resolve() / "kokoro" / "v1.0" / self.variant
        directory.parent.mkdir(parents=True, exist_ok=True)
        probe = directory.parent / (".write-check-" + uuid.uuid4().hex)
        probe.write_bytes(b"")
        probe.unlink()
        return self._select_directory(directory, self.variant)

    def _select_directory(self, directory, variant):
        self.data_root.mkdir(parents=True, exist_ok=True)
        temporary = self.registry.with_suffix(".tmp")
        temporary.write_text(json.dumps({"directory": str(directory), "variant": variant}), encoding="utf-8")
        os.replace(temporary, self.registry)
        with self.lock:
            self.cancel_pending()
            self.engine = None
            self.model_epoch += 1
            self.load_future = None
            self.futures.clear()
            self.directory = directory
            self.variant = variant
            self.cache = _cache_path(self._cache_root / self.package["modelId"])
            self._cache_bytes = None
        installed = 0
        if (directory / "manifest.json").is_file():
            try:
                installed = int(json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["installedBytes"])
            except (OSError, ValueError, KeyError):
                pass
        self._state(directory=str(directory), modelId=self.package["modelId"], variant=variant, totalBytes=self.package["bytes"],
                    status="ready" if installed else "missing", installedBytes=installed,
                    progressPercent=0, downloadedBytes=0, jobId="", message="", error=None)
        return self.snapshot()

    def start(self, imported_path=None):
        if self.thread and self.thread.is_alive():
            raise FeatureError("MODEL_BUSY", "模型任务正在进行。")
        self.cancel_event.clear()
        self._state(jobId=uuid.uuid4().hex, status="verifying" if imported_path else "downloading", error=None, message="")
        self.thread = threading.Thread(target=self._install, args=(imported_path,), name="kokoro-model-install", daemon=True)
        self.thread.start()
        return self.snapshot()

    def cancel(self):
        self.cancel_event.set()
        return self.snapshot()

    def _download(self, target):
        expected_bytes = self.package["bytes"]
        for attempt in range(4):
            if self.cancel_event.is_set():
                raise FeatureError("MODEL_CANCELLED", "已取消下载。", True)
            try:
                offset = target.stat().st_size if target.exists() else 0
                headers = {"User-Agent": "QYReader-model-download"}
                if offset:
                    headers["Range"] = f"bytes={offset}-"
                if offset == expected_bytes:
                    return
                with urllib.request.urlopen(urllib.request.Request(self.package["url"], headers=headers), timeout=15) as response:
                    host = urllib.parse.urlparse(response.url).hostname
                    if host not in {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}:
                        raise FeatureError("MODEL_URL_INVALID", "下载跳转地址不受信任。")
                    resume = response.status == 206 and response.headers.get("Content-Range", "").startswith(f"bytes {offset}-")
                    if not resume:
                        offset = 0
                    with target.open("ab" if resume else "wb") as output:
                        last_notice = 0
                        while True:
                            if self.cancel_event.is_set():
                                raise FeatureError("MODEL_CANCELLED", "已取消下载。", True)
                            block = response.read(256 * 1024)
                            if not block:
                                break
                            output.write(block)
                            offset += len(block)
                            if offset > expected_bytes:
                                raise FeatureError("MODEL_SIZE_INVALID", "下载大小不符合固定模型版本。")
                            if time.monotonic() - last_notice > .2:
                                last_notice = time.monotonic()
                                self._state(downloadedBytes=offset, progressPercent=offset / expected_bytes * 100)
                    if offset != expected_bytes:
                        raise OSError("download incomplete")
                return
            except FeatureError:
                raise
            except OSError:
                if attempt == 3:
                    raise FeatureError("MODEL_DOWNLOAD_FAILED", "下载失败，可重试或手动导入官方模型包。", True)
                self._state(message=f"下载连接中断，正在重试（{attempt + 1}/3）")
                if self.cancel_event.wait([1, 3, 10][attempt]):
                    raise FeatureError("MODEL_CANCELLED", "已取消下载。", True)

    def _install(self, imported_path):
        stage = None
        try:
            parent = self.directory.parent
            parent.mkdir(parents=True, exist_ok=True)
            package = Path(imported_path) if imported_path else parent / (self.package["modelId"] + ".tar.bz2.part")
            if not imported_path:
                if shutil.disk_usage(parent).free < self.package["bytes"] + 512 * 1024**2:
                    raise FeatureError("MODEL_NO_SPACE", "磁盘空间不足，请选择其他目录。")
                self._download(package)
            self._state(status="verifying", downloadedBytes=package.stat().st_size, progressPercent=100)
            if package.stat().st_size != self.package["bytes"] or file_hash(package) != self.package["sha256"]:
                if not imported_path:
                    package.unlink(missing_ok=True)
                raise FeatureError("MODEL_CHECKSUM_FAILED", "模型包SHA256不匹配，请导入所选版本的官方v1.0包。", True)
            self._state(status="extracting")
            stage = parent / (".kokoro-stage-" + uuid.uuid4().hex)
            stage.mkdir()
            safe_extract(package, stage, self.cancel_event.is_set)
            roots = list(stage.iterdir())
            if len(roots) != 1 or not roots[0].is_dir():
                raise FeatureError("MODEL_ARCHIVE_INVALID", "模型包目录结构无效。")
            candidate = roots[0]
            self._state(status="loading")
            engine = create_engine(candidate)
            files = {str(x.relative_to(candidate)).replace("\\", "/"): {"size": x.stat().st_size, "sha256": file_hash(x)} for x in candidate.rglob("*") if x.is_file()}
            manifest = {"modelId": self.package["modelId"], "archiveSha256": self.package["sha256"], "installedBytes": sum(x["size"] for x in files.values()), "files": files}
            (candidate / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            if self.cancel_event.is_set():
                raise FeatureError("MODEL_CANCELLED", "已取消安装。", True)
            # Never replace an existing installation in place. Keep it recoverable.
            previous = None
            if self.directory.exists():
                previous = parent / (self.variant + "-previous-" + uuid.uuid4().hex)
                os.replace(self.directory, previous)
            try:
                os.replace(candidate, self.directory)
            except OSError:
                if previous is not None:
                    os.replace(previous, self.directory)
                raise
            with self.lock:
                self.engine = None  # Re-open with final paths; dictionary paths moved.
                self.model_epoch += 1
                self.load_future = None
                self.futures.clear()
            self._state(status="ready", installedBytes=manifest["installedBytes"], error=None, message="模型已就绪，可完全离线朗读。")
            if not imported_path:
                package.unlink(missing_ok=True)
        except Exception as exc:
            self._state(status="cancelled" if self.cancel_event.is_set() else "error",
                        error={"code": getattr(exc, "code", "MODEL_INSTALL_FAILED"), "message": getattr(exc, "user_message", str(exc)), "retryable": True},
                        message=getattr(exc, "user_message", str(exc)))
        finally:
            if stage is not None and stage.parent == self.directory.parent and stage.name.startswith(".kokoro-stage-"):
                shutil.rmtree(stage, ignore_errors=True)

    def preload(self):
        """Validate/load on the producer without generating or playing text."""
        with self.lock:
            if self.state["status"] != "ready" or self.engine is not None:
                return None
            if self.load_future is None or self.load_future.cancelled() or (
                self.load_future.done() and self.load_future.exception() is not None
            ):
                self.load_future = self.executor.submit(self._load_engine, priority=20)
                self.load_future.add_done_callback(lambda future, epoch=self.model_epoch: self._generation_finished(future, epoch))
            return self.load_future

    def request(self, text, voice, rate, *, priority=0):
        sid = next((sid for sid, name, _ in VOICES if voice == f"kokoro:v1.0:{name}"), None)
        if sid is None:
            raise FeatureError("VOICE_INVALID", "Kokoro音色无效。")
        with self.lock:
            key = hashlib.sha256(f"{self.package['sha256']}|{sid}|{rate}|v1|{text}".encode("utf-8")).hexdigest()
            # Prepared WAV playback needs no model load. A backup may contain
            # retained audio without the optional large model package.
            path = self.cache / (key + ".wav")
            cached = path.is_file() and path.stat().st_size > 44
            if self.snapshot()["status"] != "ready" and not cached:
                raise FeatureError("MODEL_NOT_READY", "请先下载或导入所选版本的Kokoro v1.0模型包。", True)
            existing = self.futures.get(key)
            if existing is not None and (existing.cancelled() or existing.done() and existing.exception() is not None):
                self.futures.pop(key)
            elif existing is not None and existing.done() and not existing.result().is_file():
                self.futures.pop(key)
            elif existing is not None:
                self.executor.promote(existing, priority)
                self.futures.move_to_end(key)
                return existing
            if key not in self.futures:
                while len(self.futures) >= 32:
                    oldest = next((k for k, f in self.futures.items() if f.done()), None)
                    if oldest is None:
                        break
                    self.futures.pop(oldest)
                path = self.cache / (key + ".wav")
                if path.is_file() and path.stat().st_size > 44:
                    # A replay must not wait behind unrelated native inference.
                    os.utime(path, None)
                    ready = concurrent.futures.Future()
                    ready.set_result(path)
                    self.futures[key] = ready
                else:
                    context = (self.model_epoch, self.cache)
                    self.futures[key] = self.executor.submit(self._generate_for_model, context, key, text, sid, rate, priority=priority)
                self.futures[key].add_done_callback(lambda future, epoch=self.model_epoch: self._generation_finished(future, epoch))
            return self.futures[key]

    def _generation_finished(self, future, epoch=None):
        if future.cancelled():
            return
        error = future.exception()
        if getattr(error, "code", "") == "MODEL_FILES_INVALID":
            with self.lock:
                if epoch is not None and epoch != self.model_epoch:
                    return
                self._state(status="error", message=error.user_message,
                            error={"code": error.code, "message": error.user_message, "retryable": True})

    def _load_engine(self, expected_epoch=None):
        with self.lock:
            if expected_epoch is not None and expected_epoch != self.model_epoch:
                raise FeatureError("MODEL_CHANGED", "模型已变更，已丢弃旧的生成请求。", True)
            directory = self.directory
            epoch = self.model_epoch
            engine = self.engine
        if engine is None:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            for name, expected in manifest["files"].items():
                item = directory / name
                if not item.is_file() or item.stat().st_size != expected["size"] or file_hash(item) != expected["sha256"]:
                    raise FeatureError("MODEL_FILES_INVALID", "模型文件损坏，请重新导入模型包。", True)
            engine = create_engine(directory, self.threads)
            with self.lock:
                if directory != self.directory or epoch != self.model_epoch:
                    raise FeatureError("MODEL_CHANGED", "模型目录已变更，请重试。", True)
                self.engine = engine
        return engine

    def _generate_for_model(self, context, key, text, sid, rate):
        self._synthesis_context.model = context
        try:
            with self.lock:
                if context[0] != self.model_epoch:
                    raise FeatureError("MODEL_CHANGED", "模型已变更，已丢弃旧的生成请求。", True)
            return self._generate(key, text, sid, rate)
        finally:
            del self._synthesis_context.model

    def _generate(self, key, text, sid, rate):
        with self.lock:
            epoch, cache = getattr(self._synthesis_context, "model", (self.model_epoch, self.cache))
            if epoch != self.model_epoch:
                raise FeatureError("MODEL_CHANGED", "模型已变更，已丢弃旧的生成请求。", True)
        cache.mkdir(parents=True, exist_ok=True)
        path = cache / (key + ".wav")
        if path.is_file() and path.stat().st_size > 44:
            os.utime(path, None)
            return path
        engine = self._load_engine(expected_epoch=epoch)
        audio = engine.generate(text, sid=sid, speed=max(.4, min(2., rate / 200)))
        if not len(audio.samples):
            raise FeatureError("KOKORO_EMPTY_AUDIO", "该句未生成音频，请重试。", True)
        import sherpa_onnx
        temporary = path.with_suffix(".tmp.wav")
        if not sherpa_onnx.write_wave(str(temporary), audio.samples, audio.sample_rate):
            raise FeatureError("KOKORO_WRITE_FAILED", "无法写入离线音频，请检查缓存目录的权限和磁盘空间。", True)
        os.replace(temporary, path)
        self._trim_cache(path)
        return path

    def _trim_cache(self, path):
        with self.lock:
            if path.parent != self.cache:
                return  # A finished old-model request stays in its original cache.
            self._trim_cache_locked(path)

    def cache_path_for(self, text, voice, rate, *, package=None):
        sid = next((sid for sid, name, _ in VOICES if voice == f"kokoro:v1.0:{name}"), None)
        if sid is None:
            raise FeatureError("VOICE_INVALID", "Kokoro音色无效。")
        with self.lock:
            package = package or self.package
            key = hashlib.sha256(f"{package['sha256']}|{sid}|{rate}|v1|{text}".encode("utf-8")).hexdigest()
            return _cache_path(self._cache_root / package["modelId"] / (key + ".wav"))

    def _retained_paths_locked(self):
        if self._retained_paths_cache is not None:
            return self._retained_paths_cache
        root = normal_cache_path(self._cache_root)
        paths = set()
        for entries in self._retained_refs.values():
            if not isinstance(entries, list):
                self._retention_invalid = True
                continue
            for name in entries:
                if not isinstance(name, str):
                    self._retention_invalid = True
                    continue
                candidate = (root / name).resolve()
                if candidate.is_relative_to(root) and candidate.suffix == ".wav":
                    paths.add(candidate)
                else:
                    self._retention_invalid = True
        self._retained_paths_cache = paths
        return paths

    def retain_path(self, path, reference):
        """Persist a chapter reference before requesting synthesis (also pins in-flight files)."""
        with self.lock:
            root = normal_cache_path(self._cache_root)
            candidate = normal_cache_path(path)
            if not candidate.is_relative_to(root) or candidate.suffix != ".wav":
                raise FeatureError("CACHE_PATH_INVALID", "离线音频路径无效。")
            if self._retention_invalid:
                raise FeatureError("CACHE_INDEX_INVALID", "保留章节索引损坏，未覆盖。")
            retained = self._retained_paths_locked()
            previously_retained = candidate in retained
            values = self._retained_refs.setdefault(str(reference), [])
            relative = candidate.relative_to(root).as_posix()
            if relative not in values:
                values.append(relative)
                self._save_retention_locked()
                retained.add(candidate)
                if not previously_retained and self._cache_bytes is not None and candidate.is_file():
                    self._cache_bytes = max(0, self._cache_bytes - candidate.stat().st_size)

    def retain_paths(self, paths, reference):
        """Replace one chapter's exact references without deleting released audio."""
        with self.lock:
            root = normal_cache_path(self._cache_root)
            candidates = {normal_cache_path(path) for path in paths}
            if any(not path.is_relative_to(root) or path.suffix != ".wav" for path in candidates):
                raise FeatureError("CACHE_PATH_INVALID", "离线音频路径无效。")
            if self._retention_invalid:
                raise FeatureError("CACHE_INDEX_INVALID", "保留章节索引损坏，未覆盖。")
            before = set(self._retained_paths_locked())
            self._retained_refs[str(reference)] = sorted(path.relative_to(root).as_posix() for path in candidates)
            self._retained_paths_cache = None
            after = self._retained_paths_locked()
            self._save_retention_locked()
            if self._cache_bytes is not None:
                released = sum(path.stat().st_size for path in before - after if path.is_file())
                retained = sum(path.stat().st_size for path in after - before if path.is_file())
                self._cache_bytes = max(0, self._cache_bytes + released - retained)

    def release_reference(self, reference):
        with self.lock:
            if self._retention_invalid:
                raise FeatureError("CACHE_INDEX_INVALID", "保留章节索引损坏，未覆盖。")
            before = set(self._retained_paths_locked())
            self._retained_refs.pop(str(reference), None)
            self._retained_paths_cache = None
            after = self._retained_paths_locked()
            self._save_retention_locked()
            if self._cache_bytes is not None:
                self._cache_bytes += sum(path.stat().st_size for path in before - after if path.is_file())

    def is_retained(self, path):
        with self.lock:
            retained = self._retained_paths_locked()
            return self._retention_invalid or normal_cache_path(path) in retained

    def _save_retention_locked(self):
        self.data_root.mkdir(parents=True, exist_ok=True)
        temporary = self.retention_path.with_name(self.retention_path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps({"version": 1, "refs": self._retained_refs}, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.retention_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _trim_cache_locked(self, path):
        # Retained chapters have an independent lifetime. Only temporary bytes count
        # toward the 500 MiB budget; never evict a retained or pending chapter file.
        retained = self._retained_paths_locked()
        if self._retention_invalid:
            return
        if self._cache_bytes is None:
            self._cache_bytes = sum(item.stat().st_size for item in self.cache.glob("*.wav") if item.is_file() and normal_cache_path(item) not in retained)
        elif normal_cache_path(path) not in retained:
            self._cache_bytes += path.stat().st_size
        if self._cache_bytes <= CACHE_BYTES:
            return
        temporary = [item for item in self.cache.glob("*.wav") if item.is_file() and normal_cache_path(item) not in retained]
        size = sum(item.stat().st_size for item in temporary)
        protected = {normal_cache_path(f.result()) for f in self.futures.values()
                     if f.done() and not f.cancelled() and f.exception() is None}
        for item in sorted(temporary, key=lambda x: x.stat().st_mtime):
            if size <= CACHE_BYTES:
                break
            if item != path and normal_cache_path(item) not in protected:
                try:
                    removed_bytes = item.stat().st_size
                    item.unlink()
                    size -= removed_bytes
                except OSError:
                    pass
        self._cache_bytes = size

    def close(self):
        self.cancel_event.set()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def cancel_pending(self):
        with self.lock:
            for future in self.futures.values():
                if not future.running():
                    future.cancel()
            self.futures = OrderedDict((key, future) for key, future in self.futures.items() if future.running())
