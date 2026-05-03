#!/usr/bin/env python3
"""
publish_dual.py — Publish to X and Threads simultaneously.

Usage:
    python3 publish_dual.py "tweet text"
    python3 publish_dual.py --image /path/to/img.jpg "tweet text"
    python3 publish_dual.py --video /path/to/video.mp4 "tweet text"
    python3 publish_dual.py --thread "tweet1" "tweet2" "tweet3"
    python3 publish_dual.py --thread --image /path/to/img.jpg "tweet1" "tweet2" "tweet3"

Rules:
    - Text: X + Threads
    - Image: X + Threads (image URL from Unsplash or hosted)
    - Video: X with video, Threads text only
    - Thread: X thread + Threads thread
"""

import os
import subprocess
import sys

from config import load_environment
from telegram_client import send_message

load_environment()

BOT_DIR = os.path.dirname(os.path.abspath(__file__))


def publish_x(tweets, image_path=None, video_path=None):
    """Publish to X using post_thread.js via Puppeteer."""
    cmd = ["node", os.path.join(BOT_DIR, "post_thread.js")]

    if image_path:
        cmd.extend(["--image", image_path])
    elif video_path:
        cmd.extend(["--video", video_path])

    cmd.extend(tweets)

    print(f"[X] Publishing {len(tweets)} tweet(s)...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=BOT_DIR)
        print(result.stdout)
        if result.returncode != 0:
            print(f"[X] ERROR: {result.stderr}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("[X] ERROR: Timeout after 3 minutes")
        return False
    except Exception as e:
        print(f"[X] ERROR: {e}")
        return False


def publish_threads(tweets, image_path=None, is_video=False):
    """Publish to Threads using threads_publisher.py."""
    cmd = ["python3", os.path.join(BOT_DIR, "threads_publisher.py")]

    if len(tweets) > 1:
        cmd.append("--thread")
        cmd.extend(tweets)
    elif image_path and not is_video:
        # Threads API needs a public URL for images, not local files
        # If image is local (from Unsplash download), publish text only
        if image_path.startswith("http"):
            cmd.extend(["--image", image_path, tweets[0]])
        else:
            # Local image — just publish text on Threads
            cmd.append(tweets[0])
    else:
        cmd.append(tweets[0])

    print(f"[THREADS] Publishing {len(tweets)} post(s)...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=BOT_DIR)
        print(result.stdout)
        if result.returncode != 0:
            print(f"[THREADS] ERROR: {result.stderr}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("[THREADS] ERROR: Timeout after 60 seconds")
        return False
    except Exception as e:
        print(f"[THREADS] ERROR: {e}")
        return False


def main():
    args = sys.argv[1:]

    if not args:
        print("Usage: python3 publish_dual.py [--image path] [--video path] [--thread] \"text\" ...")
        sys.exit(1)

    image_path = None
    video_path = None
    is_thread = False
    tweets = []

    i = 0
    while i < len(args):
        if args[i] == "--image" and i + 1 < len(args):
            image_path = args[i + 1]
            i += 2
        elif args[i] == "--video" and i + 1 < len(args):
            video_path = args[i + 1]
            i += 2
        elif args[i] == "--thread":
            is_thread = True
            i += 1
        else:
            tweets.append(args[i])
            i += 1

    if not tweets:
        print("[ERROR] No tweet text provided")
        sys.exit(1)

    # Publish to X (always with all media)
    x_ok = publish_x(tweets, image_path=image_path, video_path=video_path)

    # Publish to Threads (no video, text only for videos)
    is_video = video_path is not None
    threads_ok = publish_threads(tweets, image_path=image_path, is_video=is_video)

    # Summary
    x_status = "OK" if x_ok else "FAILED"
    threads_status = "OK" if threads_ok else "FAILED"

    summary = f"X: {x_status} | Threads: {threads_status}"
    if is_video:
        summary += " (solo texto en Threads)"

    print(f"\n[RESULT] {summary}")

    # Notify via Telegram
    tg_msg = f"Publicacion dual:\n- X: {'Publicado' if x_ok else 'FALLO'}\n- Threads: {'Publicado' if threads_ok else 'FALLO'}"
    if is_video:
        tg_msg += "\n(Video solo en X, texto en Threads)"

    try:
        send_message(tg_msg)
    except Exception:
        print("[WARN] Telegram notification failed")

    sys.exit(0 if (x_ok and threads_ok) else 1)


if __name__ == "__main__":
    main()
