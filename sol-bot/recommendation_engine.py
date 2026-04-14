"""Threads analytics recommendation helpers for Sol."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from topic_utils import classify_topic

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "threads_analytics.db"
MIN_SAMPLE = 5
HIGH_CONF_SAMPLE = 20

FORMAT_DEFAULT_RANGES = {
    "WIRE": "180-260 chars",
    "DEBATE": "220-340 chars",
    "ANALISIS": "341-430 chars",
    "CONEXION": "341-430 chars",
    "COMBINADA": "431-500 chars",
    "MIXED": "431-500 chars",
    "ORIGINAL": "260-340 chars",
    "UNKNOWN": "260-340 chars",
}


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _latest_cte(days: int = 90) -> tuple[str, str]:
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()
    return """
        WITH latest AS (
            SELECT ps.*
            FROM post_snapshots ps
            JOIN (
                SELECT post_id, MAX(snapshot_at) AS max_snapshot_at
                FROM post_snapshots
                GROUP BY post_id
            ) x ON x.post_id = ps.post_id AND x.max_snapshot_at = ps.snapshot_at
        )
    """, since


def _bucket_expr() -> str:
    return """
        CASE
            WHEN p.char_count < 260 THEN '<260 chars'
            WHEN p.char_count BETWEEN 260 AND 340 THEN '260-340 chars'
            WHEN p.char_count BETWEEN 341 AND 430 THEN '341-430 chars'
            ELSE '431-500 chars'
        END
    """


def _fallback_format(topic: str, text: str, fallback: str | None) -> str:
    if fallback:
        return fallback.upper()
    low = (text or "").lower()
    if topic in {"crypto", "mercados"} and len(text) >= 140:
        return "COMBINADA"
    if len(text) <= 140 or low.startswith(("just in", "breaking", "urgent")):
        return "WIRE"
    return "ANALISIS"


def _confidence(posts: int, used_analytics: bool) -> str:
    if not used_analytics:
        return "low"
    if posts >= HIGH_CONF_SAMPLE:
        return "high"
    return "medium"


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return {k: row[k] for k in row.keys()} if row else None


def recommend_for_alert(entry: dict[str, Any], *, db_path: Path = DB_PATH, days: int = 90, fallback_format: str | None = None) -> dict[str, Any]:
    headline = entry.get("headline") or {}
    text = f"{headline.get('title', '')}\n{headline.get('summary', '')}".strip()
    topic = (entry.get("topic_guess") or classify_topic(text) or "general").lower()
    fallback = _fallback_format(topic, text, fallback_format or entry.get("suggested_format"))
    default = {
        "format": fallback,
        "length_range": FORMAT_DEFAULT_RANGES.get(fallback, FORMAT_DEFAULT_RANGES["UNKNOWN"]),
        "media": "neutral",
        "confidence": "low",
        "sample_size": 0,
        "reason": f"Using rule-based fallback for {topic}; not enough Threads analytics yet.",
        "source": "fallback",
        "topic": topic,
    }
    if not db_path.exists():
        return default

    cte, since = _latest_cte(days)
    try:
        with _connect(db_path) as conn:
            fmt = _row_dict(conn.execute(
                cte + """
                SELECT p.tweet_type AS label, COUNT(*) AS posts,
                       AVG(latest.engagement_rate) AS avg_engagement_rate,
                       AVG(latest.views) AS avg_views
                FROM posts p
                JOIN latest ON latest.post_id = p.post_id
                WHERE COALESCE(p.timestamp, p.first_seen_at) >= ?
                  AND LOWER(COALESCE(p.topic_tag, 'general')) = ?
                  AND COALESCE(p.tweet_type, '') NOT IN ('', 'UNKNOWN')
                GROUP BY p.tweet_type
                HAVING posts >= ?
                ORDER BY avg_engagement_rate DESC, avg_views DESC, posts DESC
                LIMIT 1
                """,
                (since, topic, MIN_SAMPLE),
            ).fetchone())
            used_analytics = bool(fmt)
            recommended_format = str((fmt or {}).get("label") or fallback).upper()
            sample = int((fmt or {}).get("posts") or 0)

            length = _row_dict(conn.execute(
                cte + f"""
                SELECT {_bucket_expr()} AS label, COUNT(*) AS posts,
                       AVG(latest.engagement_rate) AS avg_engagement_rate,
                       AVG(latest.views) AS avg_views
                FROM posts p
                JOIN latest ON latest.post_id = p.post_id
                WHERE COALESCE(p.timestamp, p.first_seen_at) >= ?
                  AND LOWER(COALESCE(p.topic_tag, 'general')) = ?
                  AND UPPER(COALESCE(p.tweet_type, '')) = ?
                GROUP BY label
                HAVING posts >= ?
                ORDER BY avg_engagement_rate DESC, avg_views DESC, posts DESC
                LIMIT 1
                """,
                (since, topic, recommended_format, MIN_SAMPLE),
            ).fetchone())

            media_rows = [dict(r) for r in conn.execute(
                cte + """
                SELECT CASE WHEN p.has_media = 1 THEN 'media' ELSE 'text' END AS label,
                       COUNT(*) AS posts,
                       AVG(latest.engagement_rate) AS avg_engagement_rate,
                       AVG(latest.views) AS avg_views
                FROM posts p
                JOIN latest ON latest.post_id = p.post_id
                WHERE COALESCE(p.timestamp, p.first_seen_at) >= ?
                  AND LOWER(COALESCE(p.topic_tag, 'general')) = ?
                  AND UPPER(COALESCE(p.tweet_type, '')) = ?
                GROUP BY label
                HAVING posts >= ?
                ORDER BY avg_engagement_rate DESC, avg_views DESC
                """,
                (since, topic, recommended_format, MIN_SAMPLE),
            )]
    except Exception as exc:
        default["reason"] = f"Fallback because analytics recommendation failed: {str(exc)[:120]}"
        return default

    length_range = str((length or {}).get("label") or FORMAT_DEFAULT_RANGES.get(recommended_format, FORMAT_DEFAULT_RANGES["UNKNOWN"]))
    media = "neutral"
    if len(media_rows) >= 2:
        top, second = media_rows[0], media_rows[1]
        top_eng = float(top.get("avg_engagement_rate") or 0)
        second_eng = float(second.get("avg_engagement_rate") or 0)
        if top_eng > second_eng * 1.15:
            media = str(top.get("label") or "neutral")

    if used_analytics:
        reason = f"{recommended_format} leads {topic} in Threads analytics ({sample} posts)."
        if length:
            reason += f" Best length: {length_range}."
        if media != "neutral":
            reason += f" {media.capitalize()} has stronger engagement."
    else:
        reason = default["reason"]

    return {
        "format": recommended_format,
        "length_range": length_range,
        "media": media,
        "confidence": _confidence(sample, used_analytics),
        "sample_size": sample,
        "reason": reason,
        "source": "analytics" if used_analytics else "fallback",
        "topic": topic,
    }


def get_learning_summary(*, db_path: Path = DB_PATH, days: int = 90) -> dict[str, Any]:
    if not db_path.exists():
        return {"error": "threads_analytics.db has no data yet", "best_by_topic": [], "length_ranges": [], "media": []}
    cte, since = _latest_cte(days)
    try:
        with _connect(db_path) as conn:
            best_by_topic = [dict(r) for r in conn.execute(
                cte + """
                SELECT topic_tag, tweet_type, COUNT(*) AS posts,
                       ROUND(AVG(latest.engagement_rate), 4) AS avg_engagement_rate,
                       ROUND(AVG(latest.views), 2) AS avg_views
                FROM posts p
                JOIN latest ON latest.post_id = p.post_id
                WHERE COALESCE(p.timestamp, p.first_seen_at) >= ?
                  AND COALESCE(tweet_type, '') NOT IN ('', 'UNKNOWN')
                GROUP BY topic_tag, tweet_type
                HAVING posts >= ?
                ORDER BY topic_tag ASC, avg_engagement_rate DESC, avg_views DESC
                """,
                (since, MIN_SAMPLE),
            )]
            collapsed = {}
            for row in best_by_topic:
                collapsed.setdefault(row["topic_tag"] or "general", row)
            lengths = [dict(r) for r in conn.execute(
                cte + f"""
                SELECT {_bucket_expr()} AS label, COUNT(*) AS posts,
                       ROUND(AVG(latest.engagement_rate), 4) AS avg_engagement_rate,
                       ROUND(AVG(latest.views), 2) AS avg_views
                FROM posts p
                JOIN latest ON latest.post_id = p.post_id
                WHERE COALESCE(p.timestamp, p.first_seen_at) >= ?
                GROUP BY label
                HAVING posts >= ?
                ORDER BY avg_engagement_rate DESC, avg_views DESC
                """,
                (since, MIN_SAMPLE),
            )]
            media = [dict(r) for r in conn.execute(
                cte + """
                SELECT CASE WHEN p.has_media = 1 THEN 'media' ELSE 'text' END AS label,
                       COUNT(*) AS posts,
                       ROUND(AVG(latest.engagement_rate), 4) AS avg_engagement_rate,
                       ROUND(AVG(latest.views), 2) AS avg_views
                FROM posts p
                JOIN latest ON latest.post_id = p.post_id
                WHERE COALESCE(p.timestamp, p.first_seen_at) >= ?
                GROUP BY label
                HAVING posts >= ?
                ORDER BY avg_engagement_rate DESC, avg_views DESC
                """,
                (since, MIN_SAMPLE),
            )]
    except Exception as exc:
        return {"error": str(exc)[:160], "best_by_topic": [], "length_ranges": [], "media": []}
    return {"error": None, "best_by_topic": list(collapsed.values()), "length_ranges": lengths, "media": media}
