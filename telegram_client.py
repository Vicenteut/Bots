from __future__ import annotations

import json
import random
import urllib.error
import urllib.request

from config import get_required_env
from http_utils import DEFAULT_TIMEOUT, is_retryable_http_error, retry_call


def send_message(
    text: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    parse_mode: str | None = None,
    disable_web_page_preview: bool | None = None,
) -> bool:
    bot_token = get_required_env("TELEGRAM_BOT_TOKEN")
    chat_id = str(get_required_env("TELEGRAM_CHAT_ID"))
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if disable_web_page_preview is not None:
        payload["disable_web_page_preview"] = disable_web_page_preview

    def _send():
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return bool(data.get("ok"))

    return retry_call(_send, should_retry=is_retryable_http_error)


def send_photo(photo_path: str, caption: str, *, timeout: int = DEFAULT_TIMEOUT) -> bool:
    bot_token = get_required_env("TELEGRAM_BOT_TOKEN")
    chat_id = str(get_required_env("TELEGRAM_CHAT_ID"))
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    boundary = "----WebKitFormBoundary" + str(random.randint(100000, 999999))

    with open(photo_path, "rb") as file_obj:
        photo_data = file_obj.read()

    CRLF = b"\r\n"
    body = b""
    body += ("--" + boundary).encode() + CRLF
    body += b'Content-Disposition: form-data; name="chat_id"' + CRLF + CRLF
    body += chat_id.encode() + CRLF
    body += ("--" + boundary).encode() + CRLF
    body += b'Content-Disposition: form-data; name="caption"' + CRLF + CRLF
    body += caption.encode("utf-8") + CRLF
    body += ("--" + boundary).encode() + CRLF
    body += b'Content-Disposition: form-data; name="photo"; filename="tweet.jpg"' + CRLF
    body += b"Content-Type: image/jpeg" + CRLF + CRLF
    body += photo_data + CRLF
    body += ("--" + boundary + "--").encode() + CRLF

    def _send():
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return bool(data.get("ok"))

    return retry_call(_send, should_retry=is_retryable_http_error)
