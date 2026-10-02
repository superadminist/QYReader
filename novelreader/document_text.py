# -*- coding: utf-8 -*-
"""Readable prose from Markdown and Word 97–2003 documents."""
from __future__ import annotations

import re
import struct


class DocumentTextError(ValueError):
    """A parser message that is safe to display in the import dialog."""


_DOC_ANSI = dict(zip(
    (0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x8B, 0x8C,
     0x91, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0x9B, 0x9C, 0x9F),
    (0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021, 0x02C6, 0x2030, 0x0160, 0x2039, 0x0152,
     0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014, 0x02DC, 0x2122, 0x0161, 0x203A, 0x0153, 0x0178),
))


def markdown_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    from markdown_it import MarkdownIt
    from bs4 import BeautifulSoup

    text = re.sub(r"\A---\s*\n.*?\n(?:---|\.\.\.)\s*(?:\n|$)", "", text, count=1, flags=re.S)
    tokens = MarkdownIt("commonmark").enable(["table", "strikethrough"]).parse(text)
    sections, lines = [], []
    current_title, title = "正文", ""

    def inline_text(token):
        parts, hidden = [], []
        for child in token.children or []:
            if child.type == "html_inline":
                match = re.match(r"<\s*(/?)\s*(script|style|iframe|noscript)\b", child.content, re.I)
                if match:
                    if match[1] and hidden:
                        hidden.pop()
                    elif not match[1]:
                        hidden.append(match[2].lower())
                continue
            if hidden:
                continue
            if child.type in ("text", "code_inline"):
                parts.append(child.content)
            elif child.type in ("softbreak", "hardbreak"):
                parts.append("\n")
            # Images, HTML tags and link destinations are skipped.
        return re.sub(r"https?://[^\s<>]+", "", "".join(parts)).strip()

    def flush():
        body = "\n".join(lines).strip()
        if body:
            sections.append((current_title, body))
        lines.clear()

    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag in ("h1", "h2"):
            heading = inline_text(tokens[index + 1])
            flush()
            current_title = heading or "正文"
            if not title and token.tag == "h1":
                title = heading
        elif token.type == "inline":
            value = inline_text(token)
            if value:
                lines.append(re.sub(r"^\[[ xX]\]\s*", "", value))
        elif token.type == "html_block":
            soup = BeautifulSoup(token.content, "html.parser")
            for node in soup.select("script, style, pre, code, img"):
                node.decompose()
            value = soup.get_text("\n", strip=True)
            if value:
                lines.append(value)
        # Fenced/indented code, rules and Markdown control tokens are skipped.
    flush()
    return title, sections


def _word_fields(text: str) -> str:
    """Keep field results (e.g. link labels), discard field instructions."""
    output, fields = [], []
    for char in text:
        if char == "\x13":
            fields.append(False)
        elif char == "\x14" and fields:
            fields[-1] = True
        elif char == "\x15" and fields:
            fields.pop()
        elif all(fields):
            output.append(char)
    text = "".join(output).replace("\r", "\n").replace("\x07", "\n")
    text = text.replace("\x0b", "\n").replace("\x0c", "\n")
    return re.sub(r"[\x00-\x08\x0e-\x1f]", "", text)


def word_binary_text(word: bytes, table: bytes) -> str:
    """MS-DOC FIB -> CLX -> PlcPcd, limited to the main document story.

    https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/01d5d8c4-cf9c-4ef9-80fd-439e763cfe01
    """
    def u16(data, offset):
        return struct.unpack_from("<H", data, offset)[0]

    def u32(data, offset):
        return struct.unpack_from("<I", data, offset)[0]

    try:
        if u16(word, 0) != 0xA5EC or u16(word, 2) < 0xC1:
            raise DocumentTextError("仅支持 Word 97–2003 及更新版本保存的 DOC，请另存为 DOCX 后导入。")
        if u16(word, 10) & (0x100 | 0x8000):
            raise DocumentTextError("DOC 已加密，请去除密码后导入。")
        # Walk variable-size FIB arrays instead of assuming fixed offsets.
        lw_offset = 34 + u16(word, 32) * 2
        lw_size = u16(word, lw_offset)
        if lw_size < 4:
            raise DocumentTextError("DOC 正文索引不完整。")
        main_chars = u32(word, lw_offset + 2 + 3 * 4)
        fc_offset = lw_offset + 2 + lw_size * 4
        if u16(word, fc_offset) < 34:
            raise DocumentTextError("DOC 正文索引不完整。")
        clx_offset, clx_size = struct.unpack_from("<II", word, fc_offset + 2 + 33 * 8)
        if clx_offset + clx_size > len(table):
            raise DocumentTextError("DOC 正文索引越界，文件可能损坏。")
        clx = table[clx_offset:clx_offset + clx_size]
        pos = 0
        while pos < len(clx) and clx[pos] == 1:
            pos += 3 + u16(clx, pos + 1)
        if pos >= len(clx) or clx[pos] != 2:
            raise DocumentTextError("DOC 缺少正文片段索引。")
        size = u32(clx, pos + 1)
        pieces = clx[pos + 5:pos + 5 + size]
        if size < 4 or (size - 4) % 12 or len(pieces) != size:
            raise DocumentTextError("DOC 正文片段索引损坏。")
        count = (size - 4) // 12
        cp = struct.unpack_from(f"<{count + 1}I", pieces)
        if cp[0] != 0 or cp[-1] < main_chars or any(a > b for a, b in zip(cp, cp[1:])):
            raise DocumentTextError("DOC 正文位置索引损坏。")
        output = []
        for index in range(count):
            if cp[index] >= main_chars:
                break
            chars = min(cp[index + 1], main_chars) - cp[index]
            fc = u32(pieces, (count + 1) * 4 + index * 8 + 2)
            compressed = bool(fc & 0x40000000)
            offset = fc & 0x3FFFFFFF
            if compressed:
                offset //= 2
            byte_count = chars * (1 if compressed else 2)
            if offset + byte_count > len(word):
                raise DocumentTextError("DOC 正文片段越界，文件可能损坏。")
            raw = word[offset:offset + byte_count]
            output.append(raw.decode("latin-1").translate(_DOC_ANSI) if compressed
                          else raw.decode("utf-16-le", errors="surrogatepass"))
        text = "".join(output).encode("utf-16-le", errors="surrogatepass").decode("utf-16-le", errors="replace")
        return _word_fields(text)
    except (struct.error, IndexError) as exc:
        raise DocumentTextError("DOC 文件损坏，无法读取正文索引。") from exc


def read_doc(path: str) -> str:
    import olefile

    if not olefile.isOleFile(path):
        raise DocumentTextError("文件不是有效的 Word DOC，请另存为 DOCX 后导入。")
    with olefile.OleFileIO(path) as document:
        if not document.exists("WordDocument"):
            raise DocumentTextError("DOC 缺少 Word 正文，文件可能已加密或损坏。")
        word = document.openstream("WordDocument").read()
        if len(word) < 12:
            raise DocumentTextError("DOC 文件损坏。")
        flags = struct.unpack_from("<H", word, 10)[0]
        if flags & (0x100 | 0x8000):
            raise DocumentTextError("DOC 已加密，请去除密码后导入。")
        table_name = "1Table" if flags & 0x200 else "0Table"
        if not document.exists(table_name):
            raise DocumentTextError("DOC 缺少正文索引，请另存为 DOCX 后导入。")
        return word_binary_text(word, document.openstream(table_name).read())
