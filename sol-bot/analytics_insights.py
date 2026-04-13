#!/usr/bin/env python3
"""
Analytics & Insights System for @napoleotics X/Twitter Bot
Collects tweet data, analyzes performance, and sends reports via Telegram.

Usage:
    python3 analytics_insights.py scan    — Fetch and store tweets
    python3 analytics_insights.py report  — Generate and send weekly report
    python3 analytics_insights.py daily   — Short daily summary to Telegram
    python3 analytics_insights.py stats   — Print stats to stdout
"""

import os
import sys
import json
import sqlite3
import time
import re
import ssl
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path("/root/x-bot")
DB_PATH = BASE_DIR / "analytics.db"
ENV_PATH = BASE_DIR / ".env"
LOG_DIR = BASE_DIR / "logs"

BEARER = f"Bearer {os.environ.get('X_BEARER_TOKEN', '')}"
SCREEN_NAME = "napoleotics"

TOPIC_KEYWORDS = {
    "crypto": [
        "bitcoin", "btc", "crypto", "ethereum", "eth", "defi", "nft",
        "token", "blockchain", "stablecoin", "binance", "coinbase",
    ],
    "geopolitics": [
        "iran", "israel", "russia", "ukraine", "china", "trump", "biden",
        "war", "nato", "brics", "sanctions", "missile", "nuclear", "gaza",
        "hezbollah", "military", "invasion", "conflict",
    ],
    "finance": [
        "fed", "inflation", "market", "oil", "gold", "dollar", "economy",
        "gdp", "interest rate", "stock", "bonds", "tariff", "opec", "recession",
    ],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_env():
    """Load .env file into os.environ (no external deps)."""
    if not ENV_PATH.exists():
        return
    with open(ENV_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


def get_env(key, default=None):
    return os.environ.get(key, default)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def ssl_ctx():
    return ssl.create_default_context()


def api_request(url, headers=None, method="GET", retries=2):
    """Make an HTTPS request with retries and rate-limit awareness."""
    ctx = ssl_ctx()
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                data = resp.read().decode("utf-8", errors="replace")
                return json.loads(data) if data else {}
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            if e.code == 429:
                wait = int(e.headers.get("retry-after", 60))
                log(f"Rate limited. Waiting {wait}s...")
                time.sleep(wait)
                continue
            if e.code in (401, 403):
                log(f"Auth error {e.code}: {body}")
                return None
            log(f"HTTP {e.code} on attempt {attempt+1}: {body}")
            if attempt < retries:
                time.sleep(5 * (attempt + 1))
        except Exception as exc:
            log(f"Request error on attempt {attempt+1}: {exc}")
            if attempt < retries:
                time.sleep(5 * (attempt + 1))
    return None


def get_user_id_from_twid():
    """Extract numeric user ID from X_TWID cookie (format: u%3D1234567890)."""
    twid = get_env("X_TWID", "")
    if not twid:
        return None
    # Decode URL encoding: u%3D -> u=
    decoded = urllib.parse.unquote(twid)
    # Extract number after 'u='
    match = re.search(r"u=(\d+)", decoded)
    return match.group(1) if match else None


def x_headers():
    """Build headers for X API requests using cookie auth."""
    auth_token = get_env("X_AUTH_TOKEN", "")
    ct0 = get_env("X_CT0", "")
    twid = get_env("X_TWID", "")
    if not auth_token or not ct0:
        log("WARNING: X_AUTH_TOKEN or X_CT0 not set in .env — cookies may be expired")
    cookie = f"auth_token={auth_token}; ct0={ct0}; twid={twid}"
    return {
        "Authorization": BEARER,
        "Cookie": cookie,
        "X-Csrf-Token": ct0,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://x.com/{SCREEN_NAME}",
        "X-Twitter-Active-User": "yes",
        "X-Twitter-Client-Language": "en",
    }


def send_telegram(text):
    """Send a message to Telegram."""
    bot_token = get_env("TELEGRAM_BOT_TOKEN", "")
    chat_id = get_env("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        log("WARNING: Telegram credentials missing, printing to stdout instead")
        print(text)
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=ssl_ctx(), timeout=15) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                log("Telegram message sent successfully")
                return True
            else:
                log(f"Telegram error: {result}")
                return False
    except Exception as e:
        log(f"Telegram send failed: {e}")
        # For long messages, try splitting
        if len(text) > 4096:
            return send_telegram_chunked(text)
        return False


def send_telegram_chunked(text):
    """Send long messages in chunks."""
    chunks = []
    while text:
        if len(text) <= 4096:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, 4096)
        if split_at == -1:
            split_at = 4096
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    for chunk in chunks:
        send_telegram(chunk)
        time.sleep(1)
    return True


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db():
    """Create tables if they don't exist."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tweets (
            tweet_id TEXT PRIMARY KEY,
            text TEXT,
            created_at TEXT,
            likes INTEGER DEFAULT 0,
            retweets INTEGER DEFAULT 0,
            replies INTEGER DEFAULT 0,
            views INTEGER DEFAULT 0,
            media_type TEXT DEFAULT 'text',
            topic TEXT DEFAULT 'other',
            tweet_length INTEGER DEFAULT 0,
            is_thread INTEGER DEFAULT 0,
            first_seen TEXT,
            last_updated TEXT
        );
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet_id TEXT,
            timestamp TEXT,
            likes INTEGER DEFAULT 0,
            retweets INTEGER DEFAULT 0,
            replies INTEGER DEFAULT 0,
            views INTEGER DEFAULT 0,
            FOREIGN KEY (tweet_id) REFERENCES tweets(tweet_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tweets_created ON tweets(created_at);
        CREATE INDEX IF NOT EXISTS idx_snapshots_tweet ON snapshots(tweet_id);
        CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(timestamp);
    """)
    conn.close()
    migrate_db()
    log("Database initialized")


