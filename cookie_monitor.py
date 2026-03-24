#!/usr/bin/env python3
"""cookie_monitor.py — Verifica que las cookies de X sigan activas."""

import sys
import urllib.error

from config import load_environment
from http_utils import request_json
from telegram_client import send_message
from x_client import build_x_headers, get_x_cookies, has_required_x_cookies

load_environment()


def send_tg(text):
    try:
        send_message(text)
    except Exception as exc:
        print(f"Telegram error: {exc}")


def check_cookies():
    cookies = get_x_cookies()
    if not has_required_x_cookies(cookies):
        print("ERROR: No cookies in .env")
        send_tg(
            "\u26a0\ufe0f ALERTA COOKIES X\n\n"
            "No hay cookies configuradas en .env\n"
            "El bot NO puede publicar."
        )
        return False

    url = "https://api.x.com/1.1/account/verify_credentials.json"
    headers = build_x_headers(cookies, referer="https://x.com/settings/account")

    try:
        data = request_json(url, headers=headers, timeout=15)
        screen_name = data.get("screen_name", "?")
        print(f"Cookies OK — cuenta: @{screen_name}")
        return True
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            print(f"COOKIES EXPIRADAS (HTTP {exc.code})")
            send_tg(
                "\U0001f6a8 ALERTA: COOKIES DE X EXPIRADAS\n\n"
                f"HTTP {exc.code} — Las cookies ya no funcionan.\n"
                "El bot NO puede publicar hasta que las renueves.\n\n"
                "Para renovar:\n"
                "1. Abre x.com en Chrome\n"
                "2. F12 > Application > Cookies\n"
                "3. Copia auth_token, ct0, twid\n"
                "4. Actualiza el archivo .env del bot\n"
                '5. Dile a Sol: \"cookies actualizadas\"'
            )
            return False
        print(f"HTTP error {exc.code} — puede ser temporal")
        return True
    except Exception as exc:
        print(f"Connection error: {exc}")
        return True


if __name__ == "__main__":
    ok = check_cookies()
    if ok:
        print("Todo bien — cookies activas")
    else:
        print("PROBLEMA — revisa Telegram")
        sys.exit(1)
