from __future__ import annotations

import re

HASHTAG_RE = re.compile(r"(?<!\w)#[\w_]+")
MULTI_BLANK_RE = re.compile(r"
{3,}")
WHITESPACE_RE = re.compile(r"[ 	]+")


def normalize_text(text: str) -> str:
    text = text.replace("
", "
").replace("", "
").strip()
    lines = [WHITESPACE_RE.sub(" ", line).strip() for line in text.split("
")]
    normalized = "
".join(lines)
    return MULTI_BLANK_RE.sub("

", normalized).strip()


def sanitize_generated_text(
    text: str,
    *,
    max_chars: int,
    allow_hashtags: bool = False,
) -> str:
    cleaned = normalize_text(text.strip().strip('"').strip("“").strip("”"))
    if not allow_hashtags:
        cleaned = HASHTAG_RE.sub("", cleaned)
        cleaned = normalize_text(cleaned)
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned
