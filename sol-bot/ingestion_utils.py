"""Shared ingestion helpers for Sol's multi-source monitor inbox."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from config import BASE_DIR
from topic_utils import classify_topic

SOURCE_CONFIG_PATH = BASE_DIR / "source_config.json"
MONITOR_QUEUE = BASE_DIR / "monitor_queue.json"
MONITOR_QUEUE_LOCK = BASE_DIR / "monitor_queue.lock"

DEFAULT_SCHEMA_VERSION = "1.0"
DEFAULT_QUEUE_MAX = int(os.getenv("MONITOR_QUEUE_MAX", "100") or "100")
PRIORITY_ORDER = ("breaking", "high", "normal", "low", "duplicate", "unverified")
PRIORITY_RANK = {label: idx for idx, label in enumerate(PRIORITY_ORDER)}

_BREAKING_WORDS = (
    "breaking",
    "just in",
    "urgent",
    "alert",
    "developing",
    "exclusive",
    "última hora",
)

_TIER1_NAMES = {
    "reuters",
    "associated press",
    "ap",
    "sec",
    "federal reserve",
    "fed",
    "treasury",
    "ecb",
    "imf",
    "world bank",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_source_config(path: Path = SOURCE_CONFIG_PATH) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"sources": []}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"sources": []}


def find_source_config(source_name: str, source_type: str | None = None) -> dict[str, Any]:
    name = (source_name or "").strip().lower()
    typ = (source_type or "").strip().lower()
    for source in load_source_config().get("sources", []):
        if not isinstance(source, dict):
            continue
        if (source.get("name") or "").strip().lower() != name:
            continue
        if typ and (source.get("type") or "").strip().lower() != typ:
            continue
        return dict(source)
    return {}


def normalize_url(url: str | None) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        query = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
        ]
        return urlunsplit(
            (
                parts.scheme.lower(),
                parts.netloc.lower(),
                parts.path.rstrip("/") or parts.path,
                urlencode(query, doseq=True),
                "",
            )
        )
    except Exception:
        return raw


def normalize_title(text: str | None) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip().lower()
    cleaned = re.sub(r"[^\w\s$%.-]", "", cleaned)
    return cleaned


def build_dedup_key(payload: dict[str, Any]) -> str:
    canonical_url = normalize_url(payload.get("canonical_url") or payload.get("url"))
    if canonical_url:
        basis = f"url:{canonical_url}"
    else:
        headline = payload.get("headline") or {}
        title = normalize_title(headline.get("title") or payload.get("title"))
        basis = f"title:{title}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _priority_label(score: int, *, possible_duplicate: bool = False, unverified: bool = False) -> str:
    if possible_duplicate:
        return "duplicate"
    if unverified:
        return "unverified"
    if score >= 80:
        return "breaking"
    if score >= 60:
        return "high"
    if score >= 30:
        return "normal"
    return "low"


def priority_rank(label: str | None) -> int:
    return PRIORITY_RANK.get((label or "normal").strip().lower(), PRIORITY_RANK["normal"])


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason and reason not in reasons:
        reasons.append(reason)


def score_alert_details(entry: dict[str, Any]) -> tuple[int, str, list[str]]:
    source_name = (entry.get("source_name") or "").strip().lower()
    credibility = (entry.get("credibility") or "").strip().lower()
    title = (entry.get("headline") or {}).get("title", "")
    summary = (entry.get("headline") or {}).get("summary", "")
    text = f"{title}\n{summary}".lower()
    score = 0
    reasons: list[str] = []

    if entry.get("is_official"):
        score += 40
        _add_reason(reasons, "official source")
    if credibility == "high" or source_name in _TIER1_NAMES:
        score += 30
        _add_reason(reasons, "trusted source")
    elif credibility == "medium":
        score += 10
        _add_reason(reasons, "known source")

    if entry.get("canonical_url"):
        score += 10
        _add_reason(reasons, "canonical URL")
    else:
        score -= 20
        _add_reason(reasons, "no canonical URL")

    related_count = int(entry.get("related_source_count") or 1)
    if related_count > 1:
        score += min(45, (related_count - 1) * 15)
        _add_reason(reasons, "multiple sources")

    if entry.get("topic_guess") and entry.get("topic_guess") != "general":
        score += 15
        _add_reason(reasons, f"topic: {entry.get('topic_guess')}")
    if text.startswith(_BREAKING_WORDS) or any(word in text for word in _BREAKING_WORDS):
        score += 10
        _add_reason(reasons, "breaking keywords")
    if re.search(r"\b\d+(?:[.,]\d+)?\s?(%|bps|million|billion|trillion|k|m|bn|tn)?\b", text):
        score += 10
        _add_reason(reasons, "data/numbers")

    unverified = credibility == "unverified" or entry.get("source_type") == "x"
    if unverified:
        score -= 25
        _add_reason(reasons, "unverified")

    if entry.get("possible_duplicate"):
        _add_reason(reasons, "possible duplicate")
    if int(entry.get("duplicate_count") or 0) > 0:
        _add_reason(reasons, "duplicate reports")

    score = max(0, min(100, score))
    label = _priority_label(
        score,
        possible_duplicate=bool(entry.get("possible_duplicate")),
        unverified=unverified and score < 80,
    )
    return score, label, reasons[:5]


def score_alert(entry: dict[str, Any]) -> tuple[int, str]:
    score, label, _reasons = score_alert_details(entry)
    return score, label


def _title_tokens(text: str | None) -> set[str]:
    stop = {"the", "a", "an", "to", "of", "in", "on", "for", "and", "or", "as", "is", "are"}
    return {t for t in normalize_title(text).split() if len(t) > 3 and t not in stop}


def _title_similarity(a: str | None, b: str | None) -> float:
    left = _title_tokens(a)
    right = _title_tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left | right))


def normalize_ingest_payload(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(payload.get("metadata") or {})
    headline_in = dict(payload.get("headline") or {})
    source_name = (payload.get("source_name") or metadata.get("source_name") or "Unknown").strip()
    source_type = (payload.get("source_type") or metadata.get("source_type") or "webhook").strip().lower()
    source_cfg = find_source_config(source_name, source_type) or find_source_config(source_name)

    title = (headline_in.get("title") or payload.get("title") or "").strip()
    summary = (headline_in.get("summary") or payload.get("summary") or title).strip()
    canonical_url = normalize_url(payload.get("canonical_url") or payload.get("url") or headline_in.get("url"))
    now = utc_now_iso()
    received_at = payload.get("received_at") or payload.get("published_at") or now
    text = f"{title}\n{summary}".strip()
    topic = metadata.get("topic") or metadata.get("category") or classify_topic(text)
    credibility = metadata.get("credibility") or source_cfg.get("credibility") or "medium"
    priority = metadata.get("priority") or source_cfg.get("base_priority") or "normal"
    tags = metadata.get("tags") or source_cfg.get("category_defaults") or []
    if isinstance(tags, str):
        tags = [tags]

    entry = {
        "schema_version": DEFAULT_SCHEMA_VERSION,
        "id": payload.get("id") or f"ing_{hashlib.sha1(f'{source_name}:{title}:{now}'.encode()).hexdigest()[:16]}",
        "external_id": payload.get("external_id") or "",
        "received_at": received_at,
        "ingested_at": now,
        "last_seen_at": now,
        "source_name": source_name,
        "source_type": source_type,
        "canonical_url": canonical_url,
        "headline": {
            "title": title,
            "summary": summary,
            "source": source_name,
            "url": canonical_url,
        },
        "media_urls": [u for u in payload.get("media_urls", []) if u] if isinstance(payload.get("media_urls"), list) else [],
        "media_paths": [p for p in payload.get("media_paths", []) if p] if isinstance(payload.get("media_paths"), list) else [],
        "media_path": payload.get("media_path") or "",
        "media_type": payload.get("media_type") or "",
        "metadata": metadata,
        "credibility": credibility,
        "priority": priority,
        "category": topic,
        "topic_guess": topic,
        "tags": tags,
        "language": metadata.get("language") or payload.get("language") or source_cfg.get("language") or "en",
        "is_official": bool(metadata.get("is_official", source_cfg.get("is_official", False))),
        "redistributable": bool(metadata.get("redistributable", source_cfg.get("redistributable", True))),
        "status": "new",
        "related_sources": [
            {
                "source_name": source_name,
                "source_type": source_type,
                "canonical_url": canonical_url,
                "external_id": payload.get("external_id") or "",
                "seen_at": now,
            }
        ],
        "related_source_count": 1,
    }
    entry["dedup_key"] = payload.get("dedup_key") or build_dedup_key(entry)
    entry["score"], entry["priority_label"], entry["score_reasons"] = score_alert_details(entry)
    entry["priority_rank"] = priority_rank(entry["priority_label"])
    return entry


def merge_duplicate(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    related = list(merged.get("related_sources") or [])
    incoming_source = (incoming.get("source_name") or "Unknown").strip()
    incoming_url = incoming.get("canonical_url") or ""
    already_seen = any(
        (r.get("source_name") == incoming_source and r.get("canonical_url", "") == incoming_url)
        for r in related
        if isinstance(r, dict)
    )
    if not already_seen:
        related.extend(incoming.get("related_sources") or [])
    merged["related_sources"] = related
    merged["related_source_count"] = len(
        {
            (r.get("source_name"), r.get("canonical_url") or r.get("external_id"))
            for r in related
            if isinstance(r, dict)
        }
    ) or 1
    merged["last_seen_at"] = utc_now_iso()
    merged["duplicate_count"] = int(merged.get("duplicate_count") or 0) + 1
    merged["possible_duplicate"] = False

    # Preserve the richer text if the incoming alert has more context.
    current_summary = (merged.get("headline") or {}).get("summary", "")
    incoming_summary = (incoming.get("headline") or {}).get("summary", "")
    if len(incoming_summary) > len(current_summary):
        merged["headline"] = incoming.get("headline", merged.get("headline", {}))
        merged["canonical_url"] = incoming.get("canonical_url") or merged.get("canonical_url", "")

    merged["score"], merged["priority_label"], merged["score_reasons"] = score_alert_details(merged)
    merged["priority_rank"] = priority_rank(merged["priority_label"])
    return merged


def append_or_merge_queue(queue: list[dict[str, Any]], entry: dict[str, Any], *, max_items: int = DEFAULT_QUEUE_MAX) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    dedup_key = entry.get("dedup_key")
    for idx, existing in enumerate(queue):
        if dedup_key and existing.get("dedup_key") == dedup_key:
            merged = merge_duplicate(existing, entry)
            queue[idx] = merged
            return queue, merged, "merged"

    incoming_title = (entry.get("headline") or {}).get("title", "")
    for existing in queue:
        existing_title = (existing.get("headline") or {}).get("title", "")
        if _title_similarity(incoming_title, existing_title) >= 0.82:
            entry["possible_duplicate"] = True
            entry["duplicate_of"] = existing.get("id")
            entry["score"], entry["priority_label"], entry["score_reasons"] = score_alert_details(entry)
            entry["priority_rank"] = priority_rank(entry["priority_label"])
            break

    queue.append(entry)
    if len(queue) > max_items:
        queue = queue[-max_items:]
    return queue, entry, "created"
