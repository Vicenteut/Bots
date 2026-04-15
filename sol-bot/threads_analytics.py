"""
Threads Analytics — persistent Threads-only analytics for Sol.

Usage:
    python3 threads_analytics.py fetch --limit 20
    python3 threads_analytics.py sync --limit 50
    python3 threads_analytics.py summary --days 7

Backwards compatible:
    python3 threads_analytics.py 10
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from topic_utils import classify_topic

LOG_DIR = BASE_DIR.parent / "logs"
DB_PATH = BASE_DIR / "threads_analytics.db"
PUBLISH_LOG = LOG_DIR / "publish_log.json"
BASE_URL = "https://graph.threads.net/v1.0"
METRICS = "views,likes,replies,reposts,quotes"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _load_token() -> str:
    """Load THREADS_ACCESS_TOKEN — sol-bot/.env first, then parent /root/x-bot/.env."""
    for env_path in [BASE_DIR / ".env", Path("/root/x-bot/.env")]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("THREADS_ACCESS_TOKEN="):
                    return line.split("=", 1)[1].strip()
    return os.getenv("THREADS_ACCESS_TOKEN", "")


def _get(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "sol-bot/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode("utf-8", "replace")[:500]
        except Exception:
            body = ""
        return f"HTTP {exc.code}: {body}"
    return str(exc)[:500]


def fetch_posts(limit: int = 20) -> dict[str, Any]:
    """Fetch recent Threads posts with live metrics. This keeps the old API shape."""
    token = _load_token()
    if not token:
        return {"error": "No THREADS_ACCESS_TOKEN found in .env", "posts": [], "count": 0}

    params = urllib.parse.urlencode({
        "fields": "id,text,timestamp,permalink,media_type",
        "limit": min(max(1, limit), 50),
        "access_token": token,
    })
    try:
        data = _get(f"{BASE_URL}/me/threads?{params}")
    except Exception as exc:
        return {"error": f"Error fetching posts: {_safe_error(exc)}", "posts": [], "count": 0}

    results: list[dict[str, Any]] = []
    for post in data.get("data", []):
        post_id = post.get("id")
        if not post_id:
            continue
        metrics = {"views": 0, "likes": 0, "replies": 0, "reposts": 0, "quotes": 0}
        try:
            iparams = urllib.parse.urlencode({"metric": METRICS, "access_token": token})
            idata = _get(f"{BASE_URL}/{post_id}/insights?{iparams}")
            for item in idata.get("data", []):
                name = item.get("name")
                if name not in metrics:
                    continue
                total_value = item.get("total_value") or {}
                if total_value:
                    metrics[name] = int(total_value.get("value") or 0)
                elif item.get("values"):
                    metrics[name] = int(item["values"][0].get("value") or 0)
        except Exception:
            # Some posts may not expose insights yet. Keep the post and zeros.
            pass

        text = post.get("text") or ""
        results.append({
            "id": post_id,
            "text": text[:280],
            "timestamp": post.get("timestamp"),
            "permalink": post.get("permalink"),
            "media_type": post.get("media_type", "TEXT"),
            **metrics,
        })

    return {"posts": results, "count": len(results), "error": None}


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS posts (
            post_id TEXT PRIMARY KEY,
            text TEXT,
            permalink TEXT,
            timestamp TEXT,
            media_type TEXT,
            tweet_type TEXT DEFAULT 'UNKNOWN',
            topic_tag TEXT DEFAULT 'general',
            char_count INTEGER DEFAULT 0,
            has_media INTEGER DEFAULT 0,
            media_count INTEGER DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS post_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id TEXT NOT NULL,
            snapshot_at TEXT NOT NULL,
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            replies INTEGER DEFAULT 0,
            reposts INTEGER DEFAULT 0,
            quotes INTEGER DEFAULT 0,
            engagement_rate REAL DEFAULT 0,
            FOREIGN KEY(post_id) REFERENCES posts(post_id)
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_post_at ON post_snapshots(post_id, snapshot_at);
        CREATE INDEX IF NOT EXISTS idx_posts_timestamp ON posts(timestamp);
        CREATE INDEX IF NOT EXISTS idx_posts_type ON posts(tweet_type);
        CREATE INDEX IF NOT EXISTS idx_posts_topic ON posts(topic_tag);

        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            status TEXT NOT NULL,
            count INTEGER DEFAULT 0,
            error TEXT
        );
        """
    )
    conn.commit()


