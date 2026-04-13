#!/usr/bin/env python3
"""
trending_scanner.py — Detect relevant topics and suggest tweets for @napoleotics.

Reads headlines from the local fetcher, filters by niche keywords
(geopolitics, crypto, finance), generates tweet suggestions with
Claude Haiku, and sends them to Telegram for owner approval.

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
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path("/root/x-bot")
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

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
# Fetch topics from local headlines (official API-free approach)
# ---------------------------------------------------------------------------

def fetch_topics_from_fetcher() -> list[dict]:
    """Read topics from fetcher.py output (local headlines file)."""
    headlines_file = BASE_DIR / "sol-bot" / "headlines.json"
    if not headlines_file.exists():
        # Try alternate location
        headlines_file = BASE_DIR / "headlines.json"
    if not headlines_file.exists():
        log.warning("No headlines.json found — trying live fetcher")
        try:
            sys.path.insert(0, str(BASE_DIR / "sol-bot"))
            from fetcher import get_latest_headlines
            items = get_latest_headlines()
            topics = []
            for item in items[:30]:
                text = item.get("title", "") if isinstance(item, dict) else str(item)
                if text:
                    topics.append({"name": text, "source": item.get("source", ""), "tweet_volume": None})
            log.info("Loaded %d topics from live fetcher", len(topics))
            return topics
        except Exception as e:
            log.error("Live fetcher failed: %s", e)
            return []

    try:
        data = json.loads(headlines_file.read_text())
        topics = []
        for item in data[:30]:
            text = item.get("title", "") if isinstance(item, dict) else str(item)
            if text:
                topics.append({"name": text, "source": item.get("source", ""), "tweet_volume": None})
        log.info("Loaded %d topics from headlines.json", len(topics))
        return topics
    except Exception as e:
        log.error("Failed to read headlines.json: %s", e)
        return []


def get_topics() -> list[dict]:
    """Get topics from local headlines."""
    return fetch_topics_from_fetcher()


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------

def is_relevant(topic_name: str) -> bool:
    """Check if a topic matches niche keywords."""
    lower = topic_name.lower()
    return any(kw in lower for kw in NICHE_KEYWORDS)


def filter_topics(topics: list[dict]) -> list[dict]:
    """Return only niche-relevant topics, deduplicated."""
    seen = set()
    relevant = []
    for t in topics:
        name = t.get("name", "").strip()
        if not name:
            continue
        key = name.lower()[:60]
        if key in seen:
            continue
        if is_relevant(name):
            seen.add(key)
            relevant.append(t)
    log.info("Filtered to %d relevant topics", len(relevant))
    return relevant[:MAX_SUGGESTIONS]


# ---------------------------------------------------------------------------
# Claude Haiku — generate tweet suggestions
# ---------------------------------------------------------------------------

def generate_suggestion(topic_name: str) -> str:
    """Call Claude Haiku to generate a tweet suggestion for a topic."""
    if not ANTHROPIC_API_KEY:
        return f"[Sin API key] Tema: {topic_name}"

    prompt = (
        f"Eres un analista de geopolitica y finanzas. "
        f'El tema es: "{topic_name}". '
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
        if len(text) > 280:
            text = text[:277] + "..."
        text = text.strip('"').strip("\u201c").strip("\u201d")
        return text
    except Exception as e:
        log.error("Claude API error for '%s': %s", topic_name, e)
        return f"[Error generando sugerencia para: {topic_name}]"


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def build_telegram_message(topics_with_suggestions: list[dict]) -> str:
    """Build the formatted Telegram message."""
    if not topics_with_suggestions:
        return (
            "📊 SCANNER DE TEMAS\n\n"
            "No se encontraron temas relevantes en este momento."
        )

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    lines = [f"📰 TEMAS RELEVANTES ({now})\n"]

    for i, item in enumerate(topics_with_suggestions, 1):
        name = item["name"]
        suggestion = item.get("suggestion", "")
        source = item.get("source", "")
        lines.append(f"{i}. {name[:80]}" + (f" [{source}]" if source else ""))
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
    parser = argparse.ArgumentParser(description="Topic scanner for @napoleotics")
    parser.add_argument("--now", action="store_true", help="Skip random startup delay")
    parser.add_argument("--dry-run", action="store_true", help="Print output instead of sending to Telegram")
    args = parser.parse_args()

    if not args.now:
        delay = random.randint(3 * 60, 15 * 60)
        log.info("Waiting %d seconds (%.1f min) before start...", delay, delay / 60)
        time.sleep(delay)

    log.info("=== Topic Scanner started ===")

    # 1. Fetch topics from local headlines
    topics = get_topics()
    if not topics:
        log.warning("No topics fetched")
        msg = build_telegram_message([])
        if args.dry_run:
            print(msg)
        else:
            send_telegram(msg)
        return

    # 2. Filter relevant topics
    relevant = filter_topics(topics)
    if not relevant:
        log.info("No niche-relevant topics found among %d total", len(topics))
        msg = build_telegram_message([])
        if args.dry_run:
            print(msg)
        else:
            send_telegram(msg)
        return

    # 3. Generate suggestions with Claude Haiku
    results = []
    for t in relevant:
        name = t.get("name", "")
        log.info("Generating suggestion for: %s", name[:60])
        suggestion = generate_suggestion(name)
        results.append({
            "name": name,
            "source": t.get("source", ""),
            "tweet_volume": t.get("tweet_volume"),
            "suggestion": suggestion,
        })
        time.sleep(1)

    # 4. Send to Telegram for owner approval
    msg = build_telegram_message(results)
    if args.dry_run:
        print(msg)
    else:
        send_telegram(msg)

    log.info("=== Topic Scanner finished — %d suggestions sent ===", len(results))


if __name__ == "__main__":
    main()
