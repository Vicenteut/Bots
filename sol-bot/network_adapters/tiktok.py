"""
network_adapters/tiktok.py — TikTok Content Posting API adapter.

Uses PULL_FROM_URL flow: upload MP4 to litterbox, then ask TikTok to fetch.

Env vars:
  TIKTOK_CLIENT_KEY
  TIKTOK_CLIENT_SECRET
  TIKTOK_ACCESS_TOKEN  — obtained via OAuth flow once approved
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

API_BASE = "https://open.tiktokapis.com/v2"
POLL_INTERVAL_SEC = 5
POLL_MAX_TRIES = 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_post_json(url: str, token: str, payload: dict, timeout: int = 60) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={
                                     "Authorization": f"Bearer {token}",
                                     "Content-Type": "application/json; charset=UTF-8",
                                     "User-Agent": "sol-bot/tiktok-adapter",
                                 })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class TikTokAdapter(NetworkAdapter):
    name = "tiktok"
    label = "TikTok"
    handle = "@theclamletter"
    char_limit = 2200  # TikTok caption max ~2200

    def __init__(self):
        self.token = os.getenv("TIKTOK_ACCESS_TOKEN")
        self.client_key = os.getenv("TIKTOK_CLIENT_KEY")
        self.client_secret = os.getenv("TIKTOK_CLIENT_SECRET")

    def is_connected(self) -> bool:
        return bool(self.token)

    def auth_status(self) -> dict[str, Any]:
        if not self.is_connected():
            return {"ok": False, "error": "not_configured: missing TIKTOK_ACCESS_TOKEN",
                    "checked_at": _now_iso()}
        try:
            req = urllib.request.Request(
                f"{API_BASE}/user/info/?fields=open_id,union_id,display_name",
                headers={"Authorization": f"Bearer {self.token}"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return {"ok": True, "error": None, "checked_at": _now_iso(),
                    "username": data.get("data", {}).get("user", {}).get("display_name")}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300], "checked_at": _now_iso()}

    def _upload_to_public_https(self, local_path: str) -> str | None:
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
                    "ts": _now_iso(), "error": "tiktok requires a video file"}

        local = media[0]
        public_url = local if local.startswith("http") else self._upload_to_public_https(local)
        if not public_url:
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": "media upload (litterbox) failed"}

        try:
            init = _http_post_json(
                f"{API_BASE}/post/publish/inbox/video/init/",
                self.token,
                {"source_info": {"source": "PULL_FROM_URL", "video_url": public_url}},
            )
            publish_id = (init.get("data") or {}).get("publish_id")
            if not publish_id:
                return {"ok": False, "network_post_id": None, "permalink": None,
                        "ts": _now_iso(), "error": f"init failed: {init}"}

            final_status = None
            for _ in range(POLL_MAX_TRIES):
                status = _http_post_json(
                    f"{API_BASE}/post/publish/status/fetch/",
                    self.token,
                    {"publish_id": publish_id},
                )
                final_status = (status.get("data") or {}).get("status")
                if final_status == "PUBLISH_COMPLETE":
                    break
                if final_status in {"FAILED", "PUBLISH_FAILED"}:
                    return {"ok": False, "network_post_id": None, "permalink": None,
                            "ts": _now_iso(), "error": f"publish failed: {status}"}
                time.sleep(POLL_INTERVAL_SEC)
            else:
                return {"ok": False, "network_post_id": None, "permalink": None,
                        "ts": _now_iso(),
                        "error": f"publish did not finish (last status: {final_status})"}

            return {"ok": True, "network_post_id": publish_id, "permalink": None,
                    "ts": _now_iso(), "error": None}
        except Exception as exc:
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": str(exc)[:500]}

    def fetch_post_insights(self, network_post_id: str) -> dict[str, Any]:
        return {"error": "not_implemented", "ts": _now_iso()}

    def fetch_followers(self) -> dict[str, Any]:
        return {"count": None, "error": "not_implemented"}
