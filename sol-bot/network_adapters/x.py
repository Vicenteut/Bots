"""
network_adapters/x.py — XAdapter (Sprint 2: real X API v2 + cost tracking).

Pricing model: pay-per-use since Feb 2026.
    $0.01  per write (POST /2/tweets, etc.)
    $0.005 per read  (GET /2/tweets/{id}, GET /2/users/me, etc.)
    Cap: 2,000,000 reads/month before requiring Enterprise.

Auth: OAuth 1.0a User Context (required for posting on behalf of a user).
Credentials live in /root/x-bot/sol-bot/.env (sol-bot/.env wins over /root/x-bot/.env):
    X_API_KEY
    X_API_SECRET
    X_ACCESS_TOKEN
    X_ACCESS_TOKEN_SECRET

Cost tracking persists to /root/x-bot/sol-bot/data/x_api_costs.db.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import NetworkAdapter

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATHS = [BASE_DIR / ".env", Path("/root/x-bot/.env")]
COSTS_DB = BASE_DIR / "data" / "x_api_costs.db"

# Pay-per-use pricing (Feb 2026, source: docs.x.com/x-api/getting-started/about-x-api)
COST_PER_WRITE_USD = 0.01
COST_PER_READ_USD = 0.005


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_x_creds() -> dict[str, str]:
    """Read X_* keys from .env files (sol-bot/.env wins). Env vars override."""
    needed = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN",
              "X_ACCESS_TOKEN_SECRET", "X_BEARER_TOKEN"]
    creds: dict[str, str] = {}
    for env_path in ENV_PATHS:
        if not env_path.exists():
            continue
        try:
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key in needed and val:
                    creds.setdefault(key, val)
        except Exception:
            continue
    for k in needed:
        v = os.getenv(k)
        if v:
            creds[k] = v
    return creds


def _init_costs_db() -> None:
    COSTS_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(COSTS_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS x_api_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                action TEXT NOT NULL,        -- "publish" | "read" | "insights" | "followers"
                endpoint TEXT,                -- e.g. "POST /2/tweets"
                cost_usd REAL NOT NULL,
                ok INTEGER NOT NULL DEFAULT 1,
                error TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_x_costs_ts ON x_api_calls(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_x_costs_action ON x_api_calls(action)")
        conn.commit()


def _record_cost(action: str, endpoint: str, ok: bool, error: str | None = None) -> None:
    """Persist a single API call cost. Never raises."""
    try:
        _init_costs_db()
        cost = COST_PER_WRITE_USD if action == "publish" else COST_PER_READ_USD
        # Failed calls still cost (X charges per attempt for most endpoints).
        # If you want to NOT charge for failures, gate this behind `if ok:`.
        with sqlite3.connect(COSTS_DB) as conn:
            conn.execute(
                "INSERT INTO x_api_calls(ts, action, endpoint, cost_usd, ok, error) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (_now_iso(), action, endpoint, cost, 1 if ok else 0, error),
            )
            conn.commit()
    except Exception:
        pass  # cost tracking must never break a publish


def get_cost_summary(days: int = 30) -> dict[str, Any]:
    """Returns total + breakdown by action for last N days. Used by /api/networks."""
    try:
        _init_costs_db()
        from datetime import timedelta
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with sqlite3.connect(COSTS_DB) as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS s, COUNT(*) AS n "
                "FROM x_api_calls WHERE ts >= ?",
                (since,),
            ).fetchone()
            by_action = conn.execute(
                "SELECT action, COUNT(*) AS n, COALESCE(SUM(cost_usd), 0) AS cost "
                "FROM x_api_calls WHERE ts >= ? GROUP BY action ORDER BY cost DESC",
                (since,),
            ).fetchall()
        return {
            "days": days,
            "total_usd": round(total["s"], 4),
            "total_calls": total["n"],
            "by_action": [dict(r) for r in by_action],
        }
    except Exception as exc:
        return {"days": days, "total_usd": 0.0, "total_calls": 0, "error": str(exc)[:200]}


def _get_client(creds: dict[str, str]):
    """Build a tweepy.Client for X API v2 user-context calls."""
    import tweepy
    return tweepy.Client(
        bearer_token=creds.get("X_BEARER_TOKEN") or None,
        consumer_key=creds.get("X_API_KEY"),
        consumer_secret=creds.get("X_API_SECRET"),
        access_token=creds.get("X_ACCESS_TOKEN"),
        access_token_secret=creds.get("X_ACCESS_TOKEN_SECRET"),
        wait_on_rate_limit=False,
    )


class XAdapter(NetworkAdapter):
    name = "x"
    label = "X (Twitter)"
    handle = "@inequaliti"
    char_limit = 280

    COST_PER_WRITE_USD = COST_PER_WRITE_USD
    COST_PER_READ_USD = COST_PER_READ_USD

    def is_connected(self) -> bool:
        creds = _load_x_creds()
        return bool(
            creds.get("X_API_KEY")
            and creds.get("X_API_SECRET")
            and creds.get("X_ACCESS_TOKEN")
            and creds.get("X_ACCESS_TOKEN_SECRET")
        )

    def auth_status(self) -> dict[str, Any]:
        """Live verification via GET /2/users/me. Costs $0.005."""
        creds = _load_x_creds()
        if not self.is_connected():
            missing = [k for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN",
                                   "X_ACCESS_TOKEN_SECRET") if not creds.get(k)]
            return {
                "ok": False,
                "error": f"not_configured: missing {', '.join(missing)}",
                "checked_at": _now_iso(),
            }
        try:
            client = _get_client(creds)
            resp = client.get_me(user_fields=["username", "id"])
            _record_cost("read", "GET /2/users/me", ok=True)
            user = resp.data
            return {
                "ok": True,
                "error": None,
                "checked_at": _now_iso(),
                "username": getattr(user, "username", None),
                "user_id": str(getattr(user, "id", "")),
            }
        except Exception as exc:
            _record_cost("read", "GET /2/users/me", ok=False, error=str(exc)[:300])
            return {"ok": False, "error": str(exc)[:300], "checked_at": _now_iso()}

    def publish(
        self,
        text: str,
        media: list[str] | None = None,
        in_reply_to: str | None = None,
    ) -> dict[str, Any]:
        creds = _load_x_creds()
        if not self.is_connected():
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": "not_configured"}

        if media:
            # Media upload requires X API v1.1 + multipart. Punted to a future sprint.
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": "media_upload_not_implemented"}

        if len(text) > self.char_limit:
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(),
                    "error": f"text exceeds {self.char_limit} chars ({len(text)})"}

        try:
            client = _get_client(creds)
            kwargs: dict[str, Any] = {"text": text}
            if in_reply_to:
                kwargs["in_reply_to_tweet_id"] = str(in_reply_to)
            resp = client.create_tweet(**kwargs)
            _record_cost("publish", "POST /2/tweets", ok=True)
            tweet_id = str(resp.data.get("id"))
            handle = self.handle.lstrip("@")
            permalink = f"https://x.com/{handle}/status/{tweet_id}"
            return {"ok": True, "network_post_id": tweet_id,
                    "permalink": permalink, "ts": _now_iso(), "error": None}
        except Exception as exc:
            _record_cost("publish", "POST /2/tweets", ok=False, error=str(exc)[:300])
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": str(exc)[:300]}

    def fetch_post_insights(self, network_post_id: str) -> dict[str, Any]:
        """Fetch public metrics for a tweet. Costs $0.005."""
        creds = _load_x_creds()
        if not self.is_connected():
            return {"views": 0, "likes": 0, "replies": 0, "reposts": 0, "quotes": 0,
                    "error": "not_configured", "ts": _now_iso()}
        try:
            client = _get_client(creds)
            resp = client.get_tweet(
                int(network_post_id),
                tweet_fields=["public_metrics"],
            )
            _record_cost("insights", "GET /2/tweets/{id}", ok=True)
            metrics = (resp.data and resp.data.get("public_metrics")) or {}
            return {
                "views": int(metrics.get("impression_count") or 0),
                "likes": int(metrics.get("like_count") or 0),
                "replies": int(metrics.get("reply_count") or 0),
                "reposts": int(metrics.get("retweet_count") or 0),
                "quotes": int(metrics.get("quote_count") or 0),
                "error": None,
                "ts": _now_iso(),
            }
        except Exception as exc:
            _record_cost("insights", "GET /2/tweets/{id}", ok=False, error=str(exc)[:300])
            return {"views": 0, "likes": 0, "replies": 0, "reposts": 0, "quotes": 0,
                    "error": str(exc)[:300], "ts": _now_iso()}

    def fetch_followers(self) -> dict[str, Any]:
        """Get current follower count via GET /2/users/me?user_fields=public_metrics. $0.005."""
        creds = _load_x_creds()
        if not self.is_connected():
            return {"count": None, "error": "not_configured"}
        try:
            client = _get_client(creds)
            resp = client.get_me(user_fields=["public_metrics"])
            _record_cost("followers", "GET /2/users/me", ok=True)
            metrics = (resp.data and resp.data.get("public_metrics")) or {}
            return {"count": int(metrics.get("followers_count") or 0), "error": None}
        except Exception as exc:
            _record_cost("followers", "GET /2/users/me", ok=False, error=str(exc)[:300])
            return {"count": None, "error": str(exc)[:300]}


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
                user_auth=True,
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

    def cost_estimate(self, action: str) -> float:
        if action == "publish":
            return self.COST_PER_WRITE_USD
        if action in ("read", "insights", "followers"):
            return self.COST_PER_READ_USD
        return 0.0