def migrate_db():
    """Add new analytics columns to existing tweets table (idempotent)."""
    conn = sqlite3.connect(str(DB_PATH))
    new_columns = [
        ("tweet_type",      "TEXT"),
        ("source_channel",  "TEXT"),
        ("hour_of_day",     "INTEGER"),
        ("engagement_rate", "REAL"),
    ]
    for col, col_type in new_columns:
        try:
            conn.execute(f"ALTER TABLE tweets ADD COLUMN {col} {col_type} DEFAULT NULL")
            log(f"[migrate_db] Added column: {col}")
        except sqlite3.OperationalError:
            pass  # column already exists

    # Backfill derived columns for existing rows
    conn.execute("""
        UPDATE tweets SET hour_of_day = CAST(strftime('%H', created_at) AS INTEGER)
        WHERE hour_of_day IS NULL AND created_at IS NOT NULL
    """)
    conn.execute("""
        UPDATE tweets SET
            engagement_rate = ROUND(CAST(likes + retweets + replies AS REAL) / NULLIF(views, 0) * 100, 2)
        WHERE engagement_rate IS NULL AND views > 0
    """)

    # Sync tweet_type from publish_log.json by tweet_id
    publish_log = Path("/root/x-bot/logs/publish_log.json")
    if publish_log.exists():
        try:
            entries = json.loads(publish_log.read_text())
            if isinstance(entries, list):
                synced = 0
                for entry in entries:
                    tid = entry.get("tweet_id")
                    ttype = entry.get("tweet_type")
                    if tid and ttype:
                        conn.execute(
                            "UPDATE tweets SET tweet_type = ? WHERE tweet_id = ? AND tweet_type IS NULL",
                            (ttype, tid)
                        )
                        synced += conn.execute("SELECT changes()").fetchone()[0]
                if synced:
                    log(f"[migrate_db] Synced tweet_type for {synced} rows from publish_log")
        except Exception as e:
            log(f"[migrate_db] publish_log sync error: {e}")

    conn.commit()
    conn.close()


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Topic & Media Classification
# ---------------------------------------------------------------------------

def classify_topic(text):
    """Classify tweet text into a topic by keyword matching."""
    lower = text.lower()
    scores = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in lower)
        if score > 0:
            scores[topic] = score
    if not scores:
        return "other"
    return max(scores, key=scores.get)


def detect_media_type(tweet_data):
    """Detect media type from tweet JSON (v1.1 format)."""
    entities = tweet_data.get("entities", {})
    extended = tweet_data.get("extended_entities", {})
    media_list = extended.get("media", entities.get("media", []))
    if not media_list:
        return "text"
    mtype = media_list[0].get("type", "photo")
    if mtype == "video" or mtype == "animated_gif":
        return "video"
    elif mtype == "photo":
        return "image"
    return "text"


def is_self_reply(tweet_data):
    """Check if tweet is a reply to self (thread)."""
    reply_to = tweet_data.get("in_reply_to_screen_name", "")
    if reply_to and reply_to.lower() == SCREEN_NAME.lower():
        return True
    return False


# ---------------------------------------------------------------------------
# Tweet Fetching
# ---------------------------------------------------------------------------

