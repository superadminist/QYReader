"""Pinned, optional Kokoro v1.0 INT8 package and bounded sentence synthesis."""
from __future__ import annotations

import concurrent.futures
import hashlib
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
from pathlib import Path, PurePosixPath

from .feature_store import FeatureError


MODEL_ID = "kokoro-v1.0-int8"
MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-int8-multi-lang-v1_0.tar.bz2"
MODEL_BYTES = 132303094
MODEL_SHA256 = "4c3052abaa60943a341f193888cf6abd68787dae6ab8ae5c925a706caa247e4e"
VOICES = [(45, "zf_xiaobei", "晓北"), (46, "zf_xiaoni", "晓妮"), (47, "zf_xiaoxiao", "晓晓"), (48, "zf_xiaoyi", "晓伊"),
          (49, "zm_yunjian", "云健"), (50, "zm_yunxi", "云希"), (51, "zm_yunxia", "云夏"), (52, "zm_yunyang", "云扬")]


class _SentenceExecutor:
    """One daemon producer: a native inference must never hold application exit."""
    def __init__(self):
        self.jobs = queue.Queue()
        self.closed = False
        self.thread = threading.Thread(target=self._run, name="kokoro-synthesis", daemon=True)
        self.thread.start()

    def submit(self, function, *args):
        if self.closed:
            raise RuntimeError("离线合成服务已关闭。")
        future = concurrent.futures.Future()
        self.jobs.put((future, function, args))
        return future

    def _run(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            future, function, args = job
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(function(*args))
            except Exception as exc:
                future.set_exception(exc)

    def shutdown(self, wait=False, cancel_futures=True):
        self.closed = True
        if cancel_futures:
            while True:
                try:
                    job = self.jobs.get_nowait()
                except queue.Empty:
                    break
                if job is not None:
                    job[0].cancel()
        self.jobs.put(None)
        if wait:
            self.thread.join()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


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
    def __init__(self, data_root, notify=lambda state: None):
        self.data_root = Path(data_root)
        self.registry = self.data_root / "kokoro-model.json"
        self.directory = self.data_root / "models" / "kokoro" / "v1.0" / "int8"
        if self.registry.is_file():
            try:
                saved = json.loads(self.registry.read_text(encoding="utf-8"))
                self.directory = Path(saved["directory"])
            except (OSError, ValueError, KeyError):
                pass
        self.notify = notify
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.thread = None
        self.executor = _SentenceExecutor()
        self.engine = None
        self.futures = {}
        self.cache = self.data_root / "tts_cache" / "kokoro-v1.0-int8"
        try:
            settings = json.loads((self.data_root / "library.json").read_text(encoding="utf-8")).get("settings", {})
            custom_cache = settings.get("tts_cache_dir") if isinstance(settings, dict) else None
            if isinstance(custom_cache, str) and custom_cache.strip():
                self.cache = Path(custom_cache.strip()) / "kokoro-v1.0-int8"
        except (OSError, ValueError, AttributeError):
            pass
        self.state = {"modelId": MODEL_ID, "status": "ready" if (self.directory / "manifest.json").is_file() else "missing",
                      "jobId": "", "downloadedBytes": 0, "totalBytes": MODEL_BYTES, "progressPercent": 0,
                      "installedBytes": 0, "directory": str(self.directory), "message": "", "error": None}
        if self.state["status"] == "ready":
            try:
                self.state["installedBytes"] = json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))["installedBytes"]
            except (OSError, ValueError, KeyError):
                self.state["status"] = "error"

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def _state(self, **patch):
        with self.lock:
            self.state.update(patch)
            state = dict(self.state)
        self.notify(state)

    def voices(self):
        ready = self.snapshot()["status"] == "ready"
        return [{"id": f"kokoro:v1.0:{name}", "label": name_cn + " · Kokoro离线", "backend": "kokoro", "requiresNetwork": False,
                 "speakerId": sid, "modelId": MODEL_ID, "available": ready} for sid, name, name_cn in VOICES]

    def set_directory(self, path):
        if self.thread and self.thread.is_alive():
            raise FeatureError("MODEL_BUSY", "请先取消或等待模型安装。")
        directory = Path(path).resolve() / "kokoro" / "v1.0" / "int8"
        directory.parent.mkdir(parents=True, exist_ok=True)
        probe = directory.parent / (".write-check-" + uuid.uuid4().hex)
        probe.write_bytes(b"")
        probe.unlink()
        self.data_root.mkdir(parents=True, exist_ok=True)
        temporary = self.registry.with_suffix(".tmp")
        temporary.write_text(json.dumps({"directory": str(directory)}), encoding="utf-8")
        os.replace(temporary, self.registry)
        with self.lock:
            self.engine = None
            self.futures.clear()
            self.directory = directory
        installed = 0
        if (directory / "manifest.json").is_file():
            try:
                installed = int(json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["installedBytes"])
            except (OSError, ValueError, KeyError):
                pass
        self._state(directory=str(directory), status="ready" if installed else "missing", installedBytes=installed,
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
        for attempt in range(4):
            if self.cancel_event.is_set():
                raise FeatureError("MODEL_CANCELLED", "已取消下载。", True)
            try:
                offset = target.stat().st_size if target.exists() else 0
                headers = {"User-Agent": "QYReader-model-download"}
                if offset:
                    headers["Range"] = f"bytes={offset}-"
                if offset == MODEL_BYTES:
                    return
                with urllib.request.urlopen(urllib.request.Request(MODEL_URL, headers=headers), timeout=15) as response:
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
                            if offset > MODEL_BYTES:
                                raise FeatureError("MODEL_SIZE_INVALID", "下载大小不符合固定模型版本。")
                            if time.monotonic() - last_notice > .2:
                                last_notice = time.monotonic()
                                self._state(downloadedBytes=offset, progressPercent=offset / MODEL_BYTES * 100)
                    if offset != MODEL_BYTES:
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
            package = Path(imported_path) if imported_path else parent / "kokoro-v1.0-int8.tar.bz2.part"
            if not imported_path:
                if shutil.disk_usage(parent).free < MODEL_BYTES + 256 * 1024**2:
                    raise FeatureError("MODEL_NO_SPACE", "磁盘空间不足，请选择其他目录。")
                self._download(package)
            self._state(status="verifying", downloadedBytes=package.stat().st_size, progressPercent=100)
            if package.stat().st_size != MODEL_BYTES or file_hash(package) != MODEL_SHA256:
                if not imported_path:
                    package.unlink(missing_ok=True)
                raise FeatureError("MODEL_CHECKSUM_FAILED", "模型包SHA256不匹配，请重新下载官方INT8 v1.0包。", True)
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
            manifest = {"modelId": MODEL_ID, "archiveSha256": MODEL_SHA256, "installedBytes": sum(x["size"] for x in files.values()), "files": files}
            (candidate / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            if self.cancel_event.is_set():
                raise FeatureError("MODEL_CANCELLED", "已取消安装。", True)
            # Never replace an existing installation in place. Keep it recoverable.
            previous = None
            if self.directory.exists():
                previous = parent / ("int8-previous-" + uuid.uuid4().hex)
                os.replace(self.directory, previous)
            try:
                os.replace(candidate, self.directory)
            except OSError:
                if previous is not None:
                    os.replace(previous, self.directory)
                raise
            with self.lock:
                self.engine = None  # Re-open with final paths; dictionary paths moved.
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

    def request(self, text, voice, rate):
        sid = next((sid for sid, name, _ in VOICES if voice == f"kokoro:v1.0:{name}"), None)
        if sid is None:
            raise FeatureError("VOICE_INVALID", "Kokoro音色无效。")
        key = hashlib.sha256(f"{MODEL_SHA256}|{sid}|{rate}|v1|{text}".encode("utf-8")).hexdigest()
        with self.lock:
            if self.snapshot()["status"] != "ready":
                raise FeatureError("MODEL_NOT_READY", "请先下载或导入Kokoro v1.0 INT8模型包。", True)
            existing = self.futures.get(key)
            if existing is not None and (existing.cancelled() or existing.done() and existing.exception() is not None):
                self.futures.pop(key)
            elif existing is not None and existing.done() and not existing.result().is_file():
                self.futures.pop(key)
            if key not in self.futures:
                if len(self.futures) >= 32:
                    self.futures = {k: f for k, f in self.futures.items() if not f.done()}
                self.futures[key] = self.executor.submit(self._generate, key, text, sid, rate)
                self.futures[key].add_done_callback(self._generation_finished)
            return self.futures[key]

    def _generation_finished(self, future):
        if future.cancelled():
            return
        error = future.exception()
        if getattr(error, "code", "") == "MODEL_FILES_INVALID":
            self._state(status="error", message=error.user_message,
                        error={"code": error.code, "message": error.user_message, "retryable": True})

    def _generate(self, key, text, sid, rate):
        import sherpa_onnx
        self.cache.mkdir(parents=True, exist_ok=True)
        path = self.cache / (key + ".wav")
        if path.is_file() and path.stat().st_size > 44:
            os.utime(path, None)
            return path
        if self.engine is None:
            manifest = json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))
            for name, expected in manifest["files"].items():
                item = self.directory / name
                if not item.is_file() or item.stat().st_size != expected["size"] or file_hash(item) != expected["sha256"]:
                    raise FeatureError("MODEL_FILES_INVALID", "模型文件损坏，请重新导入模型包。", True)
            self.engine = create_engine(self.directory)
        audio = self.engine.generate(text, sid=sid, speed=max(.4, min(2., rate / 200)))
        if not len(audio.samples):
            raise FeatureError("KOKORO_EMPTY_AUDIO", "该句未生成音频，请重试。", True)
        temporary = path.with_suffix(".tmp.wav")
        sherpa_onnx.write_wave(str(temporary), audio.samples, audio.sample_rate)
        os.replace(temporary, path)
        files = sorted(self.cache.glob("*.wav"), key=lambda x: x.stat().st_mtime)
        size = sum(x.stat().st_size for x in files)
        for item in files:
            if size <= 500 * 1024**2:
                break
            if item != path:
                try:
                    size -= item.stat().st_size
                    item.unlink()
                except OSError:
                    pass  # Windows may be playing this file.
        return path

    def close(self):
        self.cancel_event.set()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def cancel_pending(self):
        with self.lock:
            for future in self.futures.values():
                if not future.running():
                    future.cancel()
            self.futures = {key: future for key, future in self.futures.items() if future.running()}
