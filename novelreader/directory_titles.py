"""Derive directory labels without changing cached chapters or text offsets."""

import re


_NUMBER = r"[0-9０-９零〇一二三四五六七八九十百千万两]+"
_FALLBACK = re.compile(r"第\s*([0-9]+)\s*节")
_FILE_PREFIX = re.compile(r"^[0-9０-９]+\s*[_＿]\s*")
_HEADING = re.compile(
    rf"^(?:第\s*{_NUMBER}\s*[章节回卷部集篇课讲]|(?:chapter|lesson)\s+[0-9IVXLC]+)"
    r"(?:\s*[:：、.．\-—]\s*\S.*|\s+\S.*)?$",
    re.IGNORECASE,
)


def _opening(content):
    # Bound work per chapter, including books containing very long paragraphs.
    prefix = content[:1024].lstrip("\ufeff \t\r\n\u3000")
    line = prefix.split("\n", 1)[0].strip()
    return re.sub(r"\s+", " ", line)


def directory_labels(chapters):
    """Return additive presentation metadata; never mutate Chapter objects.

    Old caches do not record fallback provenance. Only a whole sequence matching
    the generated section names (or a single 正文) is eligible for inferred names.
    Existing meaningful titles always win.
    """
    automatic = bool(chapters) and all(
        (match := _FALLBACK.fullmatch(chapter.title.strip())) is not None
        and match.group(1) == str(index + 1)
        for index, chapter in enumerate(chapters)
    )
    if len(chapters) == 1 and chapters[0].title.strip() == "正文":
        automatic = True

    labels = []
    active_heading = ""
    continuation = 0
    for chapter in chapters:
        label = {"displayTitle": chapter.title, "continuationLabel": ""}
        if automatic:
            opening = _opening(chapter.content)
            candidate = _FILE_PREFIX.sub("", opening)
            numbered = (
                len(candidate) <= 200
                and _HEADING.fullmatch(candidate) is not None
                and not re.search(r"[。；;]", candidate)
            )
            if numbered:
                active_heading, continuation = candidate, 0
                label["displayTitle"] = candidate
            elif active_heading:
                continuation += 1
                label.update(displayTitle=active_heading, continuationLabel=f"（续{continuation}）")
            elif opening:
                # A short opening line can be a plain title; otherwise use its
                # first sentence as an excerpt, retaining the original body.
                sentence = re.split(r"(?<=[。！？!?；;])", opening, maxsplit=1)[0]
                label["displayTitle"] = sentence[:48] + ("…" if len(sentence) > 48 else "")
        labels.append(label)
    return labels