def fetch_tweets_v1(count=200, max_id=None):
    """Fetch tweets via v1.1 user_timeline endpoint."""
    params = urllib.parse.urlencode({
        "screen_name": SCREEN_NAME,
        "count": count,
        "tweet_mode": "extended",
        "include_entities": "true",
        "include_rts": "false",
    })
    if max_id:
        params += f"&max_id={max_id}"
    url = f"https://api.x.com/1.1/statuses/user_timeline.json?{params}"
    headers = x_headers()
    log(f"v1.1 request: {url[:100]}...")
    result = api_request(url, headers=headers, retries=1)
    if result is None:
        log("v1.1 returned None (error)")
    elif isinstance(result, list):
        log(f"v1.1 returned list of {len(result)} items")
    else:
        log(f"v1.1 returned unexpected type: {type(result)}")
    return result


def fetch_user_id_rest(headers):
    """Try to get user ID from REST API."""
    url = f"https://api.x.com/1.1/users/show.json?screen_name={SCREEN_NAME}"
    data = api_request(url, headers=headers)
    if data and "id_str" in data:
        return data["id_str"]
    return None


def fetch_tweets_graphql():
    """Fallback: fetch tweets via GraphQL UserTweets."""
    headers = x_headers()

    # Try to get user ID: first from TWID cookie, then REST API
    user_id = get_user_id_from_twid()
    if not user_id:
        log("No user ID from TWID cookie, trying REST lookup...")
        user_id = fetch_user_id_rest(headers)
    if not user_id:
        log("Could not get user ID for GraphQL fallback")
        return None

    log(f"Using user ID {user_id} for GraphQL query...")

    variables = {
        "userId": user_id,
        "count": 100,
        "includePromotedContent": False,
        "withQuickPromoteEligibilityTweetFields": False,
        "withVoice": False,
        "withV2Timeline": True,
    }
    features = {
        "profile_label_improvements_pcf_label_in_post_enabled": False,
        "rweb_tipjar_consumption_enabled": True,
        "responsive_web_graphql_exclude_directive_enabled": True,
        "verified_phone_label_enabled": False,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_timeline_navigation_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "premium_content_api_read_enabled": False,
        "communities_web_enable_tweet_community_results_fetch": True,
        "c9s_tweet_anatomy_moderator_badge_enabled": True,
        "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
        "articles_preview_enabled": True,
        "responsive_web_edit_tweet_api_enabled": True,
        "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
        "view_counts_everywhere_api_enabled": True,
        "longform_notetweets_consumption_enabled": True,
        "responsive_web_twitter_article_tweet_consumption_enabled": True,
        "tweet_awards_web_tipping_enabled": False,
        "creator_subscriptions_quote_tweet_preview_enabled": False,
        "freedom_of_speech_not_reach_fetch_enabled": True,
        "standardized_nudges_misinfo": True,
        "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
        "rweb_video_timestamps_enabled": True,
        "longform_notetweets_rich_text_read_enabled": True,
        "longform_notetweets_inline_media_enabled": True,
        "responsive_web_enhance_cards_enabled": False,
    }

    params = urllib.parse.urlencode({"variables": json.dumps(variables), "features": json.dumps(features)})
    url = f"https://api.x.com/graphql/V7H0Ap3_Hh2FyS75OCDO3Q/UserTweets?{params}"

    gql_headers = dict(headers)
    gql_headers["Content-Type"] = "application/json"
    result = api_request(url, headers=gql_headers)
    return parse_graphql_tweets(result) if result else None


def parse_graphql_tweets(data):
    """Parse GraphQL UserTweets response into v1.1-like format."""
    tweets = []
    try:
        instructions = (
            data.get("data", {})
            .get("user", {})
            .get("result", {})
            .get("timeline_v2", {})
            .get("timeline", {})
            .get("instructions", [])
        )
        for inst in instructions:
            if inst.get("type") == "TimelineAddEntries":
                entries = inst.get("entries", [])
            else:
                entries = inst.get("entries", [])
            for entry in entries:
                content = entry.get("content", {})
                item = content.get("itemContent", {})
                if not item:
                    # Could be in items array (for conversations)
                    items = content.get("items", [])
                    for sub in items:
                        item = sub.get("item", {}).get("itemContent", {})
                        tweet = extract_gql_tweet(item)
                        if tweet:
                            tweets.append(tweet)
                    continue
                tweet = extract_gql_tweet(item)
                if tweet:
                    tweets.append(tweet)
    except Exception as e:
        log(f"Error parsing GraphQL response: {e}")
    return tweets


