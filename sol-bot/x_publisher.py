#!/usr/bin/env python3
"""
x_publisher.py — Publish tweets and threads to X via Twitter API v2 (tweepy).

Usage:
  python3 x_publisher.py [--image path] [--images p1,p2] [--video path] "tweet1" "tweet2" ...

Credentials (from .env):
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET

Exit codes: 0 = success, 1 = fatal error.
"""

import argparse
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

try:
    import tweepy
except ImportError:
    print("[ERROR] tweepy not installed. Run: pip install tweepy", file=sys.stderr)
    sys.exit(1)


def _build_clients():
    api_key    = os.getenv("X_API_KEY")
    api_secret = os.getenv("X_API_SECRET")
    access_tok = os.getenv("X_ACCESS_TOKEN")
    access_sec = os.getenv("X_ACCESS_TOKEN_SECRET")

    missing = [k for k, v in {
        "X_API_KEY": api_key, "X_API_SECRET": api_secret,
        "X_ACCESS_TOKEN": access_tok, "X_ACCESS_TOKEN_SECRET": access_sec,
    }.items() if not v]
    if missing:
        print(f"[ERROR] Missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_tok, access_sec)
    v1_api = tweepy.API(auth, wait_on_rate_limit=True)
    v2_client = tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_tok,
        access_token_secret=access_sec,
    )
    return v1_api, v2_client


def _upload_image(api, path: str) -> str:
    """Upload a single image and return its media_id string."""
    try:
        media = api.media_upload(filename=path)
        return str(media.media_id)
    except Exception as e:
        print(f"[ERROR] Image upload failed for {path}: {e}", file=sys.stderr)
        raise


def _upload_video(api, path: str) -> str:
    """Upload a video (chunked), poll until processing done, return media_id string."""
    file_size = os.path.getsize(path)
    size_mb = file_size / (1024 * 1024)
    print(f"Tamano del video: {size_mb:.1f} MB")

    media = api.media_upload(
        filename=path,
        media_category="tweet_video",
        chunked=True,
    )
    media_id = str(media.media_id)

    # Poll processing status
    print("Esperando procesamiento del video...")
    for _ in range(60):
        status = api.get_media_upload_status(media_id)
        info = getattr(status, "processing_info", None)
        if info is None:
            break
        state = info.get("state", "")
        if state == "succeeded":
            print("Video procesado correctamente.")
            break
        if state == "failed":
            print("[ERROR] Video processing failed.", file=sys.stderr)
            sys.exit(1)
        check_after = info.get("check_after_secs", 3)
        time.sleep(check_after)
    return media_id


def _upload_media(api, image_paths: list, video_path: str) -> list:
    """Return list of media_id strings ready to attach to a tweet (max 4 images or 1 video)."""
    if video_path:
        return [_upload_video(api, video_path)]
    if image_paths:
        ids = []
        for p in image_paths[:4]:
            if not os.path.exists(p):
                print(f"[WARN] Image not found: {p} — skipping", file=sys.stderr)
                continue
            try:
                ids.append(_upload_image(api, p))
                print(f"Imagen subida: {p}")
            except Exception as e:
                print(f"[ERROR] Failed to upload {p}: {e} — skipping", file=sys.stderr)
        if not ids:
            print("[ERROR] All image uploads failed — publishing without media", file=sys.stderr)
        return ids
    return []


def post_thread(tweets: list, image_paths: list, video_path: str):
    api, client = _build_clients()

    # Upload media once (attached to first tweet only)
    media_ids = None
    if image_paths or video_path:
        ids = _upload_media(api, image_paths, video_path)
        if ids:
            media_ids = ids

    last_id = None
    for i, text in enumerate(tweets):
        print(f"Publicando tweet {i + 1}/{len(tweets)}...")

        kwargs = {"text": text}
        if i == 0 and media_ids:
            kwargs["media_ids"] = media_ids
        if last_id is not None:
            kwargs["in_reply_to_tweet_id"] = last_id

        resp = client.create_tweet(**kwargs)
        last_id = resp.data["id"]
        print(f"Tweet {i + 1} publicado. ID: {last_id}")

        if i < len(tweets) - 1:
            time.sleep(3)

    print(f"Listo: {len(tweets)} tweet(s) publicados.")


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--image",  action="append", dest="images", default=[])
    parser.add_argument("--images", dest="images_csv", default=None)
    parser.add_argument("--video",  dest="video", default=None)
    parser.add_argument("tweets",   nargs="*")
    args = parser.parse_args()

    image_paths = list(args.images)
    if args.images_csv:
        image_paths += [p.strip() for p in args.images_csv.split(",") if p.strip()]

    video_path = args.video
    if video_path and not os.path.exists(video_path):
        print(f"[WARN] Video not found: {video_path} — publishing without media")
        video_path = None

    image_paths = [p for p in image_paths if os.path.exists(p) or print(f"[WARN] Image not found: {p} — skipping") is None]
    image_paths = [p for p in image_paths if os.path.exists(p)]

    tweets = args.tweets
    if not tweets:
        print("Usage: python3 x_publisher.py [--image path] [--images p1,p2] [--video path] \"tweet1\" ...", file=sys.stderr)
        sys.exit(1)

    post_thread(tweets, image_paths, video_path)


if __name__ == "__main__":
    try:
        main()
    except tweepy.TweepyException as e:
        print(f"[ERROR] Tweepy error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Fatal: {e}", file=sys.stderr)
        sys.exit(1)
