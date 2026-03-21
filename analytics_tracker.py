#!/usr/bin/env python3
"""
X/Twitter Analytics Tracker for @napoleotics
Fetches tweet metrics and sends daily report to Telegram.

Cron setup (daily at 8PM CST):
  0 20 * * * cd /root/x-bot && /usr/bin/python3 analytics_tracker.py >> /root/x-bot/logs/analytics.log 2>&1

Requires: pip install python-dotenv
"""

import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error
import ssl
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = "/root/x-bot"
ENV_PATH = os.path.join(BASE_DIR, ".env")

BOT_TOKEN = "8603788822:AAHkhXtvyFBqYSA-hglE0aXr_0rAZhFaWxM"
CHAT_ID = "6054558214"
SCREEN_NAME = "napoleotics"

BEARER = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Ignore SSL verification issues on some VPS setups
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Env loading
# ---------------------------------------------------------------------------
def load_env(path):
    """Load .env file manually (fallback if dotenv unavailable)."""
    env = {}
    if not os.path.isfile(path):
        return env
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("'\"")
            env[key] = val
    return env


def get_cookies():
    """Return X cookie values from environment."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except ImportError:
        env = load_env(ENV_PATH)
        for k, v in env.items():
            os.environ.setdefault(k, v)

    auth_token = os.environ.get("X_AUTH_TOKEN", "")
    ct0 = os.environ.get("X_CT0", "")
    twid = os.environ.get("X_TWID", "")

    if not auth_token or not ct0:
        print("[ERROR] X_AUTH_TOKEN and X_CT0 must be set in .env")
        sys.exit(1)

    return auth_token, ct0, twid


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def make_request(url, headers, timeout=30):
    """Perform GET request, return parsed JSON or None."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        print(f"[HTTP {e.code}] {url[:80]}...\n{body}")
        return None
    except Exception as e:
        print(f"[ERROR] Request failed: {e}")
        return None


def build_headers(auth_token, ct0, twid):
    """Build headers dict for X API requests."""
    cookie = f"auth_token={auth_token}; ct0={ct0}"
    if twid:
        cookie += f"; twid={twid}"
    return {
        "Authorization": BEARER,
        "Cookie": cookie,
        "X-Csrf-Token": ct0,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://x.com/{SCREEN_NAME}",
    }


# ---------------------------------------------------------------------------
# Fetch tweets — primary: v1.1 API
# ---------------------------------------------------------------------------
def fetch_tweets_v1(headers, count=20):
    """Fetch tweets via v1.1 user_timeline endpoint."""
    params = urllib.parse.urlencode({
        "screen_name": SCREEN_NAME,
        "count": count,
        "tweet_mode": "extended",
        "include_entities": "false",
    })
    url = f"https://api.x.com/1.1/statuses/user_timeline.json?{params}"
    print(f"[v1.1] Fetching tweets from {SCREEN_NAME}...")
    data = make_request(url, headers)
    if not data or not isinstance(data, list):
        return None

    tweets = []
    for t in data:
        text = t.get("full_text", t.get("text", ""))
        # Skip RTs unless own
        if text.startswith("RT @") and not t.get("retweeted_status"):
            continue
        tweets.append({
            "id": t.get("id_str", ""),
            "text": text,
            "likes": t.get("favorite_count", 0),
            "retweets": t.get("retweet_count", 0),
            "replies": t.get("reply_count", 0),
            "views": 0,  # v1.1 doesn't always return views
            "created": t.get("created_at", ""),
        })
    return tweets


# ---------------------------------------------------------------------------
# Fetch tweets — fallback: GraphQL UserTweets
# ---------------------------------------------------------------------------
def fetch_user_id(headers):
    """Resolve screen_name to numeric user ID via v1.1 show endpoint."""
    url = f"https://api.x.com/1.1/users/show.json?screen_name={SCREEN_NAME}"
    data = make_request(url, headers)
    if data and "id_str" in data:
        return data["id_str"]
    return None


def fetch_tweets_graphql(headers):
    """Fetch tweets via GraphQL UserTweets endpoint."""
    user_id = fetch_user_id(headers)
    if not user_id:
        print("[GraphQL] Could not resolve user ID")
        return None

    variables = json.dumps({
        "userId": user_id,
        "count": 20,
        "includePromotedContent": False,
        "withQuickPromoteEligibilityTweetFields": False,
        "withVoice": False,
        "withV2Timeline": True,
    })
    features = json.dumps({
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
    })

    params = urllib.parse.urlencode({
        "variables": variables,
        "features": features,
    })
    url = f"https://api.x.com/graphql/V7H0Ap3_Hh2FyS75OCDO3Q/UserTweets?{params}"
    print(f"[GraphQL] Fetching tweets for user {user_id}...")

    gql_headers = dict(headers)
    gql_headers["Content-Type"] = "application/json"

    data = make_request(url, gql_headers)
    if not data:
        return None

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
        entries = []
        for instr in instructions:
            if instr.get("type") == "TimelineAddEntries":
                entries = instr.get("entries", [])
                break

        for entry in entries:
            content = entry.get("content", {})
            item = content.get("itemContent", {})
            if not item:
                # Could be a module with items
                items = content.get("items", [])
                for sub in items:
                    item = sub.get("item", {}).get("itemContent", {})
                    tweet = _extract_graphql_tweet(item)
                    if tweet:
                        tweets.append(tweet)
                continue
            tweet = _extract_graphql_tweet(item)
            if tweet:
                tweets.append(tweet)
    except Exception as e:
        print(f"[GraphQL] Parse error: {e}")
        return None

    return tweets if tweets else None


