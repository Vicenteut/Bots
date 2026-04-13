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
    """Publish to X using x_publisher.py via Tweepy."""
    cmd = ["python3", os.path.join(BOT_DIR, "x_publisher.py")]

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


def publish_threads(tweets, image_path=None, is_video=False, video_path=None):
    """Publish to Threads using threads_publisher.py."""
    cmd = ["python3", os.path.join(BOT_DIR, "threads_publisher.py")]

    # Always attach media first if present
    if video_path and not is_video:
        is_video = True

    if is_video and video_path:
        cmd.extend(["--video", video_path])
    elif image_path and not is_video:
        if not image_path.startswith("http"):
            print(f"[INFO] Passing local image to Threads publisher (self-hosted URL): {image_path}")
        cmd.extend(["--image", image_path])

    # Then add thread flag and tweets
    if len(tweets) > 1:
        cmd.append("--thread")
        cmd.extend(tweets)
    else:
        cmd.append(tweets[0])

    print(f"[THREADS] Publishing {len(tweets)} post(s) media={'image' if image_path else 'video' if is_video else 'none'}...")
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
        print("Usage: python3 publish_dual.py [--x-only] [--threads-only] [--image path] [--video path] [--thread] \"text\" ...")
        sys.exit(1)

    image_path = None
    video_path = None
    is_thread = False
    x_only = False
    threads_only = False
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
        elif args[i] == "--x-only":
            x_only = True
            i += 1
        elif args[i] == "--threads-only":
            threads_only = True
            i += 1
        else:
            tweets.append(args[i])
            i += 1

    if not tweets:
        print("[ERROR] No tweet text provided")
        sys.exit(1)

    x_ok = None
    threads_ok = None

    if not threads_only:
        x_ok = publish_x(tweets, image_path=image_path, video_path=video_path)

    if not x_only:
        is_video = video_path is not None
        threads_ok = publish_threads(tweets, image_path=image_path, is_video=is_video, video_path=video_path)

    # Summary
    x_status      = ("OK" if x_ok      else "FAILED") if x_ok      is not None else "N/A"
    threads_status = ("OK" if threads_ok else "FAILED") if threads_ok is not None else "N/A"

    summary = f"X: {x_status} | Threads: {threads_status}"
    if video_path and not x_only:
        summary += " (solo texto en Threads)"

    print(f"\n[RESULT] {summary}")

    # Notify via Telegram
    if x_only:
        tg_msg = f"Publicado en X: {'OK' if x_ok else 'FALLO'}"
    elif threads_only:
        tg_msg = f"Publicado en Threads: {'OK' if threads_ok else 'FALLO'}"
    else:
        tg_msg = f"Publicacion dual:\n- X: {'Publicado' if x_ok else 'FALLO'}\n- Threads: {'Publicado' if threads_ok else 'FALLO'}"
        if video_path:
            tg_msg += "\n(Video solo en X, texto en Threads)"

    try:
        send_message(tg_msg)
    except Exception:
        print("[WARN] Telegram notification failed")

    active = [r for r in [x_ok, threads_ok] if r is not None]
    sys.exit(0 if all(active) else 1)


if __name__ == "__main__":
    main()
