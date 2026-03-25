#!/usr/bin/env python3
"""Scheduled news scanner + tweet generator with images for @napoleotics."""
import json
import random
import time
from datetime import datetime
from pathlib import Path

from config import load_environment
from fetcher import get_latest_headlines
from generator import generate_tweet
from image_manager import get_image_for_tweet
from telegram_client import send_message, send_photo

load_environment()

PENDING_FILE = Path(__file__).resolve().parent.parent / "sol_pending.json"


def save_pending_drafts(drafts: list) -> None:
    """Save generated tweet drafts for Armandito to pick up."""
    try:
        with open(PENDING_FILE, "w") as f:
            json.dump({"drafts": drafts, "generated_at": datetime.now().isoformat()}, f)
    except Exception as e:
        print(f"[WARN] Could not save pending drafts: {e}")


def send_tg(text):
    send_message(text)


def send_tg_photo(photo_path, caption):
    try:
        send_photo(photo_path, caption)
    except Exception as e:
        print('Photo send error: ' + str(e))
        send_tg(caption)


def main():
    delay_min = random.randint(5, 45)
    delay_sec = delay_min * 60 + random.randint(0, 59)
    now = datetime.now()
    print('[' + str(now) + '] Delay: ' + str(delay_min) + ' min')
    time.sleep(delay_sec)

    headlines = get_latest_headlines()
    if not headlines:
        send_tg('No headlines found')
        return

    count = random.choice([2, 3])
    selected = random.sample(headlines, min(count, len(headlines)))

    nl = chr(10)
    drafts = []

    for i, h in enumerate(selected, 1):
        try:
            tweet_text = generate_tweet(h)
        except Exception as e:
            print('Generator error: ' + str(e))
            continue

        img_path = get_image_for_tweet(h['title'], output_name='sched_' + str(i) + '.jpg')

        drafts.append({
            "index": i,
            "tweet": tweet_text,
            "image_path": img_path,
            "source": h['source'],
            "headline": h['title'],
        })

        caption = 'Tweet ' + str(i) + '/' + str(count) + ':' + nl + nl
        caption += tweet_text + nl + nl
        caption += 'Fuente: ' + h['source'] + nl
        caption += 'Noticia: ' + h['title'][:100] + nl + nl
        caption += 'Dile a Armandito "publica ' + str(i) + '" para publicar con imagen.'

        if img_path:
            send_tg_photo(img_path, caption)
        else:
            send_tg(caption)

    if drafts:
        save_pending_drafts(drafts)

    print('[' + str(datetime.now()) + '] Done: ' + str(count) + ' tweets')

if __name__ == '__main__':
    main()
