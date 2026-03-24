#!/usr/bin/env python3
"""
X/Twitter Analytics Tracker for @napoleotics.
Fetches tweet metrics and sends a daily Telegram report.
"""

import json
import sys
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

from config import get_bool_env, load_environment
from http_utils import build_ssl_context, request_json
from telegram_client import send_message
from x_client import build_x_headers, get_x_cookies, has_required_x_cookies

load_environment()

SCREEN_NAME = "napoleotics"
ALLOW_INSECURE_SSL = get_bool_env("ALLOW_INSECURE_X_SSL", False)
SSL_CONTEXT = build_ssl_context(verify=not ALLOW_INSECURE_SSL)


def get_cookies():
    cookies = get_x_cookies()
    if not has_required_x_cookies(cookies):
        print("[ERROR] X_AUTH_TOKEN and X_CT0 must be set in .env")
        sys.exit(1)
    return cookies


def make_request(url, headers, timeout=30):
    try:
        return request_json(url, headers=headers, timeout=timeout, ssl_context=SSL_CONTEXT)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        print(f"[HTTP {exc.code}] {url[:80]}...\n{body}")
        return None
    except Exception as exc:
        print(f"[ERROR] Request failed: {exc}")
        return None


def build_headers(cookies):
    return build_x_headers(cookies, referer=f"https://x.com/{SCREEN_NAME}")


def fetch_tweets_v1(headers, count=20):
    params = urllib.parse.urlencode({
        "screen_name": SCREEN_NAME, "count": count,
        "tweet_mode": "extended", "include_entities": "false",
    })
    url = f"https://api.x.com/1.1/statuses/user_timeline.json?{params}"
    print(f"[v1.1] Fetching tweets from {SCREEN_NAME}...")
    data = make_request(url, headers)
    if not data or not isinstance(data, list):
        return None
    tweets = []
    for tweet in data:
        text = tweet.get("full_text", tweet.get("text", ""))
        if text.startswith("RT @") and not tweet.get("retweeted_status"):
            continue
        tweets.append({
            "id": tweet.get("id_str", ""), "text": text,
            "likes": tweet.get("favorite_count", 0),
            "retweets": tweet.get("retweet_count", 0),
            "replies": tweet.get("reply_count", 0),
            "views": 0, "created": tweet.get("created_at", ""),
        })
    return tweets


def fetch_user_id(headers):
    url = f"https://api.x.com/1.1/users/show.json?screen_name={SCREEN_NAME}"
    data = make_request(url, headers)
    if data and "id_str" in data:
        return data["id_str"]
    return None


def _extract_graphql_tweet(item):
    result = item.get("tweet_results", {}).get("result", {})
    legacy = result.get("legacy", {})
    if not legacy:
        return None
    text = legacy.get("full_text", legacy.get("text", ""))
    return {
        "id": result.get("rest_id", ""), "text": text,
        "likes": legacy.get("favorite_count", 0),
        "retweets": legacy.get("retweet_count", 0),
        "replies": legacy.get("reply_count", 0),
        "views": result.get("views", {}).get("count", 0),
        "created": legacy.get("created_at", ""),
    }


def fetch_tweets_graphql(headers):
    user_id = fetch_user_id(headers)
    if not user_id:
        print("[GraphQL] Could not resolve user ID")
        return None
    variables = json.dumps({
        "userId": user_id, "count": 20, "includePromotedContent": False,
        "withQuickPromoteEligibilityTweetFields": False,
        "withVoice": False, "withV2Timeline": True,
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
    params = urllib.parse.urlencode({"variables": variables, "features": features})
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
            data.get("data", {}).get("user", {}).get("result", {})
            .get("timeline_v2", {}).get("timeline", {}).get("instructions", [])
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
                for sub in content.get("items", []):
                    nested_item = sub.get("item", {}).get("itemContent", {})
                    tweet = _extract_graphql_tweet(nested_item)
                    if tweet:
                        tweets.append(tweet)
                continue
            tweet = _extract_graphql_tweet(item)
            if tweet:
                tweets.append(tweet)
    except Exception as exc:
        print(f"[GraphQL] Parse error: {exc}")
        return None
    return tweets or None


def get_recent_tweets(headers):
    tweets = fetch_tweets_v1(headers)
    if tweets:
        return tweets
    print("[Fallback] v1.1 failed, trying GraphQL...")
    return fetch_tweets_graphql(headers)


def _parse_twitter_datetime(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
    except Exception:
        return None


def filter_last_24h(tweets):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = []
    for tweet in tweets or []:
        created = _parse_twitter_datetime(tweet.get("created", ""))
        if created and created >= cutoff:
            recent.append(tweet)
    return recent


def build_report(tweets):
    if not tweets:
        return "No se encontraron tweets recientes en las ultimas 24h."
    total_likes = sum(int(tweet.get("likes", 0) or 0) for tweet in tweets)
    total_retweets = sum(int(tweet.get("retweets", 0) or 0) for tweet in tweets)
    total_replies = sum(int(tweet.get("replies", 0) or 0) for tweet in tweets)
    total_views = sum(int(tweet.get("views", 0) or 0) for tweet in tweets)
    best = max(tweets, key=lambda t: (int(t.get("views", 0) or 0), int(t.get("likes", 0) or 0)))
    lines = [
        "<b>Reporte X (24h)</b>", "",
        f"Tweets analizados: <b>{len(tweets)}</b>",
        f"Likes: <b>{total_likes}</b>",
        f"Retweets: <b>{total_retweets}</b>",
        f"Replies: <b>{total_replies}</b>",
        f"Views: <b>{total_views}</b>", "",
        "<b>Mejor tweet</b>",
        best.get("text", "")[:220], "",
        f"Likes: {best.get('likes', 0)} | RTs: {best.get('retweets', 0)} | "
        f"Replies: {best.get('replies', 0)} | Views: {best.get('views', 0)}",
    ]
    return "\n".join(lines)


def main():
    headers = build_headers(get_cookies())
    tweets = get_recent_tweets(headers)
    recent_tweets = filter_last_24h(tweets or [])
    report = build_report(recent_tweets)
    print(report.replace("<b>", "").replace("</b>", ""))
    try:
        send_message(report, parse_mode="HTML")
    except Exception as exc:
        print(f"[ERROR] Failed to send Telegram report: {exc}")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
