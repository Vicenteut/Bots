#!/usr/bin/env python3
"""
Threads Publisher - Publish posts to Instagram Threads via the official API.

Usage:
    python3 threads_publisher.py "single post text"
    python3 threads_publisher.py --image "https://url/img.jpg" "caption text"
    python3 threads_publisher.py --thread "tweet1" "tweet2" "tweet3"
    python3 threads_publisher.py --refresh-token
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ENV_PATH = "/root/x-bot/.env"
BASE_URL = "https://graph.threads.net/v1.0"

TG_BOT_TOKEN = "8603788822:AAHkhXtvyFBqYSA-hglE0aXr_0rAZhFaWxM"
TG_CHAT_ID = "6054558214"


def load_env(path):
    """Load key=value pairs from a .env file into os.environ."""
    if not os.path.exists(path):
        print(f"[ERROR] .env file not found: {path}")
        sys.exit(1)
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            os.environ[key] = value


load_env(ENV_PATH)

ACCESS_TOKEN = os.environ.get("THREADS_ACCESS_TOKEN", "")
USER_ID = os.environ.get("THREADS_USER_ID", "")
APP_SECRET = os.environ.get("THREADS_APP_SECRET", "")
APP_ID = os.environ.get("THREADS_APP_ID", "")

if not ACCESS_TOKEN or not USER_ID:
    print("[ERROR] THREADS_ACCESS_TOKEN and THREADS_USER_ID must be set in .env")
    sys.exit(1)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def api_post(url, params):
    """Send a POST request with form-encoded params and return parsed JSON."""
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"[HTTP ERROR {e.code}] {error_body}")
        raise
    except urllib.error.URLError as e:
        print(f"[URL ERROR] {e.reason}")
        raise


def api_get(url):
    """Send a GET request and return parsed JSON."""
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"[HTTP ERROR {e.code}] {error_body}")
        raise
    except urllib.error.URLError as e:
        print(f"[URL ERROR] {e.reason}")
        raise


# ---------------------------------------------------------------------------
# Telegram notification
# ---------------------------------------------------------------------------

def send_tg_notification(message):
    """Send a notification message to Telegram."""
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    params = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        api_post(url, params)
        print("[TG] Notification sent.")
    except Exception as e:
        print(f"[TG WARNING] Failed to send notification: {e}")


# ---------------------------------------------------------------------------
# Threads API functions
# ---------------------------------------------------------------------------

def check_status(container_id):
    """Check the processing status of a media container."""
    url = f"{BASE_URL}/{container_id}?fields=status&access_token={ACCESS_TOKEN}"
    result = api_get(url)
    return result.get("status", "UNKNOWN")


def wait_for_container(container_id, max_wait=30, interval=2):
    """Poll until container status is FINISHED or timeout."""
    elapsed = 0
    while elapsed < max_wait:
        status = check_status(container_id)
        print(f"  Container {container_id} status: {status}")
        if status == "FINISHED":
            return True
        if status == "ERROR":
            print("[ERROR] Container processing failed.")
            return False
        time.sleep(interval)
        elapsed += interval
    print("[ERROR] Timed out waiting for container to finish processing.")
    return False


def create_container(text, media_type="TEXT", image_url=None, reply_to_id=None):
    """Create a media container (step 1)."""
    url = f"{BASE_URL}/{USER_ID}/threads"
    params = {
        "media_type": media_type,
        "text": text,
        "access_token": ACCESS_TOKEN,
    }
    if media_type == "IMAGE" and image_url:
        params["image_url"] = image_url
    if reply_to_id:
        params["reply_to_id"] = reply_to_id

    result = api_post(url, params)
    container_id = result.get("id")
    if not container_id:
        print(f"[ERROR] No container ID returned: {result}")
        return None
    print(f"  Container created: {container_id}")
    return container_id


def publish_container(container_id):
    """Publish a previously created container (step 2)."""
    url = f"{BASE_URL}/{USER_ID}/threads_publish"
    params = {
        "creation_id": container_id,
        "access_token": ACCESS_TOKEN,
    }
    result = api_post(url, params)
    post_id = result.get("id")
    if not post_id:
        print(f"[ERROR] No post ID returned: {result}")
        return None
    return post_id


# ---------------------------------------------------------------------------
# High-level publish functions
# ---------------------------------------------------------------------------

def publish_text(text):
    """Publish a text-only post."""
    print(f"[THREADS] Publishing text post ({len(text)} chars)...")
    container_id = create_container(text, media_type="TEXT")
    if not container_id:
        return None

    post_id = publish_container(container_id)
    if post_id:
        post_url = f"https://www.threads.net/@me/post/{post_id}"
        print(f"[SUCCESS] Post published! ID: {post_id}")
        print(f"  URL: {post_url}")
        send_tg_notification(
            f"<b>Threads post published</b>\n\n"
            f"{text[:200]}{'...' if len(text) > 200 else ''}\n\n"
            f"ID: <code>{post_id}</code>"
        )
        return post_id
    return None


def publish_image(text, image_url):
    """Publish a post with an image."""
    print(f"[THREADS] Publishing image post...")
    print(f"  Image: {image_url}")
    container_id = create_container(text, media_type="IMAGE", image_url=image_url)
    if not container_id:
        return None

    # Wait for image processing
    print("  Waiting for image processing...")
    if not wait_for_container(container_id):
        return None

    post_id = publish_container(container_id)
    if post_id:
        post_url = f"https://www.threads.net/@me/post/{post_id}"
        print(f"[SUCCESS] Image post published! ID: {post_id}")
        print(f"  URL: {post_url}")
        send_tg_notification(
            f"<b>Threads image post published</b>\n\n"
            f"{text[:200]}{'...' if len(text) > 200 else ''}\n\n"
            f"ID: <code>{post_id}</code>"
        )
        return post_id
    return None


def publish_thread(texts):
    """Publish a thread (chain of reply posts)."""
    if not texts or len(texts) < 2:
        print("[ERROR] A thread requires at least 2 posts.")
        return None

    print(f"[THREADS] Publishing thread ({len(texts)} posts)...")
    post_ids = []
    reply_to = None

    for i, text in enumerate(texts):
        print(f"\n  --- Post {i + 1}/{len(texts)} ---")
        container_id = create_container(text, media_type="TEXT", reply_to_id=reply_to)
        if not container_id:
            print(f"[ERROR] Failed to create container for post {i + 1}.")
            return post_ids

        post_id = publish_container(container_id)
        if not post_id:
            print(f"[ERROR] Failed to publish post {i + 1}.")
            return post_ids

        print(f"  Published post {i + 1}: {post_id}")
        post_ids.append(post_id)
        reply_to = post_id

        # Small delay between posts to avoid rate limits
        if i < len(texts) - 1:
            time.sleep(1)

    print(f"\n[SUCCESS] Thread published! {len(post_ids)} posts.")
    for idx, pid in enumerate(post_ids):
        print(f"  Post {idx + 1}: {pid}")

    preview = " | ".join(t[:50] for t in texts)
    send_tg_notification(
        f"<b>Threads thread published ({len(post_ids)} posts)</b>\n\n"
        f"{preview[:300]}{'...' if len(preview) > 300 else ''}\n\n"
        f"First post ID: <code>{post_ids[0]}</code>"
    )
    return post_ids


def refresh_token():
    """Refresh the long-lived access token."""
    print("[THREADS] Refreshing access token...")
    url = (
        f"{BASE_URL}/refresh_access_token"
        f"?grant_type=th_refresh_token"
        f"&access_token={ACCESS_TOKEN}"
    )
    result = api_get(url)
    new_token = result.get("access_token")
    expires_in = result.get("expires_in", 0)

    if not new_token:
        print(f"[ERROR] Token refresh failed: {result}")
        return None

    days = expires_in // 86400
    print(f"[SUCCESS] Token refreshed! Expires in {days} days ({expires_in}s).")
    print(f"  New token (first 20 chars): {new_token[:20]}...")

    # Update .env file
    try:
        with open(ENV_PATH, "r") as f:
            lines = f.readlines()
        with open(ENV_PATH, "w") as f:
            for line in lines:
                if line.strip().startswith("THREADS_ACCESS_TOKEN="):
                    f.write(f"THREADS_ACCESS_TOKEN={new_token}\n")
                else:
                    f.write(line)
        print(f"  Updated {ENV_PATH} with new token.")
    except Exception as e:
        print(f"[WARNING] Could not update .env: {e}")
        print(f"  Manually set THREADS_ACCESS_TOKEN={new_token}")

    send_tg_notification(
        f"<b>Threads token refreshed</b>\n"
        f"Expires in {days} days."
    )
    return new_token


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_usage():
    print("Usage:")
    print('  python3 threads_publisher.py "post text"')
    print('  python3 threads_publisher.py --image "https://url/img.jpg" "caption"')
    print('  python3 threads_publisher.py --thread "post1" "post2" "post3"')
    print("  python3 threads_publisher.py --refresh-token")


def main():
    args = sys.argv[1:]

    if not args:
        print_usage()
        sys.exit(1)

    if args[0] == "--refresh-token":
        refresh_token()

    elif args[0] == "--image":
        if len(args) < 3:
            print("[ERROR] --image requires an image URL and caption text.")
            print('  python3 threads_publisher.py --image "https://url/img.jpg" "caption"')
            sys.exit(1)
        image_url = args[1]
        caption = args[2]
        publish_image(caption, image_url)

    elif args[0] == "--thread":
        texts = args[1:]
        if len(texts) < 2:
            print("[ERROR] --thread requires at least 2 posts.")
            sys.exit(1)
        publish_thread(texts)

    elif args[0].startswith("--"):
        print(f"[ERROR] Unknown option: {args[0]}")
        print_usage()
        sys.exit(1)

    else:
        # Single text post
        text = args[0]
        publish_text(text)


if __name__ == "__main__":
    main()
