"""
Threads Analytics — fetches post metrics via Meta Graph API.

Usage:
    python3 threads_analytics.py            # last 20 posts
    python3 threads_analytics.py 10         # last N posts
"""

import json
import os
import sys
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path

BASE_URL = "https://graph.threads.net/v1.0"

# Insights metrics supported by Threads API
METRICS = "views,likes,replies,reposts,quotes"


def _load_token() -> str:
    """Load THREADS_ACCESS_TOKEN — sol-bot/.env first, then parent /root/x-bot/.env."""
    for env_path in [Path(__file__).parent / ".env", Path("/root/x-bot/.env")]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("THREADS_ACCESS_TOKEN="):
                    return line.split("=", 1)[1].strip()
    return os.getenv("THREADS_ACCESS_TOKEN", "")


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "sol-bot/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def fetch_posts(limit: int = 20) -> dict:
    """
    Fetch the last `limit` Threads posts with their engagement metrics.

    Returns:
        {
            "posts": [...],
            "count": int,
            "error": str | None
        }
    """
    token = _load_token()
    if not token:
        return {"error": "No THREADS_ACCESS_TOKEN found in .env", "posts": [], "count": 0}

    # ── Step 1: fetch post list ───────────────────────────────────────────────
    fields = "id,text,timestamp,permalink,media_type"
    params = urllib.parse.urlencode({
        "fields": fields,
        "limit":  min(limit, 50),
        "access_token": token,
    })
    try:
        data = _get(f"{BASE_URL}/me/threads?{params}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": f"HTTP {e.code} fetching posts: {body}", "posts": [], "count": 0}
    except Exception as e:
        return {"error": f"Error fetching posts: {e}", "posts": [], "count": 0}

    posts = data.get("data", [])

    # ── Step 2: fetch insights per post ──────────────────────────────────────
    results = []
    for post in posts:
        post_id = post["id"]
        metrics = {"views": 0, "likes": 0, "replies": 0, "reposts": 0, "quotes": 0}

        try:
            iparams = urllib.parse.urlencode({
                "metric":       METRICS,
                "access_token": token,
            })
            idata = _get(f"{BASE_URL}/{post_id}/insights?{iparams}")
            for item in idata.get("data", []):
                name = item.get("name")
                if name not in metrics:
                    continue
                # Threads API returns lifetime totals under total_value
                tv = item.get("total_value", {})
                if tv:
                    metrics[name] = tv.get("value", 0)
                elif item.get("values"):
                    metrics[name] = item["values"][0].get("value", 0)
        except Exception:
            # Insights unavailable for very old posts or missing scope — skip silently
            pass

        results.append({
            "id":         post_id,
            "text":       (post.get("text") or "")[:140],
            "timestamp":  post.get("timestamp"),
            "permalink":  post.get("permalink"),
            "media_type": post.get("media_type", "TEXT"),
            **metrics,
        })

    return {"posts": results, "count": len(results), "error": None}


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    print(json.dumps(fetch_posts(limit=limit), indent=2))
