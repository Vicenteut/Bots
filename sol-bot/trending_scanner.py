#!/usr/bin/env python3
"""
trending_scanner.py — Detect trending topics on X/Twitter and suggest tweets.

Fetches worldwide trends via X internal API (cookie auth), filters by niche
keywords (geopolitics, crypto, finance), generates tweet suggestions with
Claude Haiku, and sends them to Telegram for approval.

Cron recommendation (add to crontab -e):
  0 10 * * * cd /root/x-bot && /usr/bin/python3 trending_scanner.py >> /root/x-bot/logs/trending.log 2>&1
  0 16 * * * cd /root/x-bot && /usr/bin/python3 trending_scanner.py >> /root/x-bot/logs/trending.log 2>&1

CLI mode:
  python3 trending_scanner.py --now          # skip random delay
  python3 trending_scanner.py --dry-run      # print to stdout, don't send to Telegram
  python3 trending_scanner.py --now --dry-run
"""

import os
import sys
import json
import time
import random
import argparse
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path("/root/x-bot")
ENV_PATH = BASE_DIR / ".env"
COOKIE_FILE = BASE_DIR / "cookies.json"

load_dotenv(ENV_PATH)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

BEARER_TOKEN = (
    "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

TRENDS_URL = "https://api.x.com/1.1/trends/place.json?id=1"

NICHE_KEYWORDS = [
    "iran", "israel", "russia", "ukraine", "china", "trump", "biden",
    "bitcoin", "btc", "crypto", "ethereum", "oil", "gold", "fed",
    "inflation", "war", "nato", "brics", "sanctions", "dollar",
    "market", "economy", "gaza", "nuclear", "missile", "tariff", "opec",
]

MAX_SUGGESTIONS = 8  # cap to avoid huge Telegram messages

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("trending")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_cookies() -> dict:
    """Load X cookies from cookies.json (Puppeteer format) or .env fallback."""
    cookies = {}
    if COOKIE_FILE.exists():
        try:
            data = json.loads(COOKIE_FILE.read_text())
            for c in data:
                name = c.get("name", "")
                if name in ("auth_token", "ct0", "twid"):
                    cookies[name] = c.get("value", "")
            if cookies.get("auth_token") and cookies.get("ct0"):
                log.info("Loaded cookies from %s", COOKIE_FILE)
                return cookies
        except Exception as e:
            log.warning("Failed to parse cookies.json: %s", e)

    # Fallback: read from .env
    cookies = {
        "auth_token": os.getenv("X_AUTH_TOKEN", ""),
        "ct0": os.getenv("X_CT0", ""),
        "twid": os.getenv("X_TWID", ""),
    }
    if cookies.get("auth_token") and cookies.get("ct0"):
        log.info("Loaded cookies from .env")
    else:
        log.warning("No valid X cookies found")
    return cookies


def build_headers(cookies: dict) -> dict:
    """Build request headers for X internal API."""
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items() if v)
    return {
        "Authorization": BEARER_TOKEN,
        "Cookie": cookie_str,
        "X-Csrf-Token": cookies.get("ct0", ""),
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Referer": "https://x.com/explore/tabs/trending",
        "X-Twitter-Active-User": "yes",
        "X-Twitter-Client-Language": "en",
    }


# ---------------------------------------------------------------------------
# Fetch trends
# ---------------------------------------------------------------------------