def extract_gql_tweet(item_content):
    """Extract a tweet dict from GraphQL itemContent."""
    try:
        result = item_content.get("tweet_results", {}).get("result", {})
        if result.get("__typename") == "TweetWithVisibilityResults":
            result = result.get("tweet", {})
        legacy = result.get("legacy", {})
        if not legacy:
            return None

        # Skip retweets
        text = legacy.get("full_text", legacy.get("text", ""))
        if text.startswith("RT @"):
            return None

        views_data = result.get("views", {})
        view_count = 0
        if views_data and views_data.get("count"):
            try:
                view_count = int(views_data["count"])
            except (ValueError, TypeError):
                pass

        tweet = {
            "id_str": legacy.get("id_str", result.get("rest_id", "")),
            "full_text": text,
            "created_at": legacy.get("created_at", ""),
            "favorite_count": legacy.get("favorite_count", 0),
            "retweet_count": legacy.get("retweet_count", 0),
            "reply_count": legacy.get("reply_count", 0),
            "view_count": view_count,
            "entities": legacy.get("entities", {}),
            "extended_entities": legacy.get("extended_entities", {}),
            "in_reply_to_screen_name": legacy.get("in_reply_to_screen_name"),
        }
        return tweet
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Scan / Collect
# ---------------------------------------------------------------------------

def scan_tweets():
    """Fetch tweets and store/update in database."""
    log("Starting tweet scan...")
    init_db()

    all_tweets = []

    # Try v1.1 first
    log("Trying v1.1 API...")
    v1_tweets = fetch_tweets_v1(count=200)
    if v1_tweets and isinstance(v1_tweets, list) and len(v1_tweets) > 0:
        log(f"v1.1 returned {len(v1_tweets)} tweets on first page")
        all_tweets.extend(v1_tweets)
        # Paginate for more
        max_id = str(int(v1_tweets[-1]["id_str"]) - 1)
        for page in range(2, 6):
            log(f"Fetching page {page} via v1.1...")
            more = fetch_tweets_v1(count=200, max_id=max_id)
            if not more or not isinstance(more, list) or len(more) == 0:
                break
            all_tweets.extend(more)
            max_id = str(int(more[-1]["id_str"]) - 1)
            time.sleep(2)
            if len(more) < 200:
                break
    else:
        log("v1.1 failed or returned no tweets, trying GraphQL fallback...")
        gql_tweets = fetch_tweets_graphql()
        if gql_tweets:
            log(f"GraphQL returned {len(gql_tweets)} tweets")
            all_tweets.extend(gql_tweets)
        else:
            log("GraphQL also returned no tweets")

    if not all_tweets:
        log("No tweets fetched")
        return 0

    log(f"Fetched {len(all_tweets)} tweets, processing...")
    conn = get_db()
    now = datetime.utcnow().isoformat()
    new_count = 0
    updated_count = 0

    for t in all_tweets:
        tid = t.get("id_str", "")
        if not tid:
            continue

        text = t.get("full_text", t.get("text", ""))
        created = t.get("created_at", "")
        # Parse Twitter date format
        try:
            dt = datetime.strptime(created, "%a %b %d %H:%M:%S %z %Y")
            created_iso = dt.isoformat()
        except Exception:
            created_iso = created

        likes = t.get("favorite_count", 0)
        rts = t.get("retweet_count", 0)
        replies = t.get("reply_count", 0)
        views = t.get("view_count", 0)
        # v1.1 doesn't always have view_count at top level
        if views == 0:
            # Check ext_views or public_metrics
            views = t.get("ext_views", {}).get("count", 0) if isinstance(t.get("ext_views"), dict) else 0

        media = detect_media_type(t)
        topic = classify_topic(text)
        length = len(text)
        thread = 1 if is_self_reply(t) else 0

        hour = None
        try:
            hour = int(datetime.fromisoformat(created_iso).strftime("%H"))
        except Exception:
            pass
        eng_rate = round((likes + rts + replies) * 100.0 / views, 2) if views > 0 else None

        existing = conn.execute("SELECT tweet_id FROM tweets WHERE tweet_id = ?", (tid,)).fetchone()
        if existing:
            conn.execute("""
                UPDATE tweets SET likes=?, retweets=?, replies=?, views=?,
                    media_type=?, topic=?, last_updated=?,
                    hour_of_day=COALESCE(hour_of_day, ?),
                    engagement_rate=?
                WHERE tweet_id=?
            """, (likes, rts, replies, views, media, topic, now, hour, eng_rate, tid))
            updated_count += 1
        else:
            conn.execute("""
                INSERT INTO tweets (tweet_id, text, created_at, likes, retweets, replies, views,
                    media_type, topic, tweet_length, is_thread, first_seen, last_updated,
                    hour_of_day, engagement_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (tid, text, created_iso, likes, rts, replies, views, media, topic, length, thread, now, now,
                  hour, eng_rate))
            new_count += 1

        # Add snapshot
        conn.execute("""
            INSERT INTO snapshots (tweet_id, timestamp, likes, retweets, replies, views)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (tid, now, likes, rts, replies, views))

    conn.commit()
    conn.close()
    log(f"Scan complete: {new_count} new, {updated_count} updated")
    return new_count + updated_count


