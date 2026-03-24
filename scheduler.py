#!/usr/bin/env python3
"""Scheduled news scanner + tweet generator with images for @napoleotics."""
import random
import time
from datetime import datetime

from config import load_environment
from fetcher import get_latest_headlines
from generator import generate_tweet
from image_manager import get_image_for_tweet
from telegram_client import send_message, send_photo

load_environment()


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

    for i, h in enumerate(selected, 1):
        try:
            tweet_text = generate_tweet(h)
        except Exception as e:
            print('Generator error: ' + str(e))
            continue

        img_path = get_image_for_tweet(h['title'], output_name='sched_' + str(i) + '.jpg')

        caption = 'Tweet ' + str(i) + '/' + str(count) + ':' + nl + nl
        caption += tweet_text + nl + nl
        caption += 'Fuente: ' + h['source'] + nl
        caption += 'Noticia: ' + h['title'][:100] + nl + nl
        caption += 'Responde "publica ' + str(i) + '" a Sol para publicar con imagen.'

        if img_path:
            send_tg_photo(img_path, caption)
        else:
            send_tg(caption)

    print('[' + str(datetime.now()) + '] Done: ' + str(count) + ' tweets')

if __name__ == '__main__':
    main()
