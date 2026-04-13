#!/usr/bin/env python3
"""
threads_publisher.py — Publish posts to Threads via the official Meta Graph API.

Usage:
    python3 threads_publisher.py "text only post"
    python3 threads_publisher.py --image /path/or/url "caption"
    python3 threads_publisher.py --image img1.jpg --image img2.jpg --image img3.jpg "caption"
    python3 threads_publisher.py --video /path/or/url "caption"
    python3 threads_publisher.py --refresh-token
"""

import json
import os
import re
import sys
import time
import uuid
import subprocess
import urllib.error
import urllib.parse
import urllib.request

QUIET_MODE = False
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
BASE_URL = "https://graph.threads.net/v1.0"


def load_env(path):
    if not os.path.exists(path):
        print(f"[ERROR] .env file not found: {path}")
        sys.exit(1)
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ[key.strip()] = value.strip().strip("'\"")


load_env(ENV_PATH)

ACCESS_TOKEN = os.environ.get("THREADS_ACCESS_TOKEN", "")
USER_ID      = os.environ.get("THREADS_USER_ID", "")
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
MEDIA_HOST   = os.environ.get("THREADS_MEDIA_HOST", "").rstrip("/")
THREADS_POST_MAX_CHARS = 500

if not ACCESS_TOKEN or not USER_ID:
    print("[ERROR] THREADS_ACCESS_TOKEN and THREADS_USER_ID must be set in .env")
    sys.exit(1)


def replace_flags(text):
    text = re.compile('[🇠-🇿]{2}').sub('', text)
    return re.sub(r'  +', ' ', text).strip()


def prepare_post_text(text):
    text = replace_flags(text)
    if len(text) > THREADS_POST_MAX_CHARS:
        print(f"[ERROR] Threads post is {len(text)} chars; max is {THREADS_POST_MAX_CHARS}", file=sys.stderr)
        return None
    return text


def api_post(url, params):
    data = json.dumps(params, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"[HTTP ERROR {e.code}] {error_body}")
        raise
    except urllib.error.URLError as e:
        print(f"[URL ERROR] {e.reason}")
        raise


def api_get(url):
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"[HTTP ERROR {e.code}] {e.read().decode('utf-8', errors='replace')}")
        raise


