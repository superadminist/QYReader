"""Portable, verified reader snapshots; restore only after the host stops writers.

The service never follows an archive path outside its staging directory. Existing
external book/model/cache files are read for backup and never changed by restore.
"""
from __future__ import annotations

import copy
from contextlib import closing
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from .feature_store import FeatureError, read_library
from .library_lock import library_write_lock
from .paths import default_data_dir


FORMAT_VERSION = 1
MAX_FILES = 100_000
MAX_BYTES = 32 * 1024**3
MANAGED_NAMES = ("library.json", "cache", "tts_cache", "models", "kokoro-model.json",
                 "offline-jobs-v1.json", "offline-audio-refs-v1.json", "reading_stats.sqlite3")
REPLACE_NAMES = MANAGED_NAMES + ("reading_stats.sqlite3-wal", "reading_stats.sqlite3-shm")
_TRANSIENT_SUFFIXES = (".tmp", ".part", ".lock", ".tmp.wav", "-wal", "-shm")


def _error(code, text):
    return FeatureError(code, text, True)


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise _error("BACKUP_CANCELLED", "操作已取消，原数据保持可用。")


def _hash(path, cancel=None):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            _check_cancel(cancel)
            result.update(block)
    return result.hexdigest()


def _copy_stream(source, target, cancel):
    for block in iter(lambda: source.read(1024**2), b""):
        _check_cancel(cancel)
        target.write(block)


def _copy_file(source, target, cancel):
    with Path(source).open("rb") as input_file, Path(target).open("wb") as output_file:
        _copy_stream(input_file, output_file, cancel)


def _is_link(path):
    path = Path(path)
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except FileNotFoundError:
        return False


def _relative(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\0" in name:
        raise _error("BACKUP_PATH_INVALID", "备份中含不安全路径。")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {".", "..", ""} or part.endswith((".", " ")) for part in name.split("/")):
        raise _error("BACKUP_PATH_INVALID", "备份中含不安全路径。")
    reserved = {"con", "prn", "aux", "nul"} | {f"{kind}{i}" for kind in ("com", "lpt") for i in range(1, 10)}
    if any(part.split(".")[0].casefold() in reserved for part in path.parts):
        raise _error("BACKUP_PATH_INVALID", "备份中含系统保留路径。")
    if path.parts[0] not in MANAGED_NAMES:
        raise _error("BACKUP_PATH_INVALID", "备份包含不支持的数据文件。")
    return path


def _write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _files(root):
    """Walk explicit roots without links, download pieces or live lock files."""
    root = Path(root)
    if _is_link(root):
        raise _error("BACKUP_SOURCE_LINK", "备份目录包含链接，请先选择普通目录。")
    if not root.exists():
        return
    for folder, dirs, names in os.walk(root, followlinks=False):
        parent = Path(folder)
        for name in list(dirs):
            if _is_link(parent / name):
                raise _error("BACKUP_SOURCE_LINK", "备份目录包含链接，未继续打包。")
            if name.startswith("."):
                dirs.remove(name)
        for name in names:
            item = parent / name
            if _is_link(item):
                raise _error("BACKUP_SOURCE_LINK", "备份目录包含链接，未继续打包。")
            if name.endswith(_TRANSIENT_SUFFIXES) or name.startswith("."):
                continue
            if item.is_file():
                yield item


