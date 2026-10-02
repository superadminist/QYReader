# -*- coding: utf-8 -*-
"""Real local HTTP -> extracted snapshot -> offline reader integration."""
import gzip
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from novelreader import book_loader
from novelreader.import_service import LibraryImportService, ImportServiceError
from novelreader.reader_service import ReaderService
from novelreader.storage import Storage
from novelreader.web_reader import (
    WebReaderError, WebReadCancelled, extract_article, fetch_article, validate_web_url,
)


HTML = '''<!doctype html><html><head><meta charset="utf-8"><title>网站标题</title></head>
<body><header>网站导航</header><nav>首页 广告链接</nav><main><article>
<h1>网页阅读测试</h1><p>第一段<strong>中文正文</strong>，链接<a href="https://example.com">文字</a>。</p>
<p>第二段用于验证离线阅读和进度恢复。</p><script>不应朗读的脚本</script>
<div hidden><span hidden>隐藏文本</span></div><div style="display:none">隐藏样式</div>
</article><aside>推荐广告</aside></main><footer>版权导航</footer></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/article")
            self.end_headers()
            return
        if self.path == "/missing":
            self.send_error(404)
            return
        body, mime = HTML.encode("utf-8"), "text/html; charset=utf-8"
        if self.path == "/gbk":
            body = HTML.replace('charset="utf-8"', 'charset="gb18030"').encode("gb18030")
            mime = "text/html"
        elif self.path == "/plain":
            body, mime = "纯文本网页正文。\n第二段文字。".encode("utf-8"), "text/plain; charset=utf-8"
        elif self.path == "/binary":
            body, mime = b"not an article", "application/pdf"
        elif self.path == "/empty":
            body = b"<html><body><script>loadArticle()</script></body></html>"
        elif self.path == "/gzip":
            body = gzip.compress(body)
        self.send_response(200)
        self.send_header("Content-Type", mime)
        if self.path == "/gzip":
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class WebReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.library_path = self.root / "data" / "library.json"
        environment = patch.dict(os.environ, {"DOUBAO_NOVEL_DATA": os.fspath(self.library_path.parent)})
        environment.start()
        self.addCleanup(environment.stop)
        self.service = LibraryImportService(self.library_path)

    def test_article_filters_chrome_and_preserves_inline_text(self):
        article = extract_article(HTML.encode("utf-8"), self.base)
        self.assertEqual(article.title, "网页阅读测试")
        self.assertIn("第一段中文正文，链接文字。", article.text)
        for noise in ("导航", "广告", "脚本", "隐藏", "https://", "网站标题"):
            self.assertNotIn(noise, article.text)

    def test_real_http_redirect_encoding_gzip_and_plain_text(self):
        for route in ("/article", "/redirect", "/gbk", "/gzip"):
            with self.subTest(route=route):
                article = fetch_article(self.base + route, threading.Event())
                self.assertIn("中文正文", article.text)
                if route == "/redirect":
                    self.assertEqual(article.url, self.base + "/article")
        article = fetch_article(self.base + "/plain", threading.Event())
        self.assertEqual(article.text, "纯文本网页正文。\n第二段文字。")

    def test_http_failures_binary_empty_and_size_limit(self):
        for route, code in [("/missing", "WEB_HTTP_ERROR"), ("/binary", "WEB_NOT_PAGE"), ("/empty", "WEB_EMPTY")]:
            with self.subTest(route=route), self.assertRaises(WebReaderError) as error:
                fetch_article(self.base + route, threading.Event())
            self.assertEqual(error.exception.code, code)
        with patch("novelreader.web_reader.MAX_PAGE_BYTES", 100):
            for route in ("/article", "/gzip"):
                with self.subTest(route=route), self.assertRaises(WebReaderError) as error:
                    fetch_article(self.base + route, threading.Event())
                self.assertEqual(error.exception.code, "WEB_TOO_LARGE")

    def test_url_validation_and_cancel_do_not_create_content(self):
        for url in ("file:///tmp/a", "javascript:alert(1)", "https://", "https://a:bad", "https://user:secret@example.com", "https://a/ bad"):
            with self.subTest(url=url), self.assertRaises(WebReaderError):
                validate_web_url(url)
        event = threading.Event()
        event.set()
        result = self.service.import_web_page(self.base + "/article", event, lambda _: None)
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(result["succeeded"], 0)
        self.assertFalse(self.library_path.parent.exists())

    def test_cancel_during_download(self):
        from email.message import Message
        event = threading.Event()

        class Response:
            headers = Message()
            headers["Content-Type"] = "text/html"
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def geturl(self): return "https://example.com/article"
            def read(self, _size):
                event.set()
                return b"<p>body</p>"

        with patch("novelreader.web_reader.build_opener") as opener:
            opener.return_value.open.return_value = Response()
            with self.assertRaises(WebReadCancelled):
                fetch_article("https://example.com/article", event)

    def test_snapshot_import_offline_reparse_backup_and_progress(self):
        progress = []
        result = self.service.import_web_page(self.base + "/article", threading.Event(), progress.append)
        self.assertEqual(result["succeeded"], 1, result)
        book_id = result["openAfterImportBookId"]
        storage = Storage(os.fspath(self.library_path))
        metadata = storage.get_book(book_id)
        self.assertEqual(metadata["format"], "web")
        self.assertEqual(metadata["title"], "网页阅读测试")
        source = Path(metadata["path"])
        snapshot = source.read_text(encoding="utf-8")
        self.assertIn(self.base + "/article", snapshot)
        self.assertNotIn("<script>", snapshot)
        self.assertNotIn(os.fspath(self.root), json.dumps(progress))
        self.assertEqual(book_loader.parse_book(os.fspath(source)).format, "web")

        # Delete cached content and the original snapshot: reopen from backup,
        # without any HTTP request or dependency on the original website.
        reader = ReaderService(self.library_path)
        opened = reader.open_book(book_id)
        reader.update_position(opened["sessionId"], 0, 3)
        (self.library_path.parent / "cache" / f"{book_id}.json").unlink()
        source.unlink()
        with patch("novelreader.web_reader.fetch_article", side_effect=AssertionError("offline")):
            reopened = ReaderService(self.library_path).open_book(book_id)
        self.assertEqual(reopened["book"]["title"], "网页阅读测试")
        self.assertEqual(reopened["position"]["charOffset"], 3)
        self.assertIn("中文正文", "".join(block["text"] for block in reopened["window"]["blocks"]))

    def test_failed_fetch_preserves_library_and_creates_no_snapshot(self):
        self.library_path.parent.mkdir()
        original = b'{"books":{},"settings":{}}'
        self.library_path.write_bytes(original)
        with self.assertRaises(ImportServiceError) as error:
            self.service.import_web_page(self.base + "/missing", threading.Event(), lambda _: None)
        self.assertEqual(error.exception.code, "WEB_HTTP_ERROR")
        self.assertEqual(self.library_path.read_bytes(), original)
        self.assertFalse((self.library_path.parent / "webpages").exists())


if __name__ == "__main__":
    unittest.main()