def send_tg(message):
    if QUIET_MODE or not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    params = {"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        data = json.dumps(params).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=15):
            pass
    except Exception as e:
        print(f"[TG WARNING] {e}")


def upload_file_to_litterbox(local_path, duration="1h", content_type="application/octet-stream", label="media"):
    """Upload a local media file to Litterbox and return a temporary HTTPS URL."""
    if local_path.startswith("http"):
        return local_path
    if not os.path.exists(local_path):
        print(f"[ERROR] File not found for upload: {local_path}", file=sys.stderr)
        return None

    boundary = f"----codex{uuid.uuid4().hex}"

    def field(name, value):
        return (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"{name}\"\r\n\r\n"
            f"{value}\r\n"
        ).encode("utf-8")

    filename = os.path.basename(local_path)
    body = bytearray()
    body += field("reqtype", "fileupload")
    body += field("time", duration)
    body += (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"fileToUpload\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    with open(local_path, "rb") as f:
        body += f.read()
    body += f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request("https://litterbox.catbox.moe/resources/internals/api.php", data=bytes(body), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("User-Agent", "sol-bot/threads-media-uploader")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            url = resp.read().decode("utf-8", errors="replace").strip()
    except Exception as e:
        print(f"[ERROR] Litterbox upload failed: {e}", file=sys.stderr)
        return None
    if not url.startswith("https://"):
        print(f"[ERROR] Litterbox upload returned unexpected response: {url}", file=sys.stderr)
        return None
    print(f"[THREADS] Temporary HTTPS {label} URL: {url}")
    return url


def upload_video_to_litterbox(local_path, duration="1h"):
    """Upload a normalized video to Litterbox and return a temporary HTTPS URL."""
    return upload_file_to_litterbox(local_path, duration, "video/mp4", "video")


def prepare_image_for_threads(local_path):
    """Normalize local images to baseline JPEG accepted by Threads ingestion."""
    if local_path.startswith("http"):
        return local_path
    if not os.path.exists(local_path):
        print(f"[ERROR] File not found: {local_path}", file=sys.stderr)
        return None
    ffmpeg = "ffmpeg"
    base, _ = os.path.splitext(local_path)
    out_path = f"{base}.threads.jpg"
    cmd = [
        ffmpeg, "-y", "-i", local_path,
        "-vf", "scale='min(1440,iw)':-2,format=yuvj420p",
        "-frames:v", "1",
        "-q:v", "3",
        out_path,
    ]
    print(f"[THREADS] Normalizing image for Threads: {os.path.basename(out_path)}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        print("[ERROR] ffmpeg is not installed; cannot normalize image", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print("[ERROR] ffmpeg timed out while normalizing image", file=sys.stderr)
        return None
    if r.returncode != 0:
        print(f"[ERROR] ffmpeg image normalization failed: {(r.stderr or r.stdout)[-1000:]}", file=sys.stderr)
        return None
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        print("[ERROR] ffmpeg produced no image output", file=sys.stderr)
        return None
    return out_path


def get_image_url(local_path):
    """Return an HTTPS URL for Threads image uploads."""
    if local_path.startswith("https://"):
        return local_path
    if local_path.startswith("http://"):
        print("[ERROR] Threads image uploads require HTTPS; got HTTP URL", file=sys.stderr)
        return None
    prepared = prepare_image_for_threads(local_path)
    if not prepared:
        return None
    host_mode = os.environ.get("THREADS_IMAGE_HOST", "litterbox").strip().lower()
    if host_mode in ("litterbox", "catbox", "https"):
        return upload_file_to_litterbox(prepared, os.environ.get("THREADS_IMAGE_TTL", "1h"), "image/jpeg", "image")
    return get_public_url(prepared)


def get_video_url(local_path):
    """Return an HTTPS URL for Threads video uploads."""
    if local_path.startswith("https://"):
        return local_path
    if local_path.startswith("http://"):
        print("[ERROR] Threads video uploads require HTTPS; got HTTP URL", file=sys.stderr)
        return None
    prepared = prepare_video_for_threads(local_path)
    if not prepared:
        return None
    host_mode = os.environ.get("THREADS_VIDEO_HOST", "litterbox").strip().lower()
    if host_mode in ("litterbox", "catbox", "https"):
        return upload_video_to_litterbox(prepared, os.environ.get("THREADS_VIDEO_TTL", "1h"))
    return get_public_url(prepared)


def prepare_video_for_threads(local_path):
    """Normalize local videos to a conservative MP4 profile accepted by Threads."""
    if local_path.startswith("http"):
        return local_path
    if not os.path.exists(local_path):
        print(f"[ERROR] File not found: {local_path}", file=sys.stderr)
        return None
    ffmpeg = "ffmpeg"
    base, _ = os.path.splitext(local_path)
    out_path = f"{base}.threads.mp4"
    cmd = [
        ffmpeg, "-y", "-i", local_path,
        "-map", "0:v:0", "-map", "0:a?",
        "-vf", "fps=30,format=yuv420p",
        "-c:v", "libx264", "-profile:v", "main", "-level", "4.0",
        "-preset", "veryfast", "-crf", "23",
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        out_path,
    ]
    print(f"[THREADS] Normalizing video for Threads: {os.path.basename(out_path)}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        print("[ERROR] ffmpeg is not installed; cannot normalize video", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print("[ERROR] ffmpeg timed out while normalizing video", file=sys.stderr)
        return None
    if r.returncode != 0:
        print(f"[ERROR] ffmpeg failed: {(r.stderr or r.stdout)[-1000:]}", file=sys.stderr)
        return None
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        print("[ERROR] ffmpeg produced no output", file=sys.stderr)
        return None
    return out_path


def get_public_url(local_path):
    if local_path.startswith("http"):
        return local_path
    if not os.path.exists(local_path):
        print(f"[ERROR] File not found: {local_path}", file=sys.stderr)
        return None
    if not MEDIA_HOST:
        print("[ERROR] THREADS_MEDIA_HOST not set in .env", file=sys.stderr)
        return None
    filename = os.path.basename(local_path)
    url = f"{MEDIA_HOST}/media/{urllib.parse.quote(filename)}"
    print(f"  Public URL: {url}")
    return url


def wait_for_container(container_id, max_wait=60, interval=3):
    elapsed = 0
    while elapsed < max_wait:
        url = f"{BASE_URL}/{container_id}?fields=status,error_message&access_token={ACCESS_TOKEN}"
        try:
            result = api_get(url)
        except Exception:
            time.sleep(interval)
            elapsed += interval
            continue
        status = result.get("status", "UNKNOWN")
        print(f"  Container {container_id} status: {status}")
        if status == "FINISHED":
            return True
        if status == "ERROR":
            print(f"[ERROR] Container failed: {result.get('error_message', 'unknown')}")
            return False
        time.sleep(interval)
        elapsed += interval
    print(f"[ERROR] Container timed out after {max_wait}s")
    return False


def _create_container(params):
    result = api_post(f"{BASE_URL}/{USER_ID}/threads", params)
    cid = result.get("id")
    if not cid:
        print(f"[ERROR] No container ID: {result}")
    return cid


def _publish(container_id):
    result = api_post(f"{BASE_URL}/{USER_ID}/threads_publish", {"creation_id": container_id, "access_token": ACCESS_TOKEN})
    post_id = result.get("id")
    if not post_id:
        print(f"[ERROR] No post ID: {result}")
    return post_id


def publish_text(text):
    post_text = prepare_post_text(text)
    if not post_text:
        return None
    print(f"[THREADS] Publishing text ({len(post_text)} chars)...")
    cid = _create_container({"media_type": "TEXT", "text": post_text, "access_token": ACCESS_TOKEN})
    if not cid:
        return None
    post_id = _publish(cid)
    if post_id:
        print(f"[SUCCESS] Post published! ID: {post_id}")
        send_tg(f"<b>Threads post published</b>\n\n{text[:200]}\n\nID: <code>{post_id}</code>")
    return post_id


def publish_single_image(text, image_url):
    post_text = prepare_post_text(text)
    if not post_text:
        return None
    print(f"[THREADS] Publishing single image...")
    cid = _create_container({"media_type": "IMAGE", "image_url": image_url, "text": post_text, "access_token": ACCESS_TOKEN})
    if not cid:
        return None
    if not wait_for_container(cid):
        return None
    post_id = _publish(cid)
    if post_id:
        print(f"[SUCCESS] Image post published! ID: {post_id}")
        send_tg(f"<b>Threads image published</b>\n\n{text[:200]}\n\nID: <code>{post_id}</code>")
    return post_id


def publish_carousel(text, image_urls):
    post_text = prepare_post_text(text)
    if not post_text:
        return None
    print(f"[THREADS] Publishing carousel with {len(image_urls)} images...")
    children_ids = []
    for i, url in enumerate(image_urls[:10]):
        print(f"  Creating carousel item {i+1}/{len(image_urls)}...")
        cid = _create_container({
            "media_type": "IMAGE",
            "image_url": url,
            "is_carousel_item": True,
            "access_token": ACCESS_TOKEN,
        })
        if not cid:
            print(f"  [WARN] Skipping item {i+1}")
            continue
        if not wait_for_container(cid, max_wait=60):
            print(f"  [WARN] Item {i+1} failed processing, skipping")
            continue
        children_ids.append(cid)
        print(f"  Item {i+1} ready: {cid}")

    if len(children_ids) == 0:
        print("[ERROR] No carousel items succeeded")
        return None
    if len(children_ids) == 1:
        print("[FALLBACK] Only 1 item succeeded, publishing as single image")
        return publish_single_image(text, image_urls[0])

    print(f"  Creating carousel container with {len(children_ids)} items...")
    carousel_cid = _create_container({
        "media_type": "CAROUSEL",
        "children": ",".join(children_ids),
        "text": post_text,
        "access_token": ACCESS_TOKEN,
    })
    if not carousel_cid:
        return None
    if not wait_for_container(carousel_cid, max_wait=60):
        return None
    post_id = _publish(carousel_cid)
    if post_id:
        print(f"[SUCCESS] Carousel published! ID: {post_id}")
        send_tg(f"<b>Threads carousel published ({len(children_ids)} images)</b>\n\n{text[:200]}\n\nID: <code>{post_id}</code>")
    return post_id


def publish_video(text, video_url):
    post_text = prepare_post_text(text)
    if not post_text:
        return None
    print(f"[THREADS] Publishing video...")
    cid = _create_container({"media_type": "VIDEO", "video_url": video_url, "text": post_text, "access_token": ACCESS_TOKEN})
    if not cid:
        return None
    # Video processing often takes longer than images; avoid false negatives too early.
    if not wait_for_container(cid, max_wait=300, interval=5):
        return None
    post_id = _publish(cid)
    if post_id:
        print(f"[SUCCESS] Video published! ID: {post_id}")
        send_tg(f"<b>Threads video published</b>\n\n{text[:200]}\n\nID: <code>{post_id}</code>")
    return post_id


def refresh_token():
    print("[THREADS] Refreshing access token...")
    url = f"{BASE_URL}/refresh_access_token?grant_type=th_refresh_token&access_token={ACCESS_TOKEN}"
    result = api_get(url)
    new_token = result.get("access_token")
    expires_in = result.get("expires_in", 0)
    if not new_token:
        print(f"[ERROR] Token refresh failed: {result}")
        return None
    days = expires_in // 86400
    print(f"[SUCCESS] Token refreshed! Expires in {days} days.")
    try:
        with open(ENV_PATH, "r") as f:
            lines = f.readlines()
        with open(ENV_PATH, "w") as f:
            for line in lines:
                if line.strip().startswith("THREADS_ACCESS_TOKEN="):
                    f.write(f"THREADS_ACCESS_TOKEN={new_token}\n")
                else:
                    f.write(line)
        print(f"  Updated {ENV_PATH}")
    except Exception as e:
        print(f"[WARNING] Could not update .env: {e}")
    send_tg(f"<b>Threads token refreshed</b>\nExpires in {days} days.")
    return new_token


def main():
    global QUIET_MODE
    args = sys.argv[1:]

    if "--quiet" in args:
        QUIET_MODE = True
        args = [a for a in args if a != "--quiet"]

    if not args:
        print(__doc__)
        sys.exit(1)

    if args[0] == "--refresh-token":
        refresh_token()
        return

    if args[0] == "--video":
        if len(args) < 3:
            print("[ERROR] --video requires a path/URL and caption text")
            sys.exit(1)
        video_url = get_video_url(args[1])
        text = " ".join(args[2:])
        if not video_url:
            print("[ERROR] Video could not be normalized/uploaded to an HTTPS URL")
            sys.exit(1)
        post_id = publish_video(text, video_url)
        sys.exit(0 if post_id else 1)

    image_inputs = []
    remaining = []
    i = 0
    while i < len(args):
        if args[i] == "--image" and i + 1 < len(args):
            image_inputs.append(args[i + 1])
            i += 2
        else:
            remaining.append(args[i])
            i += 1

    text = " ".join(remaining).strip()
    if not text:
        print("[ERROR] No caption text provided")
        sys.exit(1)

    if not image_inputs:
        post_id = publish_text(text)
        sys.exit(0 if post_id else 1)

    image_urls = [u for u in (get_image_url(p) for p in image_inputs) if u]

    if not image_urls:
        print("[ERROR] No valid image URLs; refusing to publish media request as text-only")
        sys.exit(1)

    if len(image_urls) == 1:
        post_id = publish_single_image(text, image_urls[0])
    else:
        post_id = publish_carousel(text, image_urls)
    sys.exit(0 if post_id else 1)


if __name__ == "__main__":
    main()
