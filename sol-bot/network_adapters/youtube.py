"""
network_adapters/youtube.py — YouTube Shorts via YouTube Data API v3.

Uses local file upload (no public HTTPS needed). Detects vertical 9:16 ≤60s as Short.

Env vars:
  YOUTUBE_CLIENT_SECRETS_PATH — /root/x-bot/sol-bot/.secrets/youtube_client_secrets.json
  YOUTUBE_TOKEN_PATH          — /root/x-bot/sol-bot/.secrets/youtube_token.json
  YOUTUBE_CHANNEL_ID          — optional, for /channel/{id}/shorts permalink

First-time auth: run `python3 -m network_adapters.youtube --auth` from VPS,
follow URL on a local browser, paste code back.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import NetworkAdapter

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_secrets_path() -> Path:
    return Path(os.getenv("YOUTUBE_CLIENT_SECRETS_PATH",
                          "/root/x-bot/sol-bot/.secrets/youtube_client_secrets.json"))


def _default_token_path() -> Path:
    return Path(os.getenv("YOUTUBE_TOKEN_PATH",
                          "/root/x-bot/sol-bot/.secrets/youtube_token.json"))


def _load_credentials():
    """Load OAuth credentials from disk. Refresh if expired."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_path = _default_token_path()
    if not token_path.exists():
        return None

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
    return creds


def _run_auth_flow():
    """One-time interactive auth flow. Saves token to disk."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    secrets_path = _default_secrets_path()
    if not secrets_path.exists():
        raise FileNotFoundError(
            f"Client secrets not found at {secrets_path}. "
            "Download from Google Cloud Console → OAuth 2.0 Client IDs → Desktop."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
    creds = flow.run_console() if hasattr(flow, "run_console") else flow.run_local_server(port=0)
    token_path = _default_token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    print(f"Saved YouTube token to {token_path}")


class YouTubeAdapter(NetworkAdapter):
    name = "youtube"
    label = "YouTube Shorts"
    handle = "@theclamletter"
    char_limit = 100  # video title; description has 5000

    def __init__(self):
        self.channel_id = os.getenv("YOUTUBE_CHANNEL_ID")

    def _build_service(self):
        from googleapiclient.discovery import build
        creds = _load_credentials()
        if not creds:
            return None
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    def is_connected(self) -> bool:
        try:
            return _load_credentials() is not None
        except Exception:
            return False

    def auth_status(self) -> dict[str, Any]:
        if not _default_token_path().exists():
            return {"ok": False, "error": "not_configured: run network_adapters.youtube --auth first",
                    "checked_at": _now_iso()}
        try:
            yt = self._build_service()
            if not yt:
                return {"ok": False, "error": "credentials missing/expired",
                        "checked_at": _now_iso()}
            me = yt.channels().list(part="snippet", mine=True).execute()
            items = me.get("items") or []
            uname = items[0]["snippet"]["title"] if items else None
            return {"ok": True, "error": None, "checked_at": _now_iso(), "username": uname}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300], "checked_at": _now_iso()}

    def _split_title_description(self, text: str) -> tuple[str, str]:
        """First line → title (≤90 chars + ' #Shorts'); rest → description."""
        first, _, rest = text.partition("\n")
        title = first.strip()
        if len(title) > 88:
            title = title[:85].rstrip() + "…"
        title = f"{title} #Shorts"
        description = (rest.strip() + "\n\n#Shorts #News #Geopolitics").strip()
        return title, description

    def publish(self, text: str, media: list[str] | None = None,
                in_reply_to: str | None = None) -> dict[str, Any]:
        if not media or not media[0]:
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": "youtube shorts require a video file"}
        local = media[0]
        if local.startswith("http"):
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": "youtube adapter requires local path, not URL"}
        if not Path(local).exists():
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": f"file not found: {local}"}

        try:
            from googleapiclient.http import MediaFileUpload
            yt = self._build_service()
            if not yt:
                return {"ok": False, "network_post_id": None, "permalink": None,
                        "ts": _now_iso(), "error": "not_configured: missing youtube token"}

            title, description = self._split_title_description(text)
            request = yt.videos().insert(
                part="snippet,status",
                body={
                    "snippet": {
                        "title": title,
                        "description": description,
                        "tags": ["news", "shorts", "geopolitics", "macro"],
                        "categoryId": "25",  # News & Politics
                    },
                    "status": {
                        "privacyStatus": "public",
                        "selfDeclaredMadeForKids": False,
                    },
                },
                media_body=MediaFileUpload(local, chunksize=-1, resumable=True, mimetype="video/mp4"),
            )
            response = request.execute()
            video_id = response.get("id")
            permalink = f"https://youtube.com/shorts/{video_id}" if video_id else None
            return {"ok": bool(video_id), "network_post_id": video_id, "permalink": permalink,
                    "ts": _now_iso(), "error": None if video_id else f"unexpected: {response}"}
        except Exception as exc:
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": str(exc)[:500]}

    def fetch_post_insights(self, network_post_id: str) -> dict[str, Any]:
        try:
            yt = self._build_service()
            if not yt:
                return {"error": "not_configured", "ts": _now_iso()}
            res = yt.videos().list(part="statistics", id=network_post_id).execute()
            items = res.get("items") or []
            if not items:
                return {"error": "video not found", "ts": _now_iso()}
            stats = items[0].get("statistics", {})
            return {
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "replies": int(stats.get("commentCount", 0)),
                "ts": _now_iso(),
                "error": None,
            }
        except Exception as exc:
            return {"error": str(exc)[:300], "ts": _now_iso()}

    def fetch_followers(self) -> dict[str, Any]:
        try:
            yt = self._build_service()
            if not yt:
                return {"count": None, "error": "not_configured"}
            res = yt.channels().list(part="statistics", mine=True).execute()
            items = res.get("items") or []
            count = int(items[0]["statistics"].get("subscriberCount", 0)) if items else None
            return {"count": count, "error": None}
        except Exception as exc:
            return {"count": None, "error": str(exc)[:300]}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--auth", action="store_true", help="Run interactive OAuth flow")
    args = ap.parse_args()
    if args.auth:
        _run_auth_flow()
    else:
        print(json.dumps(YouTubeAdapter().auth_status(), indent=2))
