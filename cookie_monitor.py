#!/usr/bin/env python3
"""cookie_monitor.py — Verifica que las cookies de X sigan activas.

Hace un request a X con las cookies del .env.
Si fallan o están por expirar, envía alerta a Telegram.

Cron recomendado: cada 6 horas
  0 */6 * * * cd /root/x-bot && python3 cookie_monitor.py
"""

import os, sys, json, urllib.request, urllib.parse, http.cookiejar, time

sys.path.insert(0, '/root/x-bot')
os.chdir('/root/x-bot')
from dotenv import load_dotenv
load_dotenv('/root/x-bot/.env')

AUTH_TOKEN = os.getenv('X_AUTH_TOKEN', '')
CT0 = os.getenv('X_CT0', '')
TWID = os.getenv('X_TWID', '')

BOT_TOKEN = '8603788822:AAHkhXtvyFBqYSA-hglE0aXr_0rAZhFaWxM'
CHAT_ID = 6054558214

def send_tg(text):
    url = 'https://api.telegram.org/bot' + BOT_TOKEN + '/sendMessage'
    data = json.dumps({'chat_id': CHAT_ID, 'text': text}).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f'Telegram error: {e}')

def check_cookies():
    """Test X cookies by fetching account settings API."""
    if not AUTH_TOKEN or not CT0:
        print('ERROR: No cookies in .env')
        send_tg('⚠️ ALERTA COOKIES X\n\nNo hay cookies configuradas en .env\nEl bot NO puede publicar.')
        return False

    # Use X's API endpoint that requires auth
    url = 'https://api.x.com/1.1/account/verify_credentials.json'

    req = urllib.request.Request(url)
    req.add_header('Cookie', f'auth_token={AUTH_TOKEN}; ct0={CT0}; twid={TWID}')
    req.add_header('X-Csrf-Token', CT0)
    req.add_header('Authorization', 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA')
    req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    try:
        res = urllib.request.urlopen(req, timeout=15)
        data = json.loads(res.read())
        screen_name = data.get('screen_name', '?')
        print(f'Cookies OK — cuenta: @{screen_name}')
        return True
    except urllib.error.HTTPError as e:
        if e.code == 401 or e.code == 403:
            print(f'COOKIES EXPIRADAS (HTTP {e.code})')
            send_tg(
                '🚨 ALERTA: COOKIES DE X EXPIRADAS\n\n'
                f'HTTP {e.code} — Las cookies ya no funcionan.\n'
                'El bot NO puede publicar hasta que las renueves.\n\n'
                'Para renovar:\n'
                '1. Abre x.com en Chrome\n'
                '2. F12 > Application > Cookies\n'
                '3. Copia auth_token, ct0, twid\n'
                '4. Actualiza /root/x-bot/.env\n'
                '5. Dile a Sol: "cookies actualizadas"'
            )
            return False
        else:
            print(f'HTTP error {e.code} — puede ser temporal')
            # Don't alert on temporary errors, but log
            return True
    except Exception as e:
        print(f'Connection error: {e}')
        # Network issue, not cookie issue — don't alert
        return True

if __name__ == '__main__':
    ok = check_cookies()
    if ok:
        print('Todo bien — cookies activas')
    else:
        print('PROBLEMA — revisa Telegram')
        sys.exit(1)
