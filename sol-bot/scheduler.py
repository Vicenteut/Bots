#!/usr/bin/env python3
"""
scheduler.py — Scheduled news scanner + tweet generator for @napoleotics.
Uses jittered scheduling and variable post counts for organic posting rhythm.
"""

import json
import random
import time
import logging
from datetime import datetime
from pathlib import Path

from config import load_environment, BASE_DIR
from fetcher import get_latest_headlines
from filter import is_sensitive
from generator import generate_tweet
from image_manager import get_image_for_tweet
from telegram_client import send_message, send_photo

load_environment()
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Organic posting rhythm
# ------------------------------------------------------------------

def get_daily_post_count() -> int:
    """
    Variable daily post count for natural posting rhythm.
    ~1/30 days: silent (0 posts)
    ~1/14 days: light (1 post)
    else: normal (2-3 posts)
    """
    r = random.random()
    if r < 0.033:
        return 0   # ~1 in 30: completely silent day
    elif r < 0.10:
        return 1   # ~1 in 14: light day
    else:
        return random.choice([2, 3])  # normal day


# ------------------------------------------------------------------
# Telegram helpers
# ------------------------------------------------------------------

def send_tg(text: str):
    send_message(text)


def send_tg_photo(photo_path: str, caption: str):
    try:
        send_photo(photo_path, caption)
    except Exception as e:
        logger.warning(f"Photo send error: {e}")
        send_tg(caption)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    # Jittered startup delay: 5-45 min base + 0-59 sec
    delay_min = random.randint(5, 45)
    delay_sec = delay_min * 60 + random.randint(0, 59)
    now = datetime.now()
    print(f"[{now}] Delay: {delay_min} min")
    time.sleep(delay_sec)

    # Determine post count for today
    count = get_daily_post_count()

    if count == 0:
        logger.info("[scheduler] Silent day — no posts today")
        return

    headlines = get_latest_headlines()
    if not headlines:
        send_tg("No headlines found")
        return

    # Filter sensitive headlines before processing
    clean_headlines = [
        h for h in headlines
        if not is_sensitive(h.get("title", ""), h.get("summary", ""))
    ]

    if not clean_headlines:
        logger.warning("[scheduler] All headlines filtered as sensitive — skipping")
        return

    selected = random.sample(clean_headlines, min(count, len(clean_headlines)))
    nl = chr(10)
    published = 0

    # Clear previous scheduler pending files
    for old_f in BASE_DIR.glob("pending_sched_*.json"):
        old_f.unlink(missing_ok=True)

    for i, h in enumerate(selected, 1):
        try:
            tweet_text = generate_tweet(h)
        except Exception as e:
            logger.error(f"Generator error: {e}")
            continue

        img_path = get_image_for_tweet(h["title"], output_name=f"sched_{i}.jpg")

        # Save to numbered pending file so Sol can publish via /publica N
        pending_data = {
            "tweet": tweet_text,
            "headline": h,
            "generated_at": datetime.now().isoformat(),
            "tweet_type": "SCHEDULED",
        }
        if img_path:
            pending_data["media_path"] = str(img_path)
            pending_data["media_paths"] = [str(img_path)]
            pending_data["media_type"] = "photo"

        pending_file = BASE_DIR /f"pending_sched_{i}.json"
        try:
            pending_file.write_text(json.dumps(pending_data, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"Could not save pending_sched_{i}.json: {e}")

        img_note = " 📷" if img_path else ""
        caption = (
            f"Tweet {i}/{len(selected)}{img_note}:{nl}{nl}"
            f"{tweet_text}{nl}{nl}"
            f"Fuente: {h['source']}{nl}"
            f"Noticia: {h['title'][:100]}{nl}{nl}"
            f"→ /publica {i}  (X + Threads{', con imagen' if img_path else ''})"
        )

        if img_path:
            send_tg_photo(img_path, caption)
        else:
            send_tg(caption)

        published += 1

    print(f"[{datetime.now()}] Done: {published} tweet(s) previewed")


if __name__ == "__main__":
    main()
