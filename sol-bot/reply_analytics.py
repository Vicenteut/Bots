#!/usr/bin/env python3
"""Reply Analytics - cron job that polls Threads API for engagement
on published replies and stores 1h/6h/24h/7d snapshots."""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import load_environment
load_environment()

DB_PATH = BASE_DIR / "data" / "replies.db"
BASE_URL = "https://graph.threads.net/v1.0"
METRICS = "views,likes,replies,reposts,quotes"

# bucket -> (lower seconds since publish, upper seconds since publish)
BUCKETS = {
    "1h":  (45 * 60,        2 * 3600),
    "6h":  (5 * 3600,       8 * 3600),
    "24h": (22 * 3600,      28 * 3600),
    "7d":  (6 * 86400,      8 * 86400),
}


def _token() -> str:
    return os.getenv("THREADS_ACCESS_TOKEN", "")


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "sol-bot/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _conn():
    return sqlite3.connect(str(DB_PATH))


def _due(now: int, published_at: int) -> list[str]:
    """Return list of buckets due for snapshot for a given published_at."""
    age = now - published_at
    out = []
    for name, (lo, hi) in BUCKETS.items():
        if lo <= age <= hi:
            out.append(name)
    return out


def _has_bucket(c, threads_id: str, bucket: str) -> bool:
    row = c.execute(
        "SELECT 1 FROM reply_analytics WHERE threads_reply_id=? AND bucket=?",
        (threads_id, bucket),
    ).fetchone()
    return row is not None


def _fetch_metrics(threads_id: str, token: str) -> dict:
    iparams = urllib.parse.urlencode({"metric": METRICS, "access_token": token})
    data = _get(BASE_URL + "/" + threads_id + "/insights?" + iparams)
    metrics = {"views": 0, "likes": 0, "replies": 0, "reposts": 0, "quotes": 0}
    for item in data.get("data", []):
        name = item.get("name")
        if name not in metrics:
            continue
        total_value = item.get("total_value")
        if isinstance(total_value, dict):
            metrics[name] = int(total_value.get("value") or 0)
        elif item.get("values"):
            metrics[name] = int(item["values"][0].get("value") or 0)
    return metrics


def run() -> int:
    if not DB_PATH.exists():
        print("[reply_analytics] no DB at " + str(DB_PATH))
        return 0
    token = _token()
    if not token:
        print("[reply_analytics] THREADS_ACCESS_TOKEN missing")
        return 0
    now = int(time.time())
    snapped = 0
    with _conn() as c:
        rows = c.execute(
            "SELECT threads_reply_id, published_at FROM reply_chats "
            "WHERE status='published' AND threads_reply_id IS NOT NULL "
            "AND published_at IS NOT NULL"
        ).fetchall()
        for tid, pub_at in rows:
            for bucket in _due(now, int(pub_at)):
                if _has_bucket(c, tid, bucket):
                    continue
                try:
                    m = _fetch_metrics(tid, token)
                except urllib.error.HTTPError as e:
                    print("[reply_analytics] HTTP " + str(e.code) + " for " + tid + " bucket " + bucket)
                    continue
                except Exception as e:
                    print("[reply_analytics] error for " + tid + " bucket " + bucket + ": " + str(e)[:200])
                    continue
                c.execute(
                    "INSERT OR REPLACE INTO reply_analytics"
                    "(threads_reply_id, bucket, snapshot_at, likes, replies, views, reposts) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (tid, bucket, now, m["likes"], m["replies"], m["views"], m["reposts"]),
                )
                snapped += 1
                print("[reply_analytics] " + tid + " " + bucket + " -> " + str(m))
    return snapped


if __name__ == "__main__":
    n = run()
    print("[reply_analytics] " + str(n) + " snapshots taken")
