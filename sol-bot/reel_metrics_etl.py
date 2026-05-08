"""
reel_metrics_etl.py — Pull insights for recently published reels and persist
them in `reel_metrics` for per-rhetorical-move performance analysis.

Run modes:
    python3 reel_metrics_etl.py            # default: last 30 days, all networks
    python3 reel_metrics_etl.py --days 7   # narrower window
    python3 reel_metrics_etl.py --once     # alias for default
    python3 reel_metrics_etl.py --reel-id <id>   # single reel debug

Adapter coverage:
    YouTube:   views, likes, comments (no shares — Shorts hides them)
    Instagram: views, likes, comments, shares, reach
    TikTok:    views, likes, comments, shares
    (Threads / X: not currently exposed via fetch_post_insights for reels)

Designed to be safe to re-run: every call inserts a fresh row with current
timestamp. Watch deltas across runs to compute growth velocity.

Systemd timer drives this daily; can also be invoked manually for backfill.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "threads_analytics.db"

# Load .env manually (cron / systemd context has no shell)
env_path = ROOT / ".env"
if env_path.exists():
    with env_path.open() as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("reel_metrics_etl")


def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_insights(payload: dict) -> dict:
    """Map heterogeneous adapter outputs to the reel_metrics column set.

    All values default to None — column is nullable. We collect what we can
    and accept that not every network exposes every metric.

    Important: zero is a valid value (e.g. 0 likes is real data).
    Don't use `a or b` for fallback — that swallows zeros. Use first-present.
    """
    if not isinstance(payload, dict):
        return {}

    def _first_present(*keys):
        for k in keys:
            if k in payload:
                v = payload.get(k)
                if v is None:
                    continue
                try:
                    return int(v)
                except (ValueError, TypeError):
                    continue
        return None

    return {
        "views": _first_present("views", "plays", "viewCount"),
        "likes": _first_present("likes", "likeCount"),
        "comments": _first_present("comments", "replies", "commentCount"),
        "shares": _first_present("shares", "shareCount"),
        "saves": _first_present("saves", "saved"),
        "watch_time_sec": _first_present("watch_time_sec", "total_watch_time"),
        "follows_attributed": _first_present("follows_attributed", "follower_growth"),
    }


def fetch_recent_published(days: int) -> list[sqlite3.Row]:
    """Return rows from reel_publishes joined with reels for last N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT rp.reel_id,
                   rp.network_name,
                   rp.remote_post_id,
                   rp.permalink,
                   rp.published_at,
                   r.rhetorical_move,
                   r.topic_tag,
                   r.label
            FROM reel_publishes rp
            JOIN reels r ON r.reel_id = rp.reel_id
            WHERE rp.remote_post_id IS NOT NULL
              AND rp.published_at IS NOT NULL
              AND rp.published_at >= ?
            ORDER BY rp.published_at DESC
            """,
            (cutoff,),
        ).fetchall()
    return rows


def fetch_one_reel(reel_id: str) -> list[sqlite3.Row]:
    with _conn() as c:
        rows = c.execute(
            """
            SELECT rp.reel_id, rp.network_name, rp.remote_post_id, rp.permalink,
                   rp.published_at, r.rhetorical_move, r.topic_tag, r.label
            FROM reel_publishes rp JOIN reels r ON r.reel_id = rp.reel_id
            WHERE rp.reel_id = ? AND rp.remote_post_id IS NOT NULL
            """,
            (reel_id,),
        ).fetchall()
    return rows


def collect_for_publish(row: sqlite3.Row) -> dict | None:
    """Call the network adapter's fetch_post_insights and return normalized dict.
    Returns None if the network has no adapter or fetch returns an error."""
    sys.path.insert(0, str(ROOT))
    from network_adapters import get_adapter

    adapter = get_adapter(row["network_name"])
    if adapter is None:
        logger.warning("No adapter for network %s", row["network_name"])
        return None

    try:
        raw = adapter.fetch_post_insights(row["remote_post_id"])
    except Exception as exc:
        logger.exception("fetch_post_insights failed for %s/%s: %s",
                         row["network_name"], row["remote_post_id"], exc)
        return None

    if isinstance(raw, dict) and raw.get("error"):
        logger.info("Insights for %s returned error: %s",
                    row["remote_post_id"], raw.get("error"))
        return None

    norm = _normalize_insights(raw)
    norm["raw_payload"] = json.dumps(raw, default=str)[:6000]
    return norm


def insert_metric(reel_id: str, network: str, metric: dict):
    with _conn() as c:
        c.execute(
            """
            INSERT INTO reel_metrics (
                reel_id, network_name, fetched_at,
                views, watch_time_sec, shares, saves, comments, likes,
                follows_attributed, raw_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reel_id, network, _iso_now(),
                metric.get("views"),
                metric.get("watch_time_sec"),
                metric.get("shares"),
                metric.get("saves"),
                metric.get("comments"),
                metric.get("likes"),
                metric.get("follows_attributed"),
                metric.get("raw_payload"),
            ),
        )


def run(days: int = 30, single_reel: str | None = None,
        sleep_between_calls: float = 1.0):
    if single_reel:
        rows = fetch_one_reel(single_reel)
        logger.info("Single-reel mode: %s (%d publishes found)", single_reel, len(rows))
    else:
        rows = fetch_recent_published(days)
        logger.info("ETL window: last %d days, %d publishes found", days, len(rows))

    inserted = 0
    skipped = 0
    for row in rows:
        metric = collect_for_publish(row)
        if metric is None:
            skipped += 1
            continue
        insert_metric(row["reel_id"], row["network_name"], metric)
        inserted += 1
        logger.info("✓ %s / %s — views=%s likes=%s",
                    row["reel_id"][:8], row["network_name"],
                    metric.get("views"), metric.get("likes"))
        time.sleep(sleep_between_calls)  # be polite to APIs

    logger.info("ETL done: inserted=%d skipped=%d", inserted, skipped)
    return inserted, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30, help="Window of publish dates to refresh")
    parser.add_argument("--once", action="store_true", help="Run once and exit (default behavior)")
    parser.add_argument("--reel-id", help="Single reel_id (debug)")
    parser.add_argument("--sleep", type=float, default=1.0, help="Seconds between API calls")
    args = parser.parse_args()

    inserted, skipped = run(
        days=args.days,
        single_reel=args.reel_id,
        sleep_between_calls=args.sleep,
    )
    sys.exit(0 if (inserted + skipped) > 0 else 1)


if __name__ == "__main__":
    main()
