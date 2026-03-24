from __future__ import annotations

import re

HASHTAG_RE = re.compile(r"(?<!\w)#[\w_]+")
MULTI_BLANK_RE = re.compile(r"\n{3,}")
WHITESPACE_RE = re.compile(r"[ \t]+")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [WHITESPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    normalized = "\n".join(lines)
    return MULTI_BLANK_RE.sub("\n\n", normalized).strip()


def sanitize_generated_text(
    text: str,
    *,
    max_chars: int,
    allow_hashtags: bool = False,
) -> str:
    cleaned = normalize_text(text.strip().strip('"').strip("\u201c").strip("\u201d"))
    if not allow_hashtags:
        cleaned = HASHTAG_RE.sub("", cleaned)
        cleaned = normalize_text(cleaned)
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned
