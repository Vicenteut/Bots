#!/usr/bin/env python3
"""Phase 1 — X Replies tracker backend.

1) DB migration: add is_reply, in_reply_to_user_handle, in_reply_to_tweet_id to posts.
2) Patch network_adapters/x.py — add XAdapter.fetch_recent_tweets() method.
3) Patch threads_analytics.py — add sync_x_replies() helper that pulls + stores + snapshots.
4) Patch sol_dashboard_api.py — add POST /api/networks/x/sync_replies endpoint.

Idempotent: safe to re-run.
"""

from __future__ import annotations
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path("/root/x-bot/sol-bot")
DB = ROOT / "threads_analytics.db"
X_PATH = ROOT / "network_adapters" / "x.py"
ANL_PATH = ROOT / "threads_analytics.py"
API_PATH = ROOT / "sol_dashboard_api.py"

# ---------------------------------------------------------------------------
# 1) DB migration
# ---------------------------------------------------------------------------
print("[1/4] DB migration: posts table")
with sqlite3.connect(DB) as c:
    cols = [r[1] for r in c.execute("PRAGMA table_info(posts)").fetchall()]
    additions = [
        ("is_reply", "INTEGER DEFAULT 0"),
        ("in_reply_to_user_handle", "TEXT"),
        ("in_reply_to_tweet_id", "TEXT"),
    ]
    for name, ddl in additions:
        if name in cols:
            print(f"  - {name}: already present")
        else:
            c.execute(f"ALTER TABLE posts ADD COLUMN {name} {ddl}")
            print(f"  + added {name}")
    c.execute("CREATE INDEX IF NOT EXISTS idx_posts_is_reply ON posts(is_reply)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_posts_network_reply ON posts(network_name, is_reply)")
    print("  + indexes ensured")

# ---------------------------------------------------------------------------
# 2) Patch XAdapter — add fetch_recent_tweets
# ---------------------------------------------------------------------------
print("[2/4] Patching network_adapters/x.py")
src = X_PATH.read_text()

if "def fetch_recent_tweets" in src:
    print("  - fetch_recent_tweets already exists, skipping")
else:
    # Insert after fetch_followers, before cost_estimate
    NEW_METHOD = '''
    def fetch_recent_tweets(
        self,
        limit: int = 100,
        only_replies: bool = True,
    ) -> dict[str, Any]:
        """Fetch the user's recent tweets via GET /2/users/{id}/tweets.

        Returns {ok, tweets: [...], error}. Each tweet dict:
            {tweet_id, text, created_at, is_reply, in_reply_to_user_id,
             in_reply_to_user_handle, in_reply_to_tweet_id,
             metrics: {views, likes, replies, reposts, quotes}}

        One API call covers up to 100 tweets. Costs $0.005 per call.
        """
        creds = _load_x_creds()
        if not self.is_connected():
            return {"ok": False, "tweets": [], "error": "not_configured"}
        try:
            client = _get_client(creds)
            me = client.get_me()
            user_id = me.data.get("id") if me.data else None
            if not user_id:
                _record_cost("read", "GET /2/users/me", ok=False, error="no user_id")
                return {"ok": False, "tweets": [], "error": "could not resolve user_id"}
            _record_cost("read", "GET /2/users/me", ok=True)

            resp = client.get_users_tweets(
                id=int(user_id),
                max_results=min(max(limit, 5), 100),
                tweet_fields=["created_at", "public_metrics", "referenced_tweets",
                              "in_reply_to_user_id", "lang"],
                expansions=["in_reply_to_user_id", "referenced_tweets.id.author_id"],
                user_fields=["username"],
            )
            _record_cost("read", "GET /2/users/{id}/tweets", ok=True)

            # Build user_id -> username lookup from includes
            user_map: dict[str, str] = {}
            includes = getattr(resp, "includes", {}) or {}
            for u in (includes.get("users") or []):
                uid = u.get("id") if isinstance(u, dict) else getattr(u, "id", None)
                uname = u.get("username") if isinstance(u, dict) else getattr(u, "username", None)
                if uid and uname:
                    user_map[str(uid)] = uname

            tweets_out = []
            for t in (resp.data or []):
                td = t if isinstance(t, dict) else t.data
                tid = str(td.get("id"))
                text = td.get("text") or ""
                created = td.get("created_at")
                metrics = td.get("public_metrics") or {}
                refs = td.get("referenced_tweets") or []
                in_reply_to_user_id = td.get("in_reply_to_user_id")
                in_reply_to_tweet_id = None
                is_reply_flag = False
                for r in refs:
                    rd = r if isinstance(r, dict) else (r.data if hasattr(r, "data") else {})
                    if rd.get("type") == "replied_to":
                        is_reply_flag = True
                        in_reply_to_tweet_id = str(rd.get("id"))
                        break
                if only_replies and not is_reply_flag:
                    continue
                handle = user_map.get(str(in_reply_to_user_id)) if in_reply_to_user_id else None
                tweets_out.append({
                    "tweet_id": tid,
                    "text": text,
                    "created_at": str(created) if created else None,
                    "is_reply": 1 if is_reply_flag else 0,
                    "in_reply_to_user_id": str(in_reply_to_user_id) if in_reply_to_user_id else None,
                    "in_reply_to_user_handle": handle,
                    "in_reply_to_tweet_id": in_reply_to_tweet_id,
                    "metrics": {
                        "views": int(metrics.get("impression_count") or 0),
                        "likes": int(metrics.get("like_count") or 0),
                        "replies": int(metrics.get("reply_count") or 0),
                        "reposts": int(metrics.get("retweet_count") or 0),
                        "quotes": int(metrics.get("quote_count") or 0),
                    },
                })
            return {"ok": True, "tweets": tweets_out, "error": None}
        except Exception as exc:
            _record_cost("read", "GET /2/users/{id}/tweets", ok=False, error=str(exc)[:300])
            return {"ok": False, "tweets": [], "error": str(exc)[:300]}

'''
    MARKER = "    def cost_estimate(self, action: str) -> float:"
    if MARKER not in src:
        print("  ! ERROR: cost_estimate marker not found in x.py")
        sys.exit(1)
    src = src.replace(MARKER, NEW_METHOD + MARKER, 1)
    X_PATH.write_text(src)
    print("  + fetch_recent_tweets injected before cost_estimate")

# ---------------------------------------------------------------------------
# 3) Patch threads_analytics.py — sync_x_replies
# ---------------------------------------------------------------------------
print("[3/4] Patching threads_analytics.py")
src = ANL_PATH.read_text()

if "def sync_x_replies" in src:
    print("  - sync_x_replies already exists, skipping")
else:
    NEW_FN = '''

def sync_x_replies(limit: int = 100) -> dict:
    """Pull recent X replies for @inequaliti, upsert into posts table, snapshot metrics.

    Returns {ok, fetched, inserted, updated, snapshots, error}.
    Costs ~$0.01 per call (1 read for user_id + 1 read for tweets list).
    """
    try:
        from network_adapters.x import XAdapter
    except Exception as exc:
        return {"ok": False, "fetched": 0, "inserted": 0, "updated": 0,
                "snapshots": 0, "error": f"adapter import failed: {exc}"}

    x = XAdapter()
    if not x.is_connected():
        return {"ok": False, "fetched": 0, "inserted": 0, "updated": 0,
                "snapshots": 0, "error": "X not connected"}

    res = x.fetch_recent_tweets(limit=limit, only_replies=True)
    if not res.get("ok"):
        return {"ok": False, "fetched": 0, "inserted": 0, "updated": 0,
                "snapshots": 0, "error": res.get("error") or "fetch failed"}

    tweets = res.get("tweets") or []
    handle = (x.handle or "@inequaliti").lstrip("@")
    now = _now_iso() if "_now_iso" in globals() else __import__("datetime").datetime.utcnow().isoformat() + "Z"

    inserted = 0
    updated = 0
    snapshots = 0
    with _connect() as conn:
        for t in tweets:
            tid = t["tweet_id"]
            text = t.get("text") or ""
            permalink = f"https://x.com/{handle}/status/{tid}"
            created = t.get("created_at") or now
            is_reply = int(t.get("is_reply") or 0)
            in_reply_user = t.get("in_reply_to_user_handle")
            in_reply_tweet = t.get("in_reply_to_tweet_id")
            metrics = t.get("metrics") or {}
            views = int(metrics.get("views") or 0)
            likes = int(metrics.get("likes") or 0)
            replies = int(metrics.get("replies") or 0)
            reposts = int(metrics.get("reposts") or 0)
            quotes = int(metrics.get("quotes") or 0)
            denom = max(views, 1)
            engagement = (likes + replies + reposts + quotes) / denom

            existing = conn.execute("SELECT post_id FROM posts WHERE post_id = ?", (tid,)).fetchone()
            if existing:
                conn.execute(
                    """UPDATE posts
                       SET text = ?, permalink = ?, last_seen_at = ?,
                           is_reply = ?, in_reply_to_user_handle = ?,
                           in_reply_to_tweet_id = ?, network_name = 'x',
                           char_count = ?
                       WHERE post_id = ?""",
                    (text, permalink, now, is_reply, in_reply_user,
                     in_reply_tweet, len(text), tid),
                )
                updated += 1
            else:
                conn.execute(
                    """INSERT INTO posts
                       (post_id, text, permalink, timestamp, media_type, tweet_type,
                        topic_tag, char_count, has_media, media_count,
                        first_seen_at, last_seen_at, source_name, network_name,
                        is_reply, in_reply_to_user_handle, in_reply_to_tweet_id)
                       VALUES (?, ?, ?, ?, 'TEXT', 'reply', 'general', ?, 0, 0,
                               ?, ?, NULL, 'x', ?, ?, ?)""",
                    (tid, text, permalink, created, len(text),
                     now, now, is_reply, in_reply_user, in_reply_tweet),
                )
                inserted += 1

            conn.execute(
                """INSERT INTO post_snapshots
                   (post_id, snapshot_at, views, likes, replies, reposts, quotes, engagement_rate)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (tid, now, views, likes, replies, reposts, quotes, round(engagement, 6)),
            )
            snapshots += 1
        conn.commit()

    return {"ok": True, "fetched": len(tweets), "inserted": inserted,
            "updated": updated, "snapshots": snapshots, "error": None,
            "synced_at": now}


def get_x_replies(limit: int = 50, sort: str = "recent") -> list[dict]:
    """Read x replies from posts joined to latest snapshot. sort = recent|views|engagement."""
    sort_sql = {
        "recent": "p.timestamp DESC",
        "views": "latest.views DESC",
        "engagement": "latest.engagement_rate DESC",
    }.get(sort, "p.timestamp DESC")

    with _connect() as conn:
        rows = conn.execute(f"""
            WITH latest AS (
                SELECT s.post_id,
                       s.views, s.likes, s.replies, s.reposts, s.quotes, s.engagement_rate,
                       s.snapshot_at,
                       ROW_NUMBER() OVER (PARTITION BY s.post_id ORDER BY s.snapshot_at DESC) AS rn
                FROM post_snapshots s
            )
            SELECT p.post_id, p.text, p.permalink, p.timestamp,
                   p.in_reply_to_user_handle, p.in_reply_to_tweet_id,
                   p.char_count,
                   COALESCE(latest.views, 0) AS views,
                   COALESCE(latest.likes, 0) AS likes,
                   COALESCE(latest.replies, 0) AS replies,
                   COALESCE(latest.reposts, 0) AS reposts,
                   COALESCE(latest.quotes, 0) AS quotes,
                   COALESCE(latest.engagement_rate, 0) AS engagement_rate,
                   latest.snapshot_at AS last_synced
            FROM posts p
            LEFT JOIN latest ON latest.post_id = p.post_id AND latest.rn = 1
            WHERE p.network_name = 'x' AND p.is_reply = 1
            ORDER BY {sort_sql}
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(zip([d[0] for d in conn.execute("SELECT 1").description] or [], r)) if False else dict(r) for r in rows]
'''
    src = src.rstrip() + "\n" + NEW_FN + "\n"
    ANL_PATH.write_text(src)
    print("  + sync_x_replies + get_x_replies appended")

# ---------------------------------------------------------------------------
# 4) Patch sol_dashboard_api.py — endpoint
# ---------------------------------------------------------------------------
print("[4/4] Patching sol_dashboard_api.py")
src = API_PATH.read_text()

if "/api/networks/x/sync_replies" in src:
    print("  - endpoint already present, skipping")
else:
    # Find the auth/x endpoint as anchor (we know it exists)
    ANCHOR = '@app.post("/api/networks/x/auth")'
    if ANCHOR not in src:
        print("  ! ERROR: anchor endpoint /api/networks/x/auth not found")
        sys.exit(1)

    NEW_ENDPOINT = '''@app.post("/api/networks/x/sync_replies")
def api_x_sync_replies(request: Request, limit: int = 100):
    _require_csrf(request)
    try:
        from threads_analytics import sync_x_replies
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"sync helper missing: {exc}")
    res = sync_x_replies(limit=max(5, min(int(limit), 100)))
    if not res.get("ok"):
        raise HTTPException(status_code=502, detail=res.get("error") or "sync failed")
    return res


@app.get("/api/networks/x/replies")
def api_x_replies(limit: int = 50, sort: str = "recent"):
    try:
        from threads_analytics import get_x_replies
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"helper missing: {exc}")
    rows = get_x_replies(limit=max(1, min(int(limit), 200)), sort=sort)
    return {"ok": True, "count": len(rows), "items": rows}


'''
    src = src.replace(ANCHOR, NEW_ENDPOINT + ANCHOR, 1)
    API_PATH.write_text(src)
    print("  + 2 endpoints injected before /api/networks/x/auth")

print("\nDONE. Restart sol-dashboard.service to load changes.")
