"""Layout-independent code-point anchors and safe plain-text note export."""
import hashlib


def fingerprint(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_anchor(content, start, end):
    return {"chapterHash": fingerprint(content), "quote": content[start:end],
            "prefix": content[max(0, start - 32):start], "suffix": content[end:end + 32]}


def locate(bookmark, content, chapter_hash=None):
    anchor = bookmark.get("anchor")
    start, end = bookmark.get("offset", 0), bookmark.get("offset_end", bookmark.get("offset", 0))
    if not isinstance(anchor, dict):
        return (start, end) if isinstance(start, int) and isinstance(end, int) and 0 <= start <= end <= len(content) else None
    quote = anchor.get("quote", "")
    if anchor.get("chapterHash") == (chapter_hash or fingerprint(content)) and 0 <= start < end <= len(content) and content[start:end] == quote:
        return start, end
    if not quote:
        return None
    candidates, offset = [], 0
    while True:
        index = content.find(quote, offset)
        if index < 0:
            break
        tail = index + len(quote)
        if content[:index].endswith(anchor.get("prefix", "")) and content[tail:].startswith(anchor.get("suffix", "")):
            candidates.append((index, tail))
        offset = index + 1
    return candidates[0] if len(candidates) == 1 else None


def export_notes(title, items, format):
    lines = ["# " + title if format == "md" else title, ""]
    for note in sorted(items, key=lambda x: (x["chapterIndex"], x["startOffset"], x["createdAt"])):
        lines += [("## " if format == "md" else "") + note["chapterTitle"], ""]
        lines += [("> " if format == "md" else "") + line for line in note["text"].splitlines()]
        lines += ["", "备注：" + note["note"], ""]
    return "\n".join(lines)
