"""
network_adapters/threads.py — ThreadsAdapter.

Wraps the existing threads_publisher.py + threads_analytics.py modules so the
rest of the system can talk to "a network" instead of "Threads specifically".

This is intentionally thin: it does NOT reimplement Threads logic, it delegates
to the canonical modules so behaviour stays identical to pre-refactor.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .base import NetworkAdapter


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ThreadsAdapter(NetworkAdapter):
    name = "threads"
    label = "Threads"
    handle = "@theclamletter"
    char_limit = 500

    def is_connected(self) -> bool:
        try:
            from threads_analytics import _load_token
        except Exception:
            return False
        return bool(_load_token())

    def auth_status(self) -> dict[str, Any]:
        try:
            from threads_analytics import _load_token, _get, BASE_URL
        except Exception as exc:
            return {"ok": False, "error": f"import: {exc}", "checked_at": _now_iso()}
        token = _load_token()
        if not token:
            return {"ok": False, "error": "no THREADS_ACCESS_TOKEN", "checked_at": _now_iso()}
        try:
            import urllib.parse
            params = urllib.parse.urlencode({"fields": "id,username", "access_token": token})
            data = _get(f"{BASE_URL}/me?{params}")
            uname = data.get("username")
            return {"ok": True, "error": None, "checked_at": _now_iso(), "username": uname}
        except Exception as exc:
            from threads_analytics import _safe_error
            return {"ok": False, "error": _safe_error(exc), "checked_at": _now_iso()}

    def publish(
        self,
        text: str,
        media: list[str] | None = None,
        in_reply_to: str | None = None,
    ) -> dict[str, Any]:
        try:
            import threads_publisher as tp
        except Exception as exc:
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": f"import: {exc}"}
        try:
            if in_reply_to:
                post_id = tp.publish_reply(text, in_reply_to)
            elif media and len(media) == 1:
                post_id = tp.publish_single_image(text, media[0])
            elif media and len(media) > 1:
                post_id = tp.publish_carousel(text, media)
            else:
                post_id = tp.publish_text(text)
        except tp.ThreadsPublishError as exc:
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": f"{exc.category}: {exc.message}"}
        except Exception as exc:
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": str(exc)[:500]}

        if not post_id:
            return {"ok": False, "network_post_id": None, "permalink": None,
                    "ts": _now_iso(), "error": "publish returned no id"}

        permalink = f"https://www.threads.net/@{self.handle.lstrip('@')}/post/{post_id}"
        return {"ok": True, "network_post_id": str(post_id), "permalink": permalink,
                "ts": _now_iso(), "error": None}

    def fetch_post_insights(self, network_post_id: str) -> dict[str, Any]:
        """Pulls live metrics for a single post via Threads insights API."""
        try:
            from threads_analytics import _load_token, _get, BASE_URL, METRICS, _safe_error
            import urllib.parse
        except Exception as exc:
            return {"error": f"import: {exc}", "ts": _now_iso()}
        token = _load_token()
        if not token:
            return {"error": "no token", "ts": _now_iso()}
        metrics = {"views": 0, "likes": 0, "replies": 0, "reposts": 0, "quotes": 0}
        try:
            params = urllib.parse.urlencode({"metric": METRICS, "access_token": token})
            data = _get(f"{BASE_URL}/{network_post_id}/insights?{params}")
            for item in data.get("data", []):
                name = item.get("name")
                if name not in metrics:
                    continue
                tv = item.get("total_value") or {}
                if tv:
                    metrics[name] = int(tv.get("value") or 0)
                elif item.get("values"):
                    metrics[name] = int(item["values"][0].get("value") or 0)
        except Exception as exc:
            return {**metrics, "error": _safe_error(exc), "ts": _now_iso()}
        return {**metrics, "error": None, "ts": _now_iso()}

    def fetch_followers(self) -> dict[str, Any]:
        try:
            from threads_analytics import fetch_followers as _ff
        except Exception as exc:
            return {"count": None, "error": f"import: {exc}"}
        return _ff()

    def cost_estimate(self, action: str) -> float:
        # Threads Graph API is free
        return 0.0