# ---------------------------------------------------------------------------
# Analysis Helpers
# ---------------------------------------------------------------------------

def engagement_rate(likes, retweets, replies, views):
    return (likes + retweets + replies) / max(views, 1) * 100


def get_best_hours(conn, days=30):
    """Get average engagement by posting hour."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT created_at, likes, retweets, replies, views
        FROM tweets WHERE created_at >= ? AND views > 0
    """, (cutoff,)).fetchall()

    hours = {}
    for r in rows:
        try:
            dt = datetime.fromisoformat(r["created_at"].replace("+00:00", "+00:00").split("+")[0])
            h = dt.hour
        except Exception:
            continue
        eng = engagement_rate(r["likes"], r["retweets"], r["replies"], r["views"])
        hours.setdefault(h, []).append(eng)

    result = {}
    for h, rates in hours.items():
        result[h] = sum(rates) / len(rates)
    return dict(sorted(result.items(), key=lambda x: -x[1]))


def get_best_content_type(conn, days=30):
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT media_type,
            AVG(CAST(likes + retweets + replies AS FLOAT) / MAX(views, 1) * 100) as avg_eng,
            COUNT(*) as cnt
        FROM tweets WHERE created_at >= ? AND views > 0
        GROUP BY media_type ORDER BY avg_eng DESC
    """, (cutoff,)).fetchall()
    return [(r["media_type"], round(r["avg_eng"], 2), r["cnt"]) for r in rows]


def get_best_topics(conn, days=30):
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT topic,
            AVG(CAST(likes + retweets + replies AS FLOAT) / MAX(views, 1) * 100) as avg_eng,
            COUNT(*) as cnt
        FROM tweets WHERE created_at >= ? AND views > 0
        GROUP BY topic ORDER BY avg_eng DESC
    """, (cutoff,)).fetchall()
    return [(r["topic"], round(r["avg_eng"], 2), r["cnt"]) for r in rows]


def get_length_analysis(conn, days=30):
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    categories = {
        "Corto (<100)": (0, 100),
        "Medio (100-200)": (100, 200),
        "Largo (>200)": (200, 99999),
    }
    results = {}
    for label, (lo, hi) in categories.items():
        row = conn.execute("""
            SELECT AVG(CAST(likes + retweets + replies AS FLOAT) / MAX(views, 1) * 100) as avg_eng,
                COUNT(*) as cnt
            FROM tweets WHERE created_at >= ? AND views > 0 AND tweet_length >= ? AND tweet_length < ?
        """, (cutoff, lo, hi)).fetchone()
        results[label] = (round(row["avg_eng"] or 0, 2), row["cnt"] or 0)
    return results


def get_top_tweets(conn, n=10):
    rows = conn.execute("""
        SELECT tweet_id, text, likes, retweets, replies, views,
            CAST(likes + retweets + replies AS FLOAT) / MAX(views, 1) * 100 as eng_rate
        FROM tweets WHERE views > 0
        ORDER BY eng_rate DESC LIMIT ?
    """, (n,)).fetchall()
    return rows


