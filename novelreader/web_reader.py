# -*- coding: utf-8 -*-
"""Bounded HTTP fetch and article extraction; never execute page scripts."""
from __future__ import annotations

import gzip
import re
import socket
import threading
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_PAGE_BYTES = 10 * 1024 * 1024
FETCH_TIMEOUT = 15
FETCH_DEADLINE = 45


class WebReaderError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class WebReadCancelled(Exception):
    pass


@dataclass(frozen=True)
class WebArticle:
    url: str
    title: str
    text: str


def validate_web_url(value: str) -> str:
    url = str(value or "").strip()
    try:
        parts = urlsplit(url)
        port = parts.port
        valid = (
            len(url) <= 8192 and parts.scheme.lower() in ("http", "https")
            and parts.hostname and parts.username is None and parts.password is None
            and not re.search(r"[\s\x00-\x1f\x7f\\]", url)
            and (port is None or 0 < port <= 65535)
        )
    except ValueError:
        valid = False
    if not valid:
        raise WebReaderError("WEB_INVALID_URL", "请输入完整的 http:// 或 https:// 网页地址。")
    return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path or "/", parts.query, ""))


class _WebRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, validate_web_url(newurl))


def extract_article(raw: bytes, url: str, charset: str | None = None) -> WebArticle:
    from bs4 import BeautifulSoup
    from .book_loader import normalize_body

    soup = BeautifulSoup(raw, "html.parser", from_encoding=charset)
    title_node = soup.find("meta", attrs={"property": "og:title"})
    title = str(title_node.get("content", "")).strip() if title_node else ""
    heading = soup.find("h1")
    title = title or (heading.get_text(" ", strip=True) if heading else "")
    title = title or (soup.title.get_text(" ", strip=True) if soup.title else "")
    title = title or urlsplit(url).hostname or "网页正文"
    for node in soup.select(
        "script, style, noscript, template, nav, aside, footer, header, form, "
        "button, iframe, svg, canvas, img, [hidden], [aria-hidden='true']"
    ):
        node.decompose()
    for node in soup.find_all(style=True):
        if node.attrs and re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", node["style"], re.I):
            node.decompose()
    candidates = soup.select(
        "article, main, [role='main'], #content, #chaptercontent, #nr1, "
        ".article-content, .entry-content, .post-content, .chapter-content"
    )
    body = soup.body or soup
    if candidates:
        body = max(candidates, key=lambda node: len(node.get_text(strip=True)))
    else:
        prose = []
        for node in soup.select("div, section"):
            chars = sum(len(p.get_text(strip=True)) for p in node.find_all("p"))
            links = sum(len(a.get_text(strip=True)) for a in node.find_all("a"))
            if chars >= 200 and links < chars / 2:
                prose.append((chars - links, node))
        if prose:
            body = max(prose, key=lambda item: item[0])[1]
    # Keep inline phrases together, break only at block boundaries.
    for node in body.select("p, div, section, h1, h2, h3, h4, h5, h6, li, blockquote, tr, br, pre"):
        node.insert_before("\n")
        node.insert_after("\n")
    text = normalize_body(body.get_text())
    if not text.strip() or (
        len(text) < 100 and re.search(r"enable JavaScript|启用\s*JavaScript|开启\s*JavaScript", text, re.I)
    ):
        raise WebReaderError(
            "WEB_EMPTY", "未提取到网页正文。页面可能需要登录或依赖脚本，请在浏览器中复制正文后使用粘贴文本。"
        )
    return WebArticle(url, title[:200], text)


def fetch_article(url: str, cancel_event: threading.Event) -> WebArticle:
    url = validate_web_url(url)
    started = time.monotonic()

    def check_cancel():
        if cancel_event.is_set():
            raise WebReadCancelled()
        if time.monotonic() - started > FETCH_DEADLINE:
            raise WebReaderError("WEB_TIMEOUT", "网页读取超时，请稍后重试。")

    check_cancel()
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 QYReader/2.1 (Article Reader)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
        "Accept-Encoding": "identity",
    })
    try:
        with build_opener(_WebRedirects()).open(request, timeout=FETCH_TIMEOUT) as response:
            final_url = validate_web_url(response.geturl())
            content_type = response.headers.get_content_type()
            if content_type not in ("text/html", "application/xhtml+xml", "text/plain"):
                raise WebReaderError("WEB_NOT_PAGE", "该链接不是 HTML 或文本网页，请下载文档后通过导入文件阅读。")
            charset = response.headers.get_content_charset()
            encoding = response.headers.get("Content-Encoding", "identity").lower()
            if encoding not in ("", "identity", "gzip"):
                raise WebReaderError("WEB_ENCODING", "网页使用了暂不支持的压缩方式，请复制正文后导入。")
            stream = gzip.GzipFile(fileobj=response) if encoding == "gzip" else response
            chunks, size = [], 0
            while True:
                check_cancel()
                read_chunk = getattr(stream, "read1", stream.read)
                chunk = read_chunk(min(65536, MAX_PAGE_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_PAGE_BYTES:
                    raise WebReaderError("WEB_TOO_LARGE", "网页正文超过 10MB，请复制需要阅读的部分后导入。")
            check_cancel()
            raw = b"".join(chunks)
            if content_type == "text/plain":
                from .book_loader import _decode, normalize_body
                text = normalize_body(raw.decode(charset) if charset else _decode(raw))
                if not text:
                    raise WebReaderError("WEB_EMPTY", "该链接没有可阅读正文。")
                return WebArticle(final_url, urlsplit(final_url).hostname or "网页正文", text)
            return extract_article(raw, final_url, charset)
    except HTTPError as exc:
        exc.close()
        raise WebReaderError("WEB_HTTP_ERROR", f"网页访问失败（HTTP {exc.code}），请检查链接或在浏览器中复制正文。") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise WebReaderError("WEB_TIMEOUT", "网页读取超时，请稍后重试。") from exc
    except (URLError, OSError, EOFError, LookupError, UnicodeError) as exc:
        raise WebReaderError("WEB_FETCH_FAILED", "无法读取网页，请检查网络、链接和网站访问权限。") from exc
