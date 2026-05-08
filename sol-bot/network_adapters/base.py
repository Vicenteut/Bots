"""
network_adapters/base.py — abstract NetworkAdapter interface.

Every social network we publish to (Threads, X, future LinkedIn/Bluesky) implements
this interface. Adapters are in-process, stateless beyond a single call.

Sprint 1 (foundation): only ThreadsAdapter is functional. XAdapter is a skeleton
that reports `not_configured` until Sprint 2 wires real X API credentials.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class NetworkAdapter(ABC):
    """Abstract base for a publishing target."""

    name: str = ""        # short id: "threads" | "x" | "linkedin" | "bluesky"
    label: str = ""       # human label: "Threads" | "X" | "LinkedIn" | "Bluesky"
    handle: str = ""      # account handle: "@theclamletter", "@inequaliti", ...
    char_limit: int = 0   # max post length in chars (0 = unlimited)

    @abstractmethod
    def is_connected(self) -> bool:
        """Quick check: do we have credentials for this network?"""
        ...

    @abstractmethod
    def auth_status(self) -> dict[str, Any]:
        """
        Detailed auth check. Returns:
            {"ok": bool, "error": str | None, "checked_at": iso_timestamp}
        """
        ...

    @abstractmethod
    def publish(
        self,
        text: str,
        media: list[str] | None = None,
        in_reply_to: str | None = None,
    ) -> dict[str, Any]:
        """
        Publish a post. Returns:
            {
                "ok": bool,
                "network_post_id": str | None,
                "permalink": str | None,
                "ts": iso_timestamp,
                "error": str | None,
            }
        """
        ...

    @abstractmethod
    def fetch_post_insights(self, network_post_id: str) -> dict[str, Any]:
        """
        Returns: {"views", "likes", "replies", "reposts", "quotes", "ts", "error"}
        """
        ...

    @abstractmethod
    def fetch_followers(self) -> dict[str, Any]:
        """Returns: {"count": int | None, "error": str | None}"""
        ...

    def cost_estimate(self, action: str) -> float:
        """USD cost per action. Override in adapters that have per-call billing."""
        return 0.0