def get_weekly_comparison(conn):
    """Compare this week vs last week."""
    now = datetime.utcnow()
    # This week: Monday to now
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    last_week_start = week_start - timedelta(days=7)

    this_week = conn.execute("""
        SELECT COUNT(*) as cnt, SUM(likes) as likes, SUM(retweets) as rts,
            SUM(views) as views, SUM(replies) as replies
        FROM tweets WHERE created_at >= ?
    """, (week_start.isoformat(),)).fetchone()

    last_week = conn.execute("""
        SELECT COUNT(*) as cnt, SUM(likes) as likes, SUM(retweets) as rts,
            SUM(views) as views, SUM(replies) as replies
        FROM tweets WHERE created_at >= ? AND created_at < ?
    """, (last_week_start.isoformat(), week_start.isoformat())).fetchone()

    return {
        "this_week": {
            "tweets": this_week["cnt"] or 0,
            "likes": this_week["likes"] or 0,
            "retweets": this_week["rts"] or 0,
            "views": this_week["views"] or 0,
            "replies": this_week["replies"] or 0,
        },
        "last_week": {
            "tweets": last_week["cnt"] or 0,
            "likes": last_week["likes"] or 0,
            "retweets": last_week["rts"] or 0,
            "views": last_week["views"] or 0,
            "replies": last_week["replies"] or 0,
        },
    }


def pct_change(current, previous):
    if previous == 0:
        return "+100%" if current > 0 else "0%"
    change = ((current - previous) / previous) * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.0f}%"


# ---------------------------------------------------------------------------
# Recommendations Engine
# ---------------------------------------------------------------------------