def _read_publish_metadata() -> dict[str, dict[str, Any]]:
    if not PUBLISH_LOG.exists():
        return {}
    try:
        data = json.loads(PUBLISH_LOG.read_text())
    except Exception:
        return {}
    if not isinstance(data, list):
        return {}

    metadata: dict[str, dict[str, Any]] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        post_id = entry.get("tweet_id")
        if not post_id:
            continue
        metadata[str(post_id)] = entry
    return metadata


def _enrich_post(post: dict[str, Any], metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    post_id = str(post.get("id") or "")
    meta = metadata.get(post_id, {})
    text = post.get("text") or meta.get("text_preview") or ""
    media_type = post.get("media_type") or meta.get("media_type") or "TEXT"
    tweet_type = (meta.get("tweet_type") or "UNKNOWN").upper()
    topic_tag = (meta.get("topic_tag") or classify_topic(text)).lower()
    char_count = int(meta.get("char_count") or len(text))
    media_count = int(meta.get("media_count") or (1 if media_type and media_type.upper() != "TEXT" else 0))
    has_media = 1 if bool(meta.get("has_media") or media_count or media_type.upper() != "TEXT") else 0
    return {
        "post_id": post_id,
        "text": text,
        "permalink": post.get("permalink"),
        "timestamp": post.get("timestamp"),
        "media_type": str(media_type).lower(),
        "tweet_type": tweet_type,
        "topic_tag": topic_tag,
        "char_count": char_count,
        "has_media": has_media,
        "media_count": media_count,
    }


def sync_posts(limit: int = 50, db_path: Path = DB_PATH) -> dict[str, Any]:
    fetched = fetch_posts(limit=limit)
    if fetched.get("error"):
        with _connect(db_path) as conn:
            init_db(conn)
            conn.execute(
                "INSERT INTO sync_runs(timestamp, status, count, error) VALUES (?, ?, ?, ?)",
                (_now_iso(), "ERROR", 0, fetched["error"][:500]),
            )
            conn.commit()
        return {"success": False, "count": 0, "error": fetched["error"]}

    metadata = _read_publish_metadata()
    now = _now_iso()
    count = 0
    with _connect(db_path) as conn:
        init_db(conn)
        for post in fetched.get("posts", []):
            enriched = _enrich_post(post, metadata)
            if not enriched["post_id"]:
                continue
            conn.execute(
                """
                INSERT INTO posts(
                    post_id, text, permalink, timestamp, media_type, tweet_type, topic_tag,
                    char_count, has_media, media_count, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(post_id) DO UPDATE SET
                    text=excluded.text,
                    permalink=excluded.permalink,
                    timestamp=excluded.timestamp,
                    media_type=excluded.media_type,
                    tweet_type=excluded.tweet_type,
                    topic_tag=excluded.topic_tag,
                    char_count=excluded.char_count,
                    has_media=excluded.has_media,
                    media_count=excluded.media_count,
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    enriched["post_id"], enriched["text"], enriched["permalink"],
                    enriched["timestamp"], enriched["media_type"], enriched["tweet_type"],
                    enriched["topic_tag"], enriched["char_count"], enriched["has_media"],
                    enriched["media_count"], now, now,
                ),
            )
            views = int(post.get("views") or 0)
            likes = int(post.get("likes") or 0)
            replies = int(post.get("replies") or 0)
            reposts = int(post.get("reposts") or 0)
            quotes = int(post.get("quotes") or 0)
            engagement_rate = ((likes + replies + reposts + quotes) / views) if views else 0
            conn.execute(
                """
                INSERT INTO post_snapshots(
                    post_id, snapshot_at, views, likes, replies, reposts, quotes, engagement_rate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (enriched["post_id"], now, views, likes, replies, reposts, quotes, engagement_rate),
            )
            count += 1
        conn.execute(
            "INSERT INTO sync_runs(timestamp, status, count, error) VALUES (?, ?, ?, ?)",
            (now, "OK", count, None),
        )
        conn.commit()
    return {"success": True, "count": count, "error": None}


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _latest_snapshot_cte(days: int) -> tuple[str, str]:
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
    cte = """
        WITH latest AS (
            SELECT ps.*
            FROM post_snapshots ps
            JOIN (
                SELECT post_id, MAX(snapshot_at) AS max_snapshot_at
                FROM post_snapshots
                GROUP BY post_id
            ) x ON x.post_id = ps.post_id AND x.max_snapshot_at = ps.snapshot_at
        )
    """
    return cte, since


def get_analytics(
    days: int = 7,
    limit: int = 20,
    db_path: Path = DB_PATH,
    sort: str = "date",
    format: str | None = None,
    topic: str | None = None,
    media: str | None = None,
) -> dict[str, Any]:
    days = max(1, min(days, 90))
    limit = max(1, min(limit, 50))
    sort_key = (sort or "date").strip().lower()
    sort_sql = {
        "views": "latest.views DESC, COALESCE(p.timestamp, p.last_seen_at) DESC",
        "likes": "latest.likes DESC, latest.views DESC, COALESCE(p.timestamp, p.last_seen_at) DESC",
        "replies": "latest.replies DESC, latest.views DESC, COALESCE(p.timestamp, p.last_seen_at) DESC",
        "comments": "latest.replies DESC, latest.views DESC, COALESCE(p.timestamp, p.last_seen_at) DESC",
        "engagement": "latest.engagement_rate DESC, latest.views DESC, COALESCE(p.timestamp, p.last_seen_at) DESC",
        "total_engagement": "(latest.likes + latest.replies + latest.reposts + latest.quotes) DESC, latest.views DESC, COALESCE(p.timestamp, p.last_seen_at) DESC",
        "date": "COALESCE(p.timestamp, p.last_seen_at) DESC",
    }.get(sort_key, "COALESCE(p.timestamp, p.last_seen_at) DESC")
    fmt_filter = (format or "").strip().upper()
    topic_filter = (topic or "").strip().lower()
    media_filter = (media or "").strip().lower()
    if not db_path.exists():
        return {
            "error": "threads_analytics.db has no data yet. Run sync first.",
            "summary": {}, "by_format": [], "by_topic": [], "by_media": [],
            "recent_posts": [], "last_sync": None,
        }

    cte, since = _latest_snapshot_cte(days)
    filters = ["COALESCE(p.timestamp, p.first_seen_at) >= ?"]
    params = [since]
    if fmt_filter and fmt_filter != "ALL":
        filters.append("UPPER(COALESCE(p.tweet_type, 'UNKNOWN')) = ?")
        params.append(fmt_filter)
    if topic_filter and topic_filter != "all":
        filters.append("LOWER(COALESCE(p.topic_tag, 'general')) = ?")
        params.append(topic_filter)
    if media_filter == "media":
        filters.append("p.has_media = 1")
    elif media_filter == "text":
        filters.append("COALESCE(p.has_media, 0) = 0")
    where_sql = " AND ".join(filters)

    with _connect(db_path) as conn:
        init_db(conn)
        last_sync_row = conn.execute(
            "SELECT timestamp, status, count, error FROM sync_runs ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        last_sync = _row_to_dict(last_sync_row) if last_sync_row else None

        summary = conn.execute(
            cte + """
            SELECT
                COUNT(*) AS posts,
                COALESCE(SUM(latest.views), 0) AS views,
                COALESCE(SUM(latest.likes), 0) AS likes,
                COALESCE(SUM(latest.replies), 0) AS replies,
                COALESCE(SUM(latest.reposts), 0) AS reposts,
                COALESCE(SUM(latest.quotes), 0) AS quotes,
                COALESCE(AVG(latest.views), 0) AS avg_views,
                COALESCE(AVG(latest.engagement_rate), 0) AS avg_engagement_rate
            FROM posts p
            JOIN latest ON latest.post_id = p.post_id
            WHERE """ + where_sql + """
            """,
            params,
        ).fetchone()

        def grouped(field: str) -> list[dict[str, Any]]:
            return [
                _row_to_dict(row) for row in conn.execute(
                    cte + f"""
                    SELECT
                        COALESCE(NULLIF(p.{field}, ''), 'UNKNOWN') AS label,
                        COUNT(*) AS posts,
                        ROUND(AVG(latest.views), 2) AS avg_views,
                        ROUND(AVG(latest.likes), 2) AS avg_likes,
                        ROUND(AVG(latest.replies), 2) AS avg_replies,
                        ROUND(AVG(latest.engagement_rate), 4) AS avg_engagement_rate,
                        SUM(latest.views) AS views
                    FROM posts p
                    JOIN latest ON latest.post_id = p.post_id
                    WHERE COALESCE(p.timestamp, p.first_seen_at) >= ?
                    GROUP BY label
                    ORDER BY avg_views DESC, posts DESC
                    LIMIT 12
                    """,
                    (since,),
                )
            ]

        by_media = [
            _row_to_dict(row) for row in conn.execute(
                cte + """
                SELECT
                    CASE WHEN p.has_media = 1 THEN 'media' ELSE 'text' END AS label,
                    COUNT(*) AS posts,
                    ROUND(AVG(latest.views), 2) AS avg_views,
                    ROUND(AVG(latest.engagement_rate), 4) AS avg_engagement_rate,
                    SUM(latest.views) AS views
                FROM posts p
                JOIN latest ON latest.post_id = p.post_id
                WHERE COALESCE(p.timestamp, p.first_seen_at) >= ?
                GROUP BY label
                ORDER BY avg_views DESC
                """,
                (since,),
            )
        ]

        recent_posts = [
            _row_to_dict(row) for row in conn.execute(
                cte + """
                SELECT
                    p.post_id AS id, p.text, p.permalink, p.timestamp, p.media_type,
                    p.tweet_type, p.topic_tag, p.char_count, p.has_media, p.media_count,
                    latest.views, latest.likes, latest.replies, latest.reposts, latest.quotes,
                    ROUND(latest.engagement_rate, 4) AS engagement_rate,
                    (latest.likes + latest.replies + latest.reposts + latest.quotes) AS total_engagement
                FROM posts p
                JOIN latest ON latest.post_id = p.post_id
                WHERE """ + where_sql + f"""
                ORDER BY {sort_sql}
                LIMIT ?
                """,
                [*params, limit],
            )
        ]

    return {
        "error": last_sync.get("error") if last_sync and last_sync.get("status") != "OK" else None,
        "days": days,
        "summary": _row_to_dict(summary) if summary else {},
        "by_format": grouped("tweet_type"),
        "by_topic": grouped("topic_tag"),
        "by_media": by_media,
        "recent_posts": recent_posts,
        "last_sync": last_sync,
        "filters": {
            "sort": sort_key,
            "format": fmt_filter or "ALL",
            "topic": topic_filter or "all",
            "media": media_filter or "all",
        },
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0].isdigit():
        print(json.dumps(fetch_posts(limit=int(argv[0])), indent=2))
        return 0
    if not argv:
        print(json.dumps(fetch_posts(limit=20), indent=2))
        return 0

    parser = argparse.ArgumentParser(description="Threads analytics for Sol")
    sub = parser.add_subparsers(dest="command", required=True)
    p_fetch = sub.add_parser("fetch", help="Fetch live Threads metrics")
    p_fetch.add_argument("--limit", type=int, default=20)
    p_sync = sub.add_parser("sync", help="Fetch and persist Threads metrics")
    p_sync.add_argument("--limit", type=int, default=50)
    p_summary = sub.add_parser("summary", help="Read persisted analytics summary")
    p_summary.add_argument("--days", type=int, default=7)
    p_summary.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)

    if args.command == "fetch":
        print(json.dumps(fetch_posts(limit=args.limit), indent=2))
    elif args.command == "sync":
        result = sync_posts(limit=args.limit)
        print(json.dumps(result, indent=2))
        return 0 if result.get("success") else 1
    elif args.command == "summary":
        print(json.dumps(get_analytics(days=args.days, limit=args.limit), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