def fetch_trends_api(cookies: dict) -> list[dict]:
    """
    Fetch worldwide trends from X API.
    Returns list of dicts: {"name": str, "tweet_volume": int|None, "url": str}
    """
    headers = build_headers(cookies)
    try:
        resp = requests.get(TRENDS_URL, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and len(data) > 0:
            trends = data[0].get("trends", [])
            log.info("Fetched %d trends from X API", len(trends))
            return trends
    except Exception as e:
        log.error("X trends API failed: %s", e)
    return []


def fetch_trends_explore(cookies: dict) -> list[dict]:
    """
    Fallback: fetch trends from X explore/trending GraphQL endpoint.
    """
    url = (
        "https://x.com/i/api/2/guide.json"
        "?include_profile_interstitial_type=1"
        "&include_blocking=1"
        "&include_blocked_by=1"
        "&count=20"
        "&candidate_source=trends"
        "&include_page_configuration=false"
        "&entity_tokens=false"
    )
    headers = build_headers(cookies)
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        trends = []
        timeline = data.get("timeline", {}).get("instructions", [])
        for instr in timeline:
            entries = instr.get("addEntries", {}).get("entries", [])
            for entry in entries:
                trend_meta = (
                    entry.get("content", {})
                    .get("timelineModule", {})
                    .get("items", [])
                )
                for item in trend_meta:
                    ct = item.get("item", {}).get("content", {}).get("trend", {})
                    if ct.get("name"):
                        trends.append({
                            "name": ct["name"],
                            "tweet_volume": ct.get("trendMetadata", {}).get(
                                "metaDescription", None
                            ),
                            "url": ct.get("url", {}).get("url", ""),
                        })
        log.info("Fetched %d trends from explore fallback", len(trends))
        return trends
    except Exception as e:
        log.error("Explore fallback failed: %s", e)
    return []


def fetch_trends_from_fetcher() -> list[dict]:
    """
    Last-resort fallback: read headlines from fetcher.py output if available.
    """
    headlines_file = BASE_DIR / "headlines.json"
    if not headlines_file.exists():
        return []
    try:
        data = json.loads(headlines_file.read_text())
        trends = []
        for item in data[:30]:
            text = item if isinstance(item, str) else item.get("text", "")
            if text:
                trends.append({"name": text, "tweet_volume": None, "url": ""})
        log.info("Loaded %d headlines from fetcher fallback", len(trends))
        return trends
    except Exception as e:
        log.error("Fetcher fallback failed: %s", e)
    return []


def get_trends(cookies: dict) -> list[dict]:
    """Try all sources in order."""
    trends = fetch_trends_api(cookies)
    if not trends:
        log.info("Primary API failed, trying explore fallback...")
        trends = fetch_trends_explore(cookies)
    if not trends:
        log.info("Explore failed, trying fetcher headlines...")
        trends = fetch_trends_from_fetcher()
    return trends


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------

def is_relevant(trend_name: str) -> bool:
    """Check if a trend matches niche keywords."""
    lower = trend_name.lower()
    # Strip leading # for matching
    clean = lower.lstrip("#")
    return any(kw in clean for kw in NICHE_KEYWORDS)


def filter_trends(trends: list[dict]) -> list[dict]:
    """Return only niche-relevant trends, deduplicated."""
    seen = set()
    relevant = []
    for t in trends:
        name = t.get("name", "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        if is_relevant(name):
            seen.add(key)
            relevant.append(t)
    log.info("Filtered to %d relevant trends", len(relevant))
    return relevant[:MAX_SUGGESTIONS]


# ---------------------------------------------------------------------------
# Claude Haiku — generate tweet suggestions
# ---------------------------------------------------------------------------

def generate_suggestion(trend_name: str) -> str:
    """Call Claude Haiku to generate a tweet suggestion for a trend."""
    if not ANTHROPIC_API_KEY:
        return f"[Sin API key] Tema trending: {trend_name}"

    prompt = (
        f"Eres un analista de geopolitica y finanzas. "
        f'El tema trending es: "{trend_name}". '
        f"Genera un tweet en espanol, maximo 280 caracteres, estilo analitico "
        f"con perspectiva unica. Sin hashtags. Maximo 1 emoji."
    )

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 350,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["content"][0]["text"].strip()
        # Ensure within 280 chars
        if len(text) > 280:
            text = text[:277] + "..."
        # Strip surrounding quotes if present
        text = text.strip('"').strip("\u201c").strip("\u201d")
        return text
    except Exception as e:
        log.error("Claude API error for '%s': %s", trend_name, e)
        return f"[Error generando sugerencia para: {trend_name}]"


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def format_volume(vol) -> str:
    """Format tweet volume for display."""
    if vol is None:
        return "N/A"
    try:
        v = int(vol)
        if v >= 1_000_000:
            return f"{v / 1_000_000:.1f}M"
        if v >= 1_000:
            return f"{v / 1_000:.1f}K"
        return str(v)
    except (ValueError, TypeError):
        return str(vol)


def build_telegram_message(trends_with_suggestions: list[dict]) -> str:
    """Build the formatted Telegram message."""
    if not trends_with_suggestions:
        return (
            "📊 TRENDING SCANNER\n\n"
            "No se encontraron tendencias relevantes en este momento."
        )

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    lines = [f"🔥 TRENDING RELEVANTE ({now})\n"]

    for i, item in enumerate(trends_with_suggestions, 1):
        name = item["name"]
        vol = format_volume(item.get("tweet_volume"))
        suggestion = item.get("suggestion", "")
        lines.append(f"{i}. {name} ({vol} tweets)")
        lines.append(f'💡 Sugerencia: "{suggestion}"\n')

    lines.append('Responde "publica X" para publicar.')
    return "\n".join(lines)


def send_telegram(message: str) -> bool:
    """Send message to Telegram."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        log.info("Telegram message sent")
        return True
    except Exception as e:
        log.error("Telegram send failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="X/Twitter trending scanner")
    parser.add_argument(
        "--now", action="store_true", help="Skip random startup delay"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print output instead of sending to Telegram"
    )
    args = parser.parse_args()

    # Random delay for cron (3-15 minutes)
    if not args.now:
        delay = random.randint(3 * 60, 15 * 60)
        log.info("Waiting %d seconds (%.1f min) before start...", delay, delay / 60)
        time.sleep(delay)

    log.info("=== Trending Scanner started ===")

    # 1. Load cookies
    cookies = load_cookies()

    # 2. Fetch trends
    trends = get_trends(cookies)
    if not trends:
        log.warning("No trends fetched from any source")
        msg = build_telegram_message([])
        if args.dry_run:
            print(msg)
        else:
            send_telegram(msg)
        return

    # 3. Filter relevant trends
    relevant = filter_trends(trends)
    if not relevant:
        log.info("No niche-relevant trends found among %d total", len(trends))
        msg = build_telegram_message([])
        if args.dry_run:
            print(msg)
        else:
            send_telegram(msg)
        return

    # 4. Generate suggestions with Claude Haiku
    results = []
    for t in relevant:
        name = t.get("name", "")
        log.info("Generating suggestion for: %s", name)
        suggestion = generate_suggestion(name)
        results.append({
            "name": name,
            "tweet_volume": t.get("tweet_volume"),
            "suggestion": suggestion,
        })
        # Small delay between API calls
        time.sleep(1)

    # 5. Send to Telegram
    msg = build_telegram_message(results)
    if args.dry_run:
        print(msg)
    else:
        send_telegram(msg)

    log.info("=== Trending Scanner finished — %d suggestions sent ===", len(results))


if __name__ == "__main__":
    main()