def generate_recommendations(conn):
    """Generate 2-3 actionable recommendations in Spanish."""
    recs = []

    # Best topic + media combo
    rows = conn.execute("""
        SELECT topic, media_type,
            AVG(CAST(likes + retweets + replies AS FLOAT) / MAX(views, 1) * 100) as avg_eng,
            COUNT(*) as cnt
        FROM tweets WHERE views > 0
        GROUP BY topic, media_type
        HAVING cnt >= 2
        ORDER BY avg_eng DESC
    """).fetchall()

    if len(rows) >= 2:
        best = rows[0]
        worst = rows[-1]
        if worst["avg_eng"] > 0:
            ratio = best["avg_eng"] / worst["avg_eng"]
            topic_es = {"crypto": "crypto", "geopolitics": "geopolitica", "finance": "finanzas", "other": "otros"}.get(best["topic"], best["topic"])
            media_es = {"text": "texto", "image": "imagen", "video": "video"}.get(best["media_type"], best["media_type"])
            worst_topic_es = {"crypto": "crypto", "geopolitics": "geopolitica", "finance": "finanzas", "other": "otros"}.get(worst["topic"], worst["topic"])
            worst_media_es = {"text": "texto", "image": "imagen", "video": "video"}.get(worst["media_type"], worst["media_type"])
            recs.append(
                f"Tus tweets de {topic_es} con {media_es} tienen {ratio:.1f}x mas engagement "
                f"que {worst_topic_es} con {worst_media_es}. Publica mas de esos."
            )

    # Best hour
    hours = get_best_hours(conn)
    if hours:
        best_h = list(hours.keys())[0]
        best_eng = list(hours.values())[0]
        recs.append(
            f"Tu mejor horario es {best_h:02d}:00 ({best_eng:.1f}% eng). "
            f"Considera programar mas publicaciones a esa hora."
        )

    # Threads vs singles
    thread_row = conn.execute("""
        SELECT is_thread,
            AVG(views) as avg_views,
            AVG(CAST(likes + retweets + replies AS FLOAT) / MAX(views, 1) * 100) as avg_eng,
            COUNT(*) as cnt
        FROM tweets WHERE views > 0
        GROUP BY is_thread HAVING cnt >= 2
    """).fetchall()

    thread_data = {r["is_thread"]: r for r in thread_row}
    if 0 in thread_data and 1 in thread_data:
        t_views = thread_data[1]["avg_views"]
        s_views = thread_data[0]["avg_views"]
        if s_views > 0 and t_views > s_views:
            ratio = t_views / s_views
            recs.append(
                f"Los hilos generan {ratio:.1f}x mas views que tweets individuales. Usa mas hilos."
            )
    elif 1 not in thread_data:
        recs.append("No has publicado hilos recientemente. Los hilos suelen generar mas engagement, prueba usarlos.")

    # Worst hour
    if len(hours) >= 3:
        worst_h = list(hours.keys())[-1]
        worst_eng = list(hours.values())[-1]
        recs.append(
            f"Evita publicar a las {worst_h:02d}:00 ({worst_eng:.1f}% eng), es tu horario con menor engagement."
        )

    return recs[:3]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def build_weekly_report():
    """Build the full weekly report string."""
    conn = get_db()
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    comparison = get_weekly_comparison(conn)
    tw = comparison["this_week"]
    lw = comparison["last_week"]

    # Avg engagement this week
    avg_eng_row = conn.execute("""
        SELECT AVG(CAST(likes + retweets + replies AS FLOAT) / MAX(views, 1) * 100) as avg_eng
        FROM tweets WHERE created_at >= ? AND views > 0
    """, (week_ago.isoformat(),)).fetchone()
    avg_eng = round(avg_eng_row["avg_eng"] or 0, 2)

    hours = get_best_hours(conn)
    content_types = get_best_content_type(conn)
    topics = get_best_topics(conn)
    lengths = get_length_analysis(conn)
    top_tweets = get_top_tweets(conn, 5)
    recs = generate_recommendations(conn)

    date_from = week_ago.strftime("%d/%m/%Y")
    date_to = now.strftime("%d/%m/%Y")

    lines = []
    lines.append(f"\U0001f4ca REPORTE SEMANAL \u2014 @napoleotics")
    lines.append(f"Periodo: {date_from} - {date_to}")
    lines.append("")

    lines.append("\U0001f4c8 RESUMEN")
    lines.append(f"Tweets publicados: {tw['tweets']} (prev: {lw['tweets']}, {pct_change(tw['tweets'], lw['tweets'])})")
    lines.append(f"Total likes: {tw['likes']} (prev: {lw['likes']}, {pct_change(tw['likes'], lw['likes'])})")
    lines.append(f"Total retweets: {tw['retweets']} (prev: {lw['retweets']}, {pct_change(tw['retweets'], lw['retweets'])})")
    lines.append(f"Total views: {tw['views']} (prev: {lw['views']}, {pct_change(tw['views'], lw['views'])})")
    lines.append(f"Engagement rate promedio: {avg_eng}%")
    lines.append("")

    lines.append("\U0001f550 MEJORES HORARIOS")
    for i, (h, eng) in enumerate(list(hours.items())[:3], 1):
        lines.append(f"{i}. {h:02d}:00 \u2014 {eng:.1f}% engagement")
    lines.append("")

    type_icons = {"video": "\U0001f3c6 Video", "image": "\U0001f4f7 Imagen", "text": "\U0001f4dd Texto"}
    lines.append("\U0001f4ce MEJOR TIPO DE CONTENIDO")
    for mtype, eng, cnt in content_types:
        icon = type_icons.get(mtype, mtype)
        lines.append(f"{icon} \u2014 {eng}% engagement ({cnt} tweets)")
    lines.append("")

    topic_icons = {"geopolitics": "\U0001f30d Geopolitica", "finance": "\U0001f4b0 Finanzas", "crypto": "\u20bf Crypto", "other": "\U0001f4cc Otros"}
    lines.append("\U0001f30d MEJORES TEMAS")
    for topic, eng, cnt in topics:
        icon = topic_icons.get(topic, topic)
        lines.append(f"{icon} \u2014 {eng}% engagement ({cnt} tweets)")
    lines.append("")

    lines.append("\U0001f4cf LARGO OPTIMO")
    best_len = max(lengths.items(), key=lambda x: x[1][0]) if lengths else None
    for label, (eng, cnt) in lengths.items():
        marker = " \u2190 mejor" if best_len and label == best_len[0] and eng > 0 else ""
        lines.append(f"{label}: {eng}% ({cnt} tweets){marker}")
    lines.append("")

    lines.append("\U0001f525 TOP 5 TWEETS")
    for i, t in enumerate(top_tweets[:5], 1):
        short_text = t["text"][:50].replace("\n", " ") + "..." if len(t["text"]) > 50 else t["text"].replace("\n", " ")
        eng = engagement_rate(t["likes"], t["retweets"], t["replies"], t["views"])
        lines.append(f'{i}. "{short_text}" \u2014 \u2764\ufe0f {t["likes"]} \U0001f501 {t["retweets"]} \U0001f441 {t["views"]} ({eng:.1f}% eng)')
    lines.append("")

    lines.append("\U0001f4a1 RECOMENDACIONES")
    for rec in recs:
        lines.append(f"\u2022 {rec}")

    conn.close()
    return "\n".join(lines)


