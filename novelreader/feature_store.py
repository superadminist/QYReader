"""Additive library features. Never replace metadata from a projected UI model."""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path

from .library_lock import library_write_lock


class FeatureError(Exception):
    def __init__(self, code, message, retryable=False):
        super().__init__(message)
        self.code, self.user_message, self.retryable = code, message, retryable


def read_library(path):
    path = Path(path)
    if not path.exists():
        return {"books": {}, "settings": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("books"), dict) or not isinstance(data.get("settings", {}), dict):
            raise ValueError()
        return data
    except (OSError, ValueError, UnicodeError) as exc:
        raise FeatureError("LIBRARY_INVALID", "书架数据无法读取，未覆盖原数据。") from exc


def backup_library(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # This backup is created once, byte-for-byte, before the first feature write.
    backup = path.with_name(path.name + ".before-reader-features.bak")
    if path.exists() and not backup.exists():
        try:
            with backup.open("xb") as output, path.open("rb") as source:
                shutil.copyfileobj(source, output)
        except FileExistsError:
            pass


def save_library(path, data):
    path = Path(path)
    backup_library(path)
    temporary = path.with_name(path.name + ".features-" + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, indent=1)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def status_for(meta):
    state = meta.get("reading_status")
    if isinstance(state, str) and state in {"unread", "reading", "read"}:
        return state
    try:
        percent = float((meta.get("progress") or {}).get("percent", 0))
    except (ValueError, TypeError):
        percent = 0
    return "read" if percent >= 100 else "reading" if percent > 0 else "unread"


def advance_status(meta, percent=None):
    if meta.get("reading_status_mode") == "manual" or status_for(meta) == "read":
        return
    meta["reading_status"] = "read" if percent is not None and percent >= 100 else "reading"


def taxonomy(data):
    def terms(key):
        values = data.get(key, [])
        return [item for item in values if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("name"), str)] if isinstance(values, list) else []
    return {
        "categories": terms("categories"),
        "tags": [{"id": "to-read", "name": "待读", "builtin": True}] + [
            item for item in terms("tags") if item.get("id") != "to-read"
        ],
    }


