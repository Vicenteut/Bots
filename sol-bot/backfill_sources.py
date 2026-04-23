#!/usr/bin/env python3
"""
Best-effort backfill of posts.source_name from monitor queue / pending files.

Coverage will be small because monitor_queue.json is a live queue (items get
removed after publish), so this only catches the small fraction of posts whose
queue items still exist. New posts going forward are captured automatically by
sol_dashboard_api → set_post_source().

Usage:
    python3 backfill_sources.py            # apply
    python3 backfill_sources.py --dry-run  # report only
"""
import argparse
import json
import sqlite3
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path("/root/x-bot/sol-bot")
DB = ROOT / "threads_analytics.db"
SOURCES = [
    ROOT / "monitor_queue.json",
    ROOT / "monitor_pending.json",
]
MATCH_THRESHOLD = 0.78
HEADLINE_TRUNC = 90


def _load_items() -> list[dict]:
    """Flatten all source files into a single [{headline, source_name}, …] list."""
    out: list[dict] = []
    for path in SOURCES:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except Exception as exc:
            print(f"[!] failed reading {path.name}: {exc}", file=sys.stderr)
            continue

        if isinstance(data, dict):
            data = list(data.values())

        if not isinstance(data, list):
            continue

        for item in data:
            if not isinstance(item, dict):
                continue
            # `headline` may be a dict ({title, summary}) or a plain string.
            raw = item.get("headline") or item.get("title") or item.get("text") or ""
            if isinstance(raw, dict):
                headline = (raw.get("title") or raw.get("summary") or "").strip()
            else:
                headline = str(raw).strip()
            source = (item.get("source_name") or item.get("source") or "").strip()
            if headline and source:
                out.append({"headline": headline[:HEADLINE_TRUNC], "source": source})
    return out


def _normalise(s: str) -> str:
    return " ".join(s.lower().split())[:HEADLINE_TRUNC]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Report matches without writing.")
    args = ap.parse_args()

    items = _load_items()
    if not items:
        print("[i] no source items available — nothing to backfill")
        return 0
    print(f"[i] loaded {len(items)} candidate (headline, source) pairs")

    if not DB.exists():
        print(f"[!] DB not found: {DB}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT post_id, text FROM posts WHERE source_name IS NULL OR source_name = ''"
    ).fetchall()
    print(f"[i] {len(rows)} posts have no source_name")

    matches: list[tuple[str, str, float]] = []  # (post_id, source, score)
    for row in rows:
        text_norm = _normalise(row["text"] or "")
        if not text_norm:
            continue
        best = (0.0, None)
        for item in items:
            score = SequenceMatcher(None, text_norm, _normalise(item["headline"])).ratio()
            if score > best[0]:
                best = (score, item["source"])
        if best[0] >= MATCH_THRESHOLD and best[1]:
            matches.append((row["post_id"], best[1], best[0]))

    print(f"[i] matched {len(matches)} posts above threshold {MATCH_THRESHOLD}")
    by_source: dict[str, int] = {}
    for _pid, src, _ in matches:
        by_source[src] = by_source.get(src, 0) + 1
    for src, n in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"   {src:<32} {n}")

    if args.dry_run:
        print("[dry-run] no writes")
        return 0

    if matches:
        conn.executemany(
            "UPDATE posts SET source_name = ? WHERE post_id = ? "
            "AND (source_name IS NULL OR source_name = '')",
            [(src, pid) for pid, src, _ in matches],
        )
        conn.commit()
        print(f"[OK] wrote {len(matches)} updates")
    else:
        print("[i] no matches to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