def build_daily_summary():
    """Short daily summary."""
    conn = get_db()
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Today's stats
    row = conn.execute("""
        SELECT COUNT(*) as cnt, SUM(likes) as likes, SUM(retweets) as rts,
            SUM(views) as views, SUM(replies) as replies
        FROM tweets WHERE created_at >= ?
    """, (today.isoformat(),)).fetchone()

    # Top tweet today
    top = conn.execute("""
        SELECT text, likes, retweets, replies, views
        FROM tweets WHERE created_at >= ? AND views > 0
        ORDER BY CAST(likes + retweets + replies AS FLOAT) / MAX(views, 1) DESC
        LIMIT 1
    """, (today.isoformat(),)).fetchone()

    # Overall stats
    total = conn.execute("SELECT COUNT(*) as cnt FROM tweets").fetchone()

    lines = []
    lines.append(f"\U0001f4ca RESUMEN DIARIO \u2014 @napoleotics")
    lines.append(f"Fecha: {today.strftime('%d/%m/%Y')}")
    lines.append("")
    lines.append(f"Tweets hoy: {row['cnt'] or 0}")
    lines.append(f"Likes: {row['likes'] or 0} | Retweets: {row['rts'] or 0} | Views: {row['views'] or 0}")

    if top:
        short_text = top["text"][:60].replace("\n", " ") + "..." if len(top["text"]) > 60 else top["text"].replace("\n", " ")
        eng = engagement_rate(top["likes"], top["retweets"], top["replies"], top["views"])
        lines.append("")
        lines.append(f"\U0001f525 Mejor tweet: \"{short_text}\"")
        lines.append(f"\u2764\ufe0f {top['likes']} | \U0001f501 {top['retweets']} | \U0001f441 {top['views']} | {eng:.1f}% eng")

    lines.append("")
    lines.append(f"Total tweets en DB: {total['cnt']}")

    conn.close()
    return "\n".join(lines)


def print_stats():
    """Print all stats to stdout without sending to Telegram."""
    init_db()
    conn = get_db()

    total = conn.execute("SELECT COUNT(*) as cnt FROM tweets").fetchone()["cnt"]
    if total == 0:
        print("No tweets in database. Run 'scan' first.")
        return

    print(f"\n{'='*60}")
    print(f"  ANALYTICS STATS — @napoleotics ({total} tweets in DB)")
    print(f"{'='*60}\n")

    # Best hours
    hours = get_best_hours(conn)
    print("BEST HOURS (by avg engagement %):")
    for h, eng in list(hours.items())[:5]:
        print(f"  {h:02d}:00 — {eng:.2f}%")

    # Content types
    print("\nBEST CONTENT TYPE:")
    for mtype, eng, cnt in get_best_content_type(conn):
        print(f"  {mtype:10s} — {eng:.2f}% ({cnt} tweets)")

    # Topics
    print("\nBEST TOPICS:")
    for topic, eng, cnt in get_best_topics(conn):
        print(f"  {topic:15s} — {eng:.2f}% ({cnt} tweets)")

    # Length
    print("\nOPTIMAL LENGTH:")
    lengths = get_length_analysis(conn)
    for label, (eng, cnt) in lengths.items():
        print(f"  {label:20s} — {eng:.2f}% ({cnt} tweets)")

    # Top tweets
    print("\nTOP 10 TWEETS (by engagement rate):")
    for i, t in enumerate(get_top_tweets(conn, 10), 1):
        short = t["text"][:60].replace("\n", " ")
        eng = engagement_rate(t["likes"], t["retweets"], t["replies"], t["views"])
        print(f"  {i:2d}. [{eng:.2f}%] {short}...")

    # Weekly comparison
    comp = get_weekly_comparison(conn)
    tw, lw = comp["this_week"], comp["last_week"]
    print(f"\nWEEK OVER WEEK:")
    print(f"  Tweets:   {tw['tweets']:>6d} (prev: {lw['tweets']}, {pct_change(tw['tweets'], lw['tweets'])})")
    print(f"  Likes:    {tw['likes']:>6d} (prev: {lw['likes']}, {pct_change(tw['likes'], lw['likes'])})")
    print(f"  Retweets: {tw['retweets']:>6d} (prev: {lw['retweets']}, {pct_change(tw['retweets'], lw['retweets'])})")
    print(f"  Views:    {tw['views']:>6d} (prev: {lw['views']}, {pct_change(tw['views'], lw['views'])})")

    # Recommendations
    print("\nRECOMMENDATIONS:")
    for rec in generate_recommendations(conn):
        print(f"  * {rec}")

    print(f"\n{'='*60}\n")
    conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    load_env()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "scan":
        count = scan_tweets()
        log(f"Scan finished. Processed {count} tweets.")

    elif cmd == "report":
        init_db()
        report = build_weekly_report()
        send_telegram(report)
        print(report)

    elif cmd == "daily":
        init_db()
        summary = build_daily_summary()
        send_telegram(summary)
        print(summary)

    elif cmd == "stats":
        print_stats()

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