class OrganizationService:
    def __init__(self, path):
        self.path = Path(path)

    def state(self):
        return taxonomy(read_library(self.path))

    def update(self, request):
        if not isinstance(request, dict):
            raise FeatureError("INVALID_REQUEST", "书架操作参数无效。")
        with library_write_lock(self.path):
            data = read_library(self.path)
            action = request.get("action")
            if action == "batch":
                self._apply_batch(data, request)
            elif action == "book":
                book = data["books"].get(request.get("bookId"))
                if not isinstance(book, dict):
                    raise FeatureError("BOOK_NOT_FOUND", "内容已不在书架中。")
                patch = request.get("patch")
                allowed = {"contentType", "categoryId", "tagIds", "readingStatus", "statusMode"}
                if not isinstance(patch, dict) or not patch or set(patch) - allowed:
                    raise FeatureError("INVALID_REQUEST", "书架编辑参数无效。")
                enums = {"contentType": {"", "novel", "article", "reference"}, "readingStatus": {"unread", "reading", "read"}, "statusMode": {"auto", "manual"}}
                for key, choices in enums.items():
                    if key in patch and (not isinstance(patch[key], str) or patch[key] not in choices):
                        raise FeatureError("INVALID_REQUEST", "内容类型或阅读状态无效。")
                terms = taxonomy(data)
                if "categoryId" in patch and patch["categoryId"] not in {""} | {x["id"] for x in terms["categories"]}:
                    raise FeatureError("INVALID_REQUEST", "分类不存在。")
                if "tagIds" in patch and (not isinstance(patch["tagIds"], list) or any(not isinstance(x, str) or x not in {t["id"] for t in terms["tags"]} for x in patch["tagIds"])):
                    raise FeatureError("INVALID_REQUEST", "标签不存在。")
                keys = {"contentType": "content_type", "categoryId": "category_id", "tagIds": "tag_ids", "readingStatus": "reading_status", "statusMode": "reading_status_mode"}
                book.update({keys[k]: v for k, v in patch.items()})
                if "readingStatus" in patch:
                    book["reading_status_mode"] = patch.get("statusMode", "manual")
                if patch.get("statusMode") == "auto":
                    book.pop("reading_status", None)
            elif action in {"create", "rename", "delete"}:
                kind = request.get("kind")
                if kind not in {"categories", "tags"}:
                    raise FeatureError("INVALID_REQUEST", "分类或标签类型无效。")
                terms = data.setdefault(kind, [])
                if not isinstance(terms, list) or any(not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("name"), str) for item in terms):
                    raise FeatureError("LIBRARY_INVALID", "分类数据格式无效，未覆盖。")
                identifier = request.get("id")
                if identifier == "to-read":
                    raise FeatureError("INVALID_REQUEST", "待读为内置标签。")
                name = str(request.get("name") or "").strip()
                if action != "delete" and (not name or len(name) > 50 or any(x.get("name") == name and x.get("id") != identifier for x in terms)):
                    raise FeatureError("INVALID_REQUEST", "名称不能为空、重复或超过50字。")
                if action == "create":
                    terms.append({"id": uuid.uuid4().hex, "name": name})
                else:
                    term = next((x for x in terms if x.get("id") == identifier), None)
                    if term is None:
                        raise FeatureError("INVALID_REQUEST", "分类或标签不存在。")
                    if action == "rename":
                        term["name"] = name
                    else:
                        terms.remove(term)
                        for book in data["books"].values():
                            if kind == "categories" and book.get("category_id") == identifier:
                                book["category_id"] = ""
                            elif kind == "tags" and isinstance(book.get("tag_ids"), list):
                                book["tag_ids"] = [x for x in book["tag_ids"] if x != identifier]
            else:
                raise FeatureError("INVALID_REQUEST", "书架操作无效。")
            save_library(self.path, data)
        return self.state()

    @staticmethod
    def _apply_batch(data, request):
        """Validate every target before changing any metadata in this snapshot."""
        identifiers = request.get("bookIds")
        if (not isinstance(identifiers, list) or not identifiers
                or any(not isinstance(identifier, str) or not identifier for identifier in identifiers)
                or len(set(identifiers)) != len(identifiers)):
            raise FeatureError("INVALID_REQUEST", "请选择有效内容，书籍编号不能重复。")
        books = [data["books"].get(identifier) for identifier in identifiers]
        if any(not isinstance(book, dict) for book in books):
            raise FeatureError("BOOK_NOT_FOUND", "选中内容已不在书架中，本次批量修改未保存。")
        patch = request.get("patch")
        allowed = {"categoryId", "addTagIds", "removeTagIds", "readingStatus", "statusMode"}
        if not isinstance(patch, dict) or not patch or set(patch) - allowed:
            raise FeatureError("INVALID_REQUEST", "批量修改参数无效。")
        terms = taxonomy(data)
        categories = {""} | {term["id"] for term in terms["categories"]}
        tags = {term["id"] for term in terms["tags"]}
        if "categoryId" in patch and (not isinstance(patch["categoryId"], str) or patch["categoryId"] not in categories):
            raise FeatureError("INVALID_REQUEST", "分类不存在。")
        for key in ("addTagIds", "removeTagIds"):
            if key in patch:
                values = patch[key]
                if (not isinstance(values, list) or any(not isinstance(value, str) or value not in tags for value in values)
                        or len(set(values)) != len(values)):
                    raise FeatureError("INVALID_REQUEST", "标签不存在或重复。")
        additions, removals = patch.get("addTagIds", []), patch.get("removeTagIds", [])
        if set(additions) & set(removals):
            raise FeatureError("INVALID_REQUEST", "同一标签不能同时添加和移除。")
        for key, values in (("readingStatus", {"unread", "reading", "read"}), ("statusMode", {"auto", "manual"})):
            if key in patch and (not isinstance(patch[key], str) or patch[key] not in values):
                raise FeatureError("INVALID_REQUEST", "阅读状态无效。")
        if "readingStatus" in patch and patch.get("statusMode") == "auto":
            raise FeatureError("INVALID_REQUEST", "自动状态与人工状态不能同时设置。")
        if not (set(patch) - {"addTagIds", "removeTagIds"}) and not additions and not removals:
            raise FeatureError("INVALID_REQUEST", "请选择需要修改的内容。")
        if "addTagIds" in patch or "removeTagIds" in patch:
            for book in books:
                old_tags = book.get("tag_ids", [])
                if not isinstance(old_tags, list) or any(not isinstance(value, str) for value in old_tags):
                    raise FeatureError("LIBRARY_INVALID", "选中内容的标签数据无效，本次批量修改未保存。")
        for book in books:
            if "categoryId" in patch:
                book["category_id"] = patch["categoryId"]
            if "addTagIds" in patch or "removeTagIds" in patch:
                updated_tags = [value for value in book.get("tag_ids", []) if value not in removals]
                updated_tags.extend(value for value in additions if value not in updated_tags)
                book["tag_ids"] = updated_tags
            if "readingStatus" in patch:
                book["reading_status"] = patch["readingStatus"]
                book["reading_status_mode"] = "manual"
            elif patch.get("statusMode") == "manual":
                book["reading_status"] = status_for(book)
                book["reading_status_mode"] = "manual"
            if patch.get("statusMode") == "auto":
                book["reading_status_mode"] = "auto"
                book.pop("reading_status", None)

    def active(self, book_id):
        with library_write_lock(self.path):
            data = read_library(self.path)
            book = data["books"].get(book_id)
            if isinstance(book, dict) and status_for(book) == "unread" and book.get("reading_status_mode") != "manual":
                advance_status(book)
                save_library(self.path, data)
