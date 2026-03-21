#!/usr/bin/env python3
"""Scheduled news scanner + tweet generator with images for @napoleotics."""
import sys, os, json, random, time, urllib.request
from datetime import datetime

sys.path.insert(0, '/root/x-bot')
os.chdir('/root/x-bot')
from dotenv import load_dotenv
load_dotenv('/root/x-bot/.env')

from fetcher import get_latest_headlines
from generator import generate_tweet
from image_manager import get_image_for_tweet

BOT_TOKEN = '8603788822:AAHkhXtvyFBqYSA-hglE0aXr_0rAZhFaWxM'
CHAT_ID = 6054558214

def send_tg(text):
    url = 'https://api.telegram.org/bot' + BOT_TOKEN + '/sendMessage'
    data = json.dumps({'chat_id': CHAT_ID, 'text': text}).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req)

def send_tg_photo(photo_path, caption):
    """Send photo with caption to Telegram."""
    import mimetypes
    boundary = '----WebKitFormBoundary' + str(random.randint(100000, 999999))
    url = 'https://api.telegram.org/bot' + BOT_TOKEN + '/sendPhoto'

    with open(photo_path, 'rb') as f:
        photo_data = f.read()

    body = b''
    # chat_id field
    body += ('--' + boundary + '\r\n').encode()
    body += b'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
    body += str(CHAT_ID).encode() + b'\r\n'
    # caption field
    body += ('--' + boundary + '\r\n').encode()
    body += b'Content-Disposition: form-data; name="caption"\r\n\r\n'
    body += caption.encode('utf-8') + b'\r\n'
    # photo field
    body += ('--' + boundary + '\r\n').encode()
    body += b'Content-Disposition: form-data; name="photo"; filename="tweet.jpg"\r\n'
    body += b'Content-Type: image/jpeg\r\n\r\n'
    body += photo_data + b'\r\n'
    body += ('--' + boundary + '--\r\n').encode()

    req = urllib.request.Request(url, data=body)
    req.add_header('Content-Type', 'multipart/form-data; boundary=' + boundary)
    try:
        urllib.request.urlopen(req, timeout=30)
    except Exception as e:
        print('Photo send error: ' + str(e))
        send_tg(caption)

def main():
    # Random delay: 5-45 minutes
    delay_min = random.randint(5, 45)
    delay_sec = delay_min * 60 + random.randint(0, 59)
    now = datetime.now()
    print('[' + str(now) + '] Delay: ' + str(delay_min) + 'm')
    time.sleep(delay_sec)

    headlines = get_latest_headlines(n=8)
    if not headlines:
        print('No headlines')
        return

    count = random.choice([2, 3])
    selected = random.sample(headlines, min(count, len(headlines)))

    NL = chr(10)
    hour = datetime.now().hour

    for i, h in enumerate(selected, 1):
        try:
            tweet_text = generate_tweet(h)
        except Exception as e:
            print('Generator error: ' + str(e))
            continue

        # Fetch image
        img_path = get_image_for_tweet(h['title'], output_name='sched_' + str(i) + '.jpg')

        caption = 'Tweet ' + str(i) + '/' + str(count) + ':' + NL + NL
        caption += tweet_text + NL + NL
        caption += 'Fuente: ' + h['source'] + NL
        caption += 'Noticia: ' + h['title'][:100] + NL + NL
        caption += 'Responde "publica ' + str(i) + '" a Sol para publicar con imagen.'

        if img_path:
            send_tg_photo(img_path, caption)
        else:
            send_tg(caption)

        print('[' + str(datetime.now()) + '] Tweet ' + str(i) + ' enviado')
        time.sleep(2)

    print('[' + str(datetime.now()) + '] Done: ' + str(count) + ' tweets generados')

if __name__ == '__main__':
    main()
