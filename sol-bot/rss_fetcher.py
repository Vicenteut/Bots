#!/usr/bin/env python3
"""Fetch enabled RSS sources and add normalized alerts to Sol's monitor queue."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from config import BASE_DIR
from ingestion_utils import append_or_merge_queue, load_source_config, normalize_ingest_payload

try:
    import feedparser
except ImportError:
    feedparser = None

MONITOR_QUEUE = BASE_DIR / "monitor_queue.json"
MONITOR_QUEUE_LOCK = BASE_DIR / "monitor_queue.lock"
RSS_STATE = BASE_DIR / "rss_fetcher_state.json"
RSS_STATE_LOCK = BASE_DIR / "rss_fetcher_state.lock"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _atomic_write_json(path: Path, data) -> None:
    tmp = path.parent / f".tmp_{path.name}"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _entry_time(entry) -> str:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _entry_payload(source: dict[str, Any], entry) -> dict[str, Any]:
    title = (getattr(entry, "title", "") or "").strip()
    summary = (getattr(entry, "summary", "") or getattr(entry, "description", "") or title).strip()
    link = (getattr(entry, "link", "") or "").strip()
    external_id = (getattr(entry, "id", "") or getattr(entry, "guid", "") or link or title).strip()
    return {
        "external_id": external_id,
        "received_at": _entry_time(entry),
        "source_name": source.get("name") or "RSS",
        "source_type": "rss",
        "canonical_url": link,
        "headline": {
            "title": title,
            "summary": summary,
            "source": source.get("name") or "RSS",
            "url": link,
        },
        "metadata": {
            "credibility": source.get("credibility", "medium"),
            "priority": source.get("base_priority", "normal"),
            "tags": source.get("category_defaults", []),
            "language": source.get("language", "en"),
            "is_official": bool(source.get("is_official", False)),
            "redistributable": bool(source.get("redistributable", True)),
        },
    }


def _load_queue() -> list[dict[str, Any]]:
    try:
        data = json.loads(MONITOR_QUEUE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def sync_sources(*, limit_per_source: int = 10, dry_run: bool = False) -> dict[str, Any]:
    if feedparser is None:
        return {
            "success": False,
            "sources": 0,
            "created": 0,
            "merged": 0,
            "skipped": 0,
            "dry_run": dry_run,
            "processed": [],
            "errors": ["feedparser is not installed; run pip install -r requirements.txt"],
        }

    config = load_source_config()
    rss_sources = [
        s for s in config.get("sources", [])
        if isinstance(s, dict) and s.get("enabled") and s.get("type") == "rss" and s.get("feed_url")
    ]
    state = _read_json(RSS_STATE, {"seen": {}})
    seen = state.setdefault("seen", {})
    created = 0
    merged = 0
    skipped = 0
    errors: list[str] = []
    processed: list[dict[str, str]] = []

    with FileLock(str(MONITOR_QUEUE_LOCK), timeout=10):
        queue = _load_queue()
        for source in rss_sources:
            source_name = source.get("name", "RSS")
            feed_url = source.get("feed_url", "")
            source_seen = set(seen.get(source_name, []))
            try:
                feed = feedparser.parse(feed_url)
                entries = list(feed.entries or [])[:limit_per_source]
            except Exception as exc:
                errors.append(f"{source_name}: {exc}")
                continue

            for raw_entry in entries:
                payload = _entry_payload(source, raw_entry)
                unique_id = payload["external_id"]
                if unique_id in source_seen:
                    skipped += 1
                    continue
                if not payload["headline"]["title"]:
                    skipped += 1
                    continue
                entry = normalize_ingest_payload(payload)
                queue, stored, status = append_or_merge_queue(queue, entry)
                if status == "created":
                    created += 1
                else:
                    merged += 1
                source_seen.add(unique_id)
                processed.append({"source": source_name, "status": status, "id": stored.get("id", "")})

            seen[source_name] = list(source_seen)[-500:]

        if not dry_run:
            _atomic_write_json(MONITOR_QUEUE, queue)

    if not dry_run:
        with FileLock(str(RSS_STATE_LOCK), timeout=5):
            state["last_run_at"] = datetime.now(timezone.utc).isoformat()
            _atomic_write_json(RSS_STATE, state)

    return {
        "success": not errors,
        "sources": len(rss_sources),
        "created": created,
        "merged": merged,
        "skipped": skipped,
        "dry_run": dry_run,
        "processed": processed[:50],
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Sol RSS sources into the monitor inbox.")
    parser.add_argument("sync", nargs="?", default="sync")
    parser.add_argument("--limit", type=int, default=10, help="Max entries per source")
    parser.add_argument("--dry-run", action="store_true", help="Parse and normalize without writing")
    args = parser.parse_args()
    print(json.dumps(sync_sources(limit_per_source=args.limit, dry_run=args.dry_run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