def _extract_graphql_tweet(item):
    """Extract tweet data from a GraphQL timeline item."""
    if item.get("tweet_display_type") not in ("Tweet", None):
        return None
    result = item.get("tweet_results", {}).get("result", {})
    if not result:
        return None
    # Handle TweetWithVisibilityResults wrapper
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet", {})

    legacy = result.get("legacy", {})
    if not legacy:
        return None

    text = legacy.get("full_text", "")
    if text.startswith("RT @"):
        return None

    views_info = result.get("views", {})
    views = int(views_info.get("count", 0)) if views_info.get("count") else 0

    return {
        "id": legacy.get("id_str", result.get("rest_id", "")),
        "text": text,
        "likes": legacy.get("favorite_count", 0),
        "retweets": legacy.get("retweet_count", 0),
        "replies": legacy.get("reply_count", 0),
        "views": views,
        "created": legacy.get("created_at", ""),
    }


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
def send_telegram(message):
    """Send message to Telegram via Bot API."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("ok"):
                print("[Telegram] Report sent successfully")
            else:
                print(f"[Telegram] API error: {result}")
    except Exception as e:
        print(f"[Telegram] Failed to send: {e}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def build_report(tweets):
    """Build the formatted daily report string."""
    cst = timezone(timedelta(hours=-6))
    now = datetime.now(cst)
    date_str = now.strftime("%Y-%m-%d %H:%M CST")

    lines = []
    lines.append(f"\U0001F4CA <b>REPORTE DIARIO — @{SCREEN_NAME}</b>")
    lines.append(f"Fecha: {date_str}")
    lines.append("")

    if not tweets:
        lines.append("No se encontraron tweets recientes.")
        return "\n".join(lines)

    total_likes = 0
    total_rts = 0
    total_views = 0
    best_tweet = None
    best_likes = -1

    for i, t in enumerate(tweets[:15], 1):
        short = t["text"][:50].replace("\n", " ").strip()
        if len(t["text"]) > 50:
            short += "..."
        likes = t["likes"]
        rts = t["retweets"]
        views = t["views"]
        replies = t["replies"]

        total_likes += likes
        total_rts += rts
        total_views += views

        if likes > best_likes:
            best_likes = likes
            best_tweet = t

        view_str = f"  \U0001F441 {views:,}" if views else ""
        lines.append(f"<b>Tweet {i}:</b> \"{short}\"")
        lines.append(
            f"\u2764\ufe0f {likes:,}  \U0001F501 {rts:,}{view_str}  \U0001F4AC {replies:,}"
        )
        lines.append("")

    count = min(len(tweets), 15)
    avg_likes = total_likes / count if count else 0

    lines.append(f"\U0001F4C8 <b>RESUMEN:</b>")
    lines.append(f"Total tweets: {count}")
    if best_tweet:
        best_short = best_tweet["text"][:40].replace("\n", " ").strip()
        if len(best_tweet["text"]) > 40:
            best_short += "..."
        lines.append(f"Mejor tweet: \"{best_short}\" ({best_likes:,} likes)")
    lines.append(f"Promedio likes: {avg_likes:.1f}")
    if total_views:
        lines.append(f"Total views: {total_views:,}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"=== Analytics Tracker — {datetime.utcnow().isoformat()}Z ===")

    auth_token, ct0, twid = get_cookies()
    headers = build_headers(auth_token, ct0, twid)

    # Try v1.1 first, then GraphQL fallback
    tweets = fetch_tweets_v1(headers)

    if not tweets:
        print("[v1.1] Failed or empty, trying GraphQL fallback...")
        tweets = fetch_tweets_graphql(headers)

    if not tweets:
        print("[WARN] No tweets retrieved from any source")
        error_msg = (
            f"\u26A0\ufe0f <b>Analytics Tracker</b>\n"
            f"No se pudieron obtener tweets de @{SCREEN_NAME}.\n"
            f"Verificar cookies en .env (pueden estar expiradas)."
        )
        send_telegram(error_msg)
        sys.exit(1)

    print(f"[OK] Retrieved {len(tweets)} tweets")
    report = build_report(tweets)

    # Print to stdout for CLI review
    print("\n" + report.replace("<b>", "").replace("</b>", "") + "\n")

    # Send to Telegram
    send_telegram(report)
    print("=== Done ===")


if __name__ == "__main__":
    main()
