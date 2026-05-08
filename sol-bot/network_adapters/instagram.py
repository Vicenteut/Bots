"""
network_adapters/instagram.py — Instagram Reels publisher via Meta Graph API.

Flow (Graph API v18+):
  1. Upload MP4 to a public HTTPS URL (litterbox, 1h TTL — reuses threads_publisher).
  2. POST /{ig-user-id}/media with media_type=REELS, video_url, caption.
  3. Poll /{container_id}?fields=status_code until FINISHED (or fail).
  4. POST /{ig-user-id}/media_publish with creation_id.
  5. GET /{media_id}?fields=permalink.

Env vars:
  IG_BUSINESS_ACCOUNT_ID — numeric IG-User-ID
  IG_ACCESS_TOKEN        — long-lived token with instagram_content_publish

Reports auth_status='not_configured' until both are set.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .base import NetworkAdapter

GRAPH_BASE = "https://graph.instagram.com/v23.0"
POLL_INTERVAL_SEC = 5
POLL_MAX_TRIES = 60  # ~5 min
# IG sometimes returns status_code=ERROR transiently while still processing the
# upload, then later transitions to FINISHED. Bailing on the first ERROR caused
# false negatives where the reel actually published but the DB recorded a fail
# (observed 2026-05-02 with reels CARLSON / b7a37fcabcb94a86 etc). Tolerate up
# to N consecutive ERROR responses before treating the container as truly broken.
MAX_CONSECUTIVE_ERRORS = 6  # ~30s of persistent ERROR before bailing


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_get(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "sol-bot/instagram-adapter"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post(url: str, params: dict, timeout: int = 60) -> dict:
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"User-Agent": "sol-bot/instagram-adapter"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class InstagramAdapter(NetworkAdapter):
    name = "instagram"
    label = "Instagram Reels"
    handle = "@theclamletter"
    char_limit = 2200  # IG caption limit

    def __init__(self):
        self.ig_user_id = os.getenv("IG_BUSINESS_ACCOUNT_ID")
        self.token = os.getenv("IG_ACCESS_TOKEN")

    def is_connected(self) -> bool:
        return bool(self.ig_user_id and self.token)

    def auth_status(self) -> dict[str, Any]:
        if not self.is_connected():
            return {"ok": False, "error": "not_configured: missing IG_BUSINESS_ACCOUNT_ID / IG_ACCESS_TOKEN",
                    "checked_at": _now_iso()}
        try:
            url = f"{GRAPH_BASE}/{self.ig_user_id}?fields=username&access_token={self.token}"
            data = _http_get(url)
            return {"ok": True, "error": None, "checked_at": _now_iso(), "username": data.get("username")}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300], "checked_at": _now_iso()}

    def _upload_to_public_https(self, local_path: str) -> str | None:
        """Convert a local /root/x-bot/sol-bot/media/<file> path to the
        public Cloudflare-fronted URL. The Cloudflare Access bypass policy
        on /media/* means Meta's IG API can fetch the MP4 directly, with
        no third-party file host in the loop.

        Falls back to litterbox if the file is not under the media dir
        (e.g. arbitrary paths from CLI tests).
        """
        import os
        media_root = "/root/x-bot/sol-bot/media"
        public_base = os.getenv("REELS_PUBLIC_BASE", "https://sol.theclamletter.com/media")
        try:
            real = os.path.realpath(local_path)
            if real.startswith(media_root + "/"):
                filename = os.path.basename(real)
                return f"{public_base}/{filename}"
        except Exception:
            pass
        # Fallback (rare path): try litterbox
        from threads_publisher import upload_file_to_litterbox
        return upload_file_to_litterbox(local_path, duration="1h",
                                        content_type="video/mp4", label="reel")

    def publish(self, text: str, media: list[str] | None = None,
                in_reply_to: str | None = None) -> dict[str, Any]:
        if not self.is_connected():
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": "not_configured"}
        if not media or not media[0]:
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": "instagram reels require a video file"}
        local = media[0]
        public_url = local if local.startswith("http") else self._upload_to_public_https(local)
        if not public_url:
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": "media upload (litterbox) failed"}

        try:
            container = _http_post(f"{GRAPH_BASE}/{self.ig_user_id}/media", {
                "media_type": "REELS",
                "video_url": public_url,
                "caption": text[: self.char_limit],
                "share_to_feed": "true",
                "access_token": self.token,
            })
            container_id = container.get("id")
            if not container_id:
                return {"ok": False, "network_post_id": None, "permalink": None,
                        "ts": _now_iso(), "error": f"container failed: {container}"}

            consecutive_errors = 0
            last_error_status: dict | None = None
            for _ in range(POLL_MAX_TRIES):
                status = _http_get(
                    f"{GRAPH_BASE}/{container_id}?fields=status_code&access_token={self.token}"
                )
                code = status.get("status_code")
                if code == "FINISHED":
                    break
                if code == "EXPIRED":
                    # Final state — no point retrying.
                    return {"ok": False, "network_post_id": None, "permalink": None,
                            "ts": _now_iso(), "error": f"container EXPIRED: {status}"}
                if code == "ERROR":
                    consecutive_errors += 1
                    last_error_status = status
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        return {"ok": False, "network_post_id": None, "permalink": None,
                                "ts": _now_iso(),
                                "error": f"container ERROR persisted {consecutive_errors}x: {last_error_status}"}
                else:
                    # IN_PROGRESS / PUBLISHED / etc — reset transient error counter
                    consecutive_errors = 0
                time.sleep(POLL_INTERVAL_SEC)
            else:
                return {"ok": False, "network_post_id": None, "permalink": None,
                        "ts": _now_iso(), "error": "container did not finish within 5min"}

            published = _http_post(f"{GRAPH_BASE}/{self.ig_user_id}/media_publish", {
                "creation_id": container_id,
                "access_token": self.token,
            })
            media_id = published.get("id")
            if not media_id:
                return {"ok": False, "network_post_id": None, "permalink": None,
                        "ts": _now_iso(), "error": f"publish failed: {published}"}

            permalink = None
            try:
                meta = _http_get(f"{GRAPH_BASE}/{media_id}?fields=permalink&access_token={self.token}")
                permalink = meta.get("permalink")
            except Exception:
                pass

            return {"ok": True, "network_post_id": media_id, "permalink": permalink,
                    "ts": _now_iso(), "error": None}
        except Exception as exc:
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": str(exc)[:500]}

    def fetch_post_insights(self, network_post_id: str) -> dict[str, Any]:
        if not self.is_connected():
            return {"error": "not_configured"}
        try:
            url = (f"{GRAPH_BASE}/{network_post_id}/insights"
                   f"?metric=plays,likes,comments,shares,reach&access_token={self.token}")
            data = _http_get(url)
            out: dict[str, Any] = {"ts": _now_iso(), "error": None}
            for entry in data.get("data", []):
                name = entry.get("name")
                values = entry.get("values") or [{}]
                out[name] = values[0].get("value")
            return out
        except Exception as exc:
            return {"error": str(exc)[:300], "ts": _now_iso()}

    def fetch_followers(self) -> dict[str, Any]:
        if not self.is_connected():
            return {"count": None, "error": "not_configured"}
        try:
            url = f"{GRAPH_BASE}/{self.ig_user_id}?fields=followers_count&access_token={self.token}"
            data = _http_get(url)
            return {"count": data.get("followers_count"), "error": None}
        except Exception as exc:
            return {"count": None, "error": str(exc)[:300]}