class BackupService:
    def __init__(self, data_root=None, library_path=None):
        self.root = Path(data_root or default_data_dir()).resolve()
        self.library_path = Path(library_path or self.root / "library.json").resolve()
        if self.library_path.parent != self.root or self.library_path.name != "library.json":
            raise ValueError("backup requires the data root's library.json")
        self.lock = threading.RLock()
        self.jobs = {}
        self.previews = {}
        self.closed = False

    def _roots(self, data):
        settings = data.get("settings", {})
        cache = Path(settings.get("cache_dir") or self.root / "cache").resolve()
        audio = Path(settings.get("tts_cache_dir") or self.root / "tts_cache").resolve()
        models = []
        registry = self.root / "kokoro-model.json"
        if registry.is_file():
            try:
                saved = json.loads(registry.read_text(encoding="utf-8"))
                directory = Path(saved["directory"]).resolve()
                models.append((directory, "models/kokoro/v1.0/" + ("fp32" if saved.get("variant") == "fp32" else "int8")))
            except (OSError, ValueError, KeyError, TypeError):
                pass
        default_models = self.root / "models"
        return cache, audio, default_models, models

    def _inventory(self, include_audio=False, include_models=False, cancel=None):
        data = read_library(self.library_path)
        cache, audio, default_models, external_models = self._roots(data)
        sources = {}
        missing = []
        book_files = {}

        def add(path, relative):
            _check_cancel(cancel)
            relative = str(_relative(relative))
            path = Path(path)
            if _is_link(path):
                raise _error("BACKUP_SOURCE_LINK", "备份源文件不能是链接。")
            path = path.resolve()
            if path.is_file():
                sources.setdefault(relative, path)
                return relative
            return None

        if self.library_path.exists():
            add(self.library_path, "library.json")
        for bid, book in data["books"].items():
            if not isinstance(book, dict):
                continue
            if not isinstance(bid, str) or not bid or "/" in bid or "\\" in bid or ":" in bid or bid in {".", ".."}:
                raise _error("BACKUP_LIBRARY_INVALID", "书籍编号格式无效，未打包。")
            entry = {}
            parsed = add(cache / (bid + ".json"), "cache/" + bid + ".json")
            if parsed:
                entry["cache"] = parsed
            for key in ("path", "source_bak"):
                source = book.get(key)
                if isinstance(source, str) and source:
                    suffix = Path(source).suffix.lower()
                    if len(suffix) > 12 or any(c not in ".abcdefghijklmnopqrstuvwxyz0123456789" for c in suffix):
                        suffix = ".source"
                    relative = "cache/sources/" + bid + ("-original" if key == "path" else "-backup") + suffix
                    copied = add(source, relative)
                    if copied:
                        entry[key] = copied
                    else:
                        missing.append({"bookId": bid, "kind": key, "message": "源文件不可读取"})
            # Retain an existing managed source even if older metadata omits it.
            if not entry.get("path") and not entry.get("source_bak"):
                backup = next((p for p in (cache / "sources").glob(bid + ".*") if p.is_file()), None)
                if backup:
                    entry["source_bak"] = add(backup, "cache/sources/" + bid + backup.suffix.lower())
            if "cache" not in entry and not entry.get("path") and not entry.get("source_bak"):
                missing.append({"bookId": bid, "kind": "content", "message": "没有可备份的正文或源文件"})
            book_files[bid] = entry
        for name in ("reading_stats.sqlite3", "offline-jobs-v1.json", "offline-audio-refs-v1.json", "kokoro-model.json"):
            add(self.root / name, name)
        if include_audio:
            for item in _files(audio):
                add(item, "tts_cache/" + item.relative_to(audio).as_posix())
        if include_models:
            for item in _files(default_models):
                add(item, "models/" + item.relative_to(default_models).as_posix())
            for directory, relative in external_models:
                for item in _files(directory):
                    add(item, relative + "/" + item.relative_to(directory).as_posix())
        size = sum(path.stat().st_size for path in sources.values())
        return data, sources, book_files, missing, size

    def inventory(self, include_audio=False, include_models=False, cancel=None):
        with library_write_lock(self.library_path):
            data, sources, _, missing, size = self._inventory(include_audio, include_models, cancel)
        return {"bookCount": len(data["books"]), "noteCount": sum(len(x.get("bookmarks", [])) for x in data["books"].values() if isinstance(x, dict) and isinstance(x.get("bookmarks", []), list)),
                "estimatedBytes": size, "fileCount": len(sources), "missing": missing,
                "includeAudio": bool(include_audio), "includeModels": bool(include_models), "targetRoot": str(self.root)}

    @staticmethod
    def _sqlite_backup(source, destination, cancel):
        with closing(sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as original:
            with closing(sqlite3.connect(str(destination))) as target:
                original.backup(target, pages=256, progress=lambda *_: _check_cancel(cancel), sleep=.05)
                if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise _error("BACKUP_DATABASE_INVALID", "统计数据库校验失败。")
                target.commit()

    def create(self, destination, include_audio=False, include_models=False, cancel=None):
        destination = Path(destination).resolve()
        if destination.is_relative_to(self.root):
            raise _error("BACKUP_TARGET_INVALID", "请将备份保存到阅读器数据目录之外。")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name("." + destination.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with tempfile.TemporaryDirectory(prefix="qyreader-backup-") as folder, library_write_lock(self.library_path):
                stage = Path(folder)
                data, sources, book_files, missing, size = self._inventory(include_audio, include_models, cancel)
                if destination in sources.values():
                    raise _error("BACKUP_TARGET_INVALID", "备份不能覆盖书籍或模型源文件。")
                if size > MAX_BYTES or len(sources) > MAX_FILES:
                    raise _error("BACKUP_TOO_LARGE", "备份超过单包大小或文件数量限制。")
                if shutil.disk_usage(destination.parent).free < size + 16 * 1024**2 or shutil.disk_usage(stage).free < size + 16 * 1024**2:
                    raise _error("BACKUP_NO_SPACE", "磁盘空间不足，未覆盖已有备份。")
                _write_json(stage / "library.json", data)
                records = []
                for relative, source in sorted(sources.items()):
                    _check_cancel(cancel)
                    target = stage.joinpath(*PurePosixPath(relative).parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if relative == "reading_stats.sqlite3":
                        self._sqlite_backup(source, target, cancel)
                    elif relative != "library.json":
                        _copy_file(source, target, cancel)
                    records.append({"path": relative, "size": target.stat().st_size, "sha256": _hash(target, cancel)})
                if "library.json" not in sources:
                    records.append({"path": "library.json", "size": (stage / "library.json").stat().st_size, "sha256": _hash(stage / "library.json")})
                manifest = {"format": "QYReader-backup", "version": FORMAT_VERSION, "createdAt": time.time(), "files": records,
                            "bookFiles": book_files, "missing": missing, "includeAudio": bool(include_audio), "includeModels": bool(include_models)}
                with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as output:
                    output.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
                    for record in records:
                        _check_cancel(cancel)
                        with (stage / record["path"]).open("rb") as source, output.open("data/" + record["path"], "w", force_zip64=True) as target:
                            _copy_stream(source, target, cancel)
                _check_cancel(cancel)
                os.replace(temporary, destination)
                return {"saved": True, "path": str(destination), "bytes": destination.stat().st_size,
                        "complete": not missing, "missing": missing, "bookCount": len(data["books"])}
        finally:
            temporary.unlink(missing_ok=True)

    def inspect(self, archive, cancel=None):
        temporary = tempfile.TemporaryDirectory(prefix="qyreader-restore-")
        stage = Path(temporary.name)
        try:
            with zipfile.ZipFile(archive) as package:
                infos = package.infolist()
                names = [x.filename for x in infos]
                if len(infos) > MAX_FILES + 1 or len({x.casefold() for x in names}) != len(names):
                    raise _error("BACKUP_ARCHIVE_INVALID", "备份文件数量异常或含重复路径。")
                if "manifest.json" not in names or package.getinfo("manifest.json").file_size > 16 * 1024**2:
                    raise _error("BACKUP_ARCHIVE_INVALID", "备份清单缺失或过大。")
                manifest = json.loads(package.read("manifest.json"))
                if not isinstance(manifest, dict) or manifest.get("format") != "QYReader-backup" or manifest.get("version") != FORMAT_VERSION:
                    raise _error("BACKUP_VERSION_UNSUPPORTED", "备份版本暂不支持。")
                records = manifest.get("files")
                if not isinstance(records, list) or not records or len(records) > MAX_FILES:
                    raise _error("BACKUP_ARCHIVE_INVALID", "备份清单无效。")
                seen, total = set(), 0
                for record in records:
                    if not isinstance(record, dict):
                        raise _error("BACKUP_ARCHIVE_INVALID", "备份文件记录无效。")
                    relative = str(_relative(record.get("path")))
                    if relative.casefold() in seen or type(record.get("size")) is not int or record["size"] < 0 or not isinstance(record.get("sha256"), str):
                        raise _error("BACKUP_ARCHIVE_INVALID", "备份文件记录无效或重复。")
                    seen.add(relative.casefold())
                    total += record["size"]
                if total > MAX_BYTES or {"manifest.json"} | {"data/" + x["path"] for x in records} != set(names):
                    raise _error("BACKUP_ARCHIVE_INVALID", "备份包含未登记文件或体积异常。")
                if "library.json" not in seen:
                    raise _error("BACKUP_ARCHIVE_INVALID", "备份中没有书架数据。")
                if shutil.disk_usage(stage).free < total + 16 * 1024**2:
                    raise _error("BACKUP_NO_SPACE", "校验备份所需的临时空间不足。")
                for record in records:
                    _check_cancel(cancel)
                    info = package.getinfo("data/" + record["path"])
                    mode = (info.external_attr >> 16) & 0o170000
                    if info.is_dir() or mode not in (0, stat.S_IFREG) or info.flag_bits & 1 or info.file_size != record["size"]:
                        raise _error("BACKUP_ARCHIVE_INVALID", "备份包含链接、特殊文件或大小错误。")
                    target = stage.joinpath(*_relative(record["path"]).parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    copied = 0
                    with package.open(info) as source, target.open("xb") as output:
                        for block in iter(lambda: source.read(1024**2), b""):
                            _check_cancel(cancel)
                            copied += len(block)
                            if copied > record["size"]:
                                raise _error("BACKUP_ARCHIVE_INVALID", "备份展开体积异常。")
                            digest.update(block)
                            output.write(block)
                    if copied != record["size"] or digest.hexdigest() != record["sha256"]:
                        raise _error("BACKUP_HASH_MISMATCH", "备份校验值不匹配，未改动原数据。")
            data = read_library(stage / "library.json")
            if any(not isinstance(bid, str) or not bid or any(c in bid for c in ("/", "\\", ":")) or bid in {".", ".."} for bid in data["books"]):
                raise _error("BACKUP_ARCHIVE_INVALID", "备份中的书籍编号无效，未改动原数据。")
            missing = manifest.get("missing", [])
            if not isinstance(missing, list) or any(not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("bookId", "kind", "message")) for item in missing):
                raise _error("BACKUP_ARCHIVE_INVALID", "备份缺失记录格式无效。")
            book_files = manifest.get("bookFiles", {})
            if not isinstance(book_files, dict) or set(book_files) - set(data["books"]):
                raise _error("BACKUP_ARCHIVE_INVALID", "书籍文件关联无效。")
            for entry in book_files.values():
                if not isinstance(entry, dict) or set(entry) - {"cache", "path", "source_bak"}:
                    raise _error("BACKUP_ARCHIVE_INVALID", "书籍文件关联无效。")
                for name in entry.values():
                    if str(_relative(name)).casefold() not in seen:
                        raise _error("BACKUP_ARCHIVE_INVALID", "书籍文件关联未经过校验。")
            dates = []
            if (stage / "reading_stats.sqlite3").exists():
                with closing(sqlite3.connect((stage / "reading_stats.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
                    if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise _error("BACKUP_DATABASE_INVALID", "统计数据库校验失败。")
                    dates = list(db.execute("SELECT min(date),max(date) FROM daily").fetchone())
            token = uuid.uuid4().hex
            summary = {"previewId": token, "bookCount": len(data["books"]), "noteCount": sum(len(x.get("bookmarks", [])) for x in data["books"].values() if isinstance(x, dict) and isinstance(x.get("bookmarks", []), list)),
                       "statisticsRange": dates, "missing": missing, "targetRoot": str(self.root),
                       "replaceNames": list(MANAGED_NAMES), "bytes": total, "includeAudio": bool(manifest.get("includeAudio")), "includeModels": bool(manifest.get("includeModels"))}
            # The user can inspect the cost of retaining the current state
            # before confirming. Actual free space is checked again at commit.
            summary["rollbackEstimatedBytes"] = self.inventory(include_audio=True, include_models=True)["estimatedBytes"]
            with self.lock:
                for previous, _, _ in self.previews.values():
                    previous.cleanup()
                self.previews.clear()
                self.previews[token] = (temporary, manifest, summary)
            return summary
        except (zipfile.BadZipFile, KeyError, TypeError, ValueError, sqlite3.DatabaseError) as exc:
            temporary.cleanup()
            raise _error("BACKUP_ARCHIVE_INVALID", "备份损坏或数据格式无效，未改动原数据。") from exc
        except Exception:
            temporary.cleanup()
            raise

    def _relocate(self, stage, manifest):
        data = read_library(stage / "library.json")
        settings = data.setdefault("settings", {})
        settings["cache_dir"] = str(self.root / "cache")
        settings["tts_cache_dir"] = str(self.root / "tts_cache")
        settings["last_import_dir"] = ""
        for bid, book in data["books"].items():
            if not isinstance(book, dict):
                continue
            entry = manifest.get("bookFiles", {}).get(bid, {})
            source = entry.get("path") or entry.get("source_bak")
            book["path"] = str(self.root.joinpath(*_relative(source).parts)) if source else ""
            book["source_bak"] = str(self.root.joinpath(*_relative(entry.get("source_bak") or source).parts)) if source else ""
        _write_json(stage / "library.json", data)
        registry = stage / "kokoro-model.json"
        if registry.exists():
            saved = json.loads(registry.read_text(encoding="utf-8"))
            variant = "fp32" if saved.get("variant") == "fp32" else "int8"
            saved["directory"] = str(self.root / "models" / "kokoro" / "v1.0" / variant)
            _write_json(registry, saved)
        jobs = stage / "offline-jobs-v1.json"
        if jobs.exists():
            payload = json.loads(jobs.read_text(encoding="utf-8"))
            # Relative audio references survive relocation. Every task must
            # revalidate physical audio before claiming offline readiness.
            def pause(value):
                if isinstance(value, dict):
                    if "status" in value:
                        value["status"] = "paused"
                    if "state" in value and value["state"] in {"complete", "completed", "caching", "running", "queued"}:
                        value["state"] = "paused"
                    for child in value.values():
                        pause(child)
                elif isinstance(value, list):
                    for child in value:
                        pause(child)
            pause(payload)
            _write_json(jobs, payload)

    def restore(self, preview_id, cancel=None):
        """Host must quiesce writers first; old managed files form a rollback snapshot."""
        with self.lock:
            preview = self.previews.get(preview_id)
        if preview is None:
            raise _error("BACKUP_PREVIEW_EXPIRED", "恢复预览已失效，请重新选择备份。")
        temporary, manifest, summary = preview
        verified = Path(temporary.name)
        self.root.mkdir(parents=True, exist_ok=True)
        _check_cancel(cancel)
        if shutil.disk_usage(self.root).free < summary["bytes"] + summary.get("rollbackEstimatedBytes", 0) + 16 * 1024**2:
            raise _error("BACKUP_NO_SPACE", "恢复所需空间不足，原数据未改动。")
        rollback = self.root / ".restore-snapshots" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex)
        if _is_link(rollback.parent):
            raise _error("BACKUP_TARGET_INVALID", "回滚快照目录不能是链接，未执行恢复。")
        with tempfile.TemporaryDirectory(prefix=".qyreader-restore-", dir=self.root.parent) as folder:
            stage = Path(folder)
            for record in manifest["files"]:
                _check_cancel(cancel)
                relative = _relative(record["path"])
                source = verified.joinpath(*relative.parts)
                if source.stat().st_size != record["size"] or _hash(source, cancel) != record["sha256"]:
                    raise _error("BACKUP_HASH_MISMATCH", "暂存备份已变化，请重新校验。")
                target = stage.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                _copy_file(source, target, cancel)
            self._relocate(stage, manifest)
            moved, installed = [], []
            with library_write_lock(self.library_path):
                _check_cancel(cancel)
                for name in REPLACE_NAMES:
                    target = self.root / name
                    if _is_link(target):
                        raise _error("BACKUP_TARGET_INVALID", "目标数据包含链接，未执行恢复。")
                # A normal archive makes the pre-restore state selectable in
                # the same restore UI. Keep raw files as well for crash recovery.
                before_archive = stage / "before-restore.zip"
                self.create(before_archive, include_audio=True, include_models=True, cancel=cancel)
                rollback.mkdir(parents=True)
                os.replace(before_archive, rollback / before_archive.name)
                _write_json(rollback / "snapshot.json", {"version": 1, "targetRoot": str(self.root), "managedNames": list(REPLACE_NAMES), "createdAt": time.time()})
                try:
                    for name in REPLACE_NAMES:
                        _check_cancel(cancel)
                        target = self.root / name
                        if target.exists():
                            os.replace(target, rollback / name)
                            moved.append(name)
                        if (stage / name).exists():
                            os.replace(stage / name, target)
                            installed.append(name)
                    _check_cancel(cancel)
                except Exception:
                    # Move installed files back into our own staging area;
                    # restoring old names never deletes an external source.
                    for name in reversed(installed):
                        os.replace(self.root / name, stage / name)
                    for name in reversed(moved):
                        os.replace(rollback / name, self.root / name)
                    raise
        with self.lock:
            self.previews.pop(preview_id, None)
        temporary.cleanup()
        return {"restored": True, "bookCount": summary["bookCount"], "missing": summary["missing"], "rollbackDirectory": str(rollback), "rollbackArchive": str(rollback / "before-restore.zip"), "restartRequired": False}

    def start(self, kind, **kwargs):
        if kind not in {"create", "inspect", "restore", "inventory"}:
            raise _error("BACKUP_ACTION_INVALID", "备份操作无效。")
        with self.lock:
            if self.closed or any(x["status"] == "running" for x in self.jobs.values()):
                raise _error("BACKUP_BUSY", "已有备份或恢复任务，请稍候。")
            job_id = uuid.uuid4().hex
            cancel = threading.Event()
            job = {"jobId": job_id, "kind": kind, "status": "running", "result": None, "error": None, "_cancel": cancel}
            self.jobs[job_id] = job
        def run():
            try:
                result = getattr(self, kind)(**kwargs, cancel=cancel)
                with self.lock:
                    job.update(status="completed", result=result)
            except Exception as exc:
                with self.lock:
                    job.update(status="cancelled" if getattr(exc, "code", "") == "BACKUP_CANCELLED" else "error", error={"code": getattr(exc, "code", "BACKUP_FAILED"), "message": getattr(exc, "user_message", "备份操作失败，原数据保持可用。"), "retryable": True})
        thread = threading.Thread(target=run, name="reader-backup-" + kind, daemon=True)
        job["_thread"] = thread
        thread.start()
        return self.state(job_id)

    def state(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise _error("BACKUP_JOB_NOT_FOUND", "备份任务不存在。")
            return copy.deepcopy({k: v for k, v in job.items() if not k.startswith("_")})

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise _error("BACKUP_JOB_NOT_FOUND", "备份任务不存在。")
            job["_cancel"].set()
            if job["kind"] == "inspect" and job["status"] == "completed":
                preview = self.previews.pop(job["result"]["previewId"], None)
                if preview:
                    preview[0].cleanup()
        return self.state(job_id)

    def request_close(self):
        """Cancel without blocking the GUI; the host retries exit after rollback."""
        with self.lock:
            self.closed = True
            jobs = list(self.jobs.values())
            for job in jobs:
                job["_cancel"].set()
        return not any(job["_thread"].is_alive() for job in jobs)

    def close(self):
        with self.lock:
            self.closed = True
            jobs, previews = list(self.jobs.values()), list(self.previews.values())
            for job in jobs:
                job["_cancel"].set()
        for job in jobs:
            job["_thread"].join(timeout=2)
        safe = not any(job["_thread"].is_alive() for job in jobs)
        if safe:
            for temporary, _, _ in previews:
                temporary.cleanup()
        return safe
