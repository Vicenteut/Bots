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


def send_media_group(photo_paths: list, caption: str, *, timeout: int = DEFAULT_TIMEOUT) -> bool:
    """Send multiple photos as an album (sendMediaGroup)."""
    bot_token = get_required_env("TELEGRAM_BOT_TOKEN")
    chat_id = str(get_required_env("TELEGRAM_CHAT_ID"))
    url = f"https://api.telegram.org/bot{bot_token}/sendMediaGroup"
    boundary = "----WebKitFormBoundary" + str(random.randint(100000, 999999))
    CRLF = b"\r\n"

    media_list = []
    for i, _ in enumerate(photo_paths):
        item = {"type": "photo", "media": f"attach://photo{i}"}
        if i == 0:
            item["caption"] = caption
        media_list.append(item)

    body = b""
    body += ("--" + boundary).encode() + CRLF
    body += b'Content-Disposition: form-data; name="chat_id"' + CRLF + CRLF
    body += chat_id.encode() + CRLF
    body += ("--" + boundary).encode() + CRLF
    body += b'Content-Disposition: form-data; name="media"' + CRLF + CRLF
    body += json.dumps(media_list).encode() + CRLF

    for i, path in enumerate(photo_paths):
        with open(path, "rb") as f:
            data = f.read()
        body += ("--" + boundary).encode() + CRLF
        body += f'Content-Disposition: form-data; name="photo{i}"; filename="photo{i}.jpg"'.encode() + CRLF
        body += b"Content-Type: image/jpeg" + CRLF + CRLF
        body += data + CRLF

    body += ("--" + boundary + "--").encode() + CRLF

    def _send():
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        return bool(result.get("ok"))

    return retry_call(_send, should_retry=is_retryable_http_error)


def send_video(video_path: str, caption: str, *, timeout: int = 60) -> bool:
    import random as _random
    bot_token = get_required_env("TELEGRAM_BOT_TOKEN")
    chat_id = str(get_required_env("TELEGRAM_CHAT_ID"))
    url = f"https://api.telegram.org/bot{bot_token}/sendVideo"
    boundary = "----WebKitFormBoundary" + str(_random.randint(100000, 999999))

    with open(video_path, "rb") as f:
        video_data = f.read()

    CRLF = b"\r\n"
    body = b""
    body += ("--" + boundary).encode() + CRLF
    body += b'Content-Disposition: form-data; name="chat_id"' + CRLF + CRLF
    body += chat_id.encode() + CRLF
    body += ("--" + boundary).encode() + CRLF
    body += b'Content-Disposition: form-data; name="caption"' + CRLF + CRLF
    body += caption.encode("utf-8") + CRLF
    body += ("--" + boundary).encode() + CRLF
    body += b'Content-Disposition: form-data; name="video"; filename="clip.mp4"' + CRLF
    body += b"Content-Type: video/mp4" + CRLF + CRLF
    body += video_data + CRLF
    body += ("--" + boundary + "--").encode() + CRLF

    def _send():
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return bool(data.get("ok"))

    return retry_call(_send, should_retry=is_retryable_http_error)
