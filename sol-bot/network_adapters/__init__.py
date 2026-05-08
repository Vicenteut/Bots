"""
network_adapters — registry of publishing targets.

Usage:
    from network_adapters import NETWORKS, get_adapter

    threads = get_adapter("threads")
    threads.publish("hello world")

    for name, adapter in NETWORKS.items():
        print(name, adapter.is_connected())
"""

from __future__ import annotations

from .base import NetworkAdapter
from .threads import ThreadsAdapter
from .x import XAdapter
from .instagram import InstagramAdapter
from .tiktok import TikTokAdapter
from .youtube import YouTubeAdapter

# Singleton instances. Adapters are cheap and stateless beyond a single call,
# so reusing one instance per network is fine.
_THREADS = ThreadsAdapter()
_X = XAdapter()
_INSTAGRAM = InstagramAdapter()
_TIKTOK = TikTokAdapter()
_YOUTUBE = YouTubeAdapter()

NETWORKS: dict[str, NetworkAdapter] = {
    _THREADS.name: _THREADS,
    _X.name: _X,
    _INSTAGRAM.name: _INSTAGRAM,
    _TIKTOK.name: _TIKTOK,
    _YOUTUBE.name: _YOUTUBE,
}


def get_adapter(name: str) -> NetworkAdapter | None:
    """Return adapter by name, or None if unknown."""
    return NETWORKS.get(name)


def list_networks() -> list[dict]:
    """Lightweight summary of every registered network for /api/networks."""
    out: list[dict] = []
    for name, adapter in NETWORKS.items():
        out.append({
            "name": name,
            "label": adapter.label,
            "handle": adapter.handle,
            "char_limit": adapter.char_limit,
            "connected": adapter.is_connected(),
        })
    return out


__all__ = [
    "NetworkAdapter",
    "ThreadsAdapter",
    "XAdapter",
    "InstagramAdapter",
    "TikTokAdapter",
    "YouTubeAdapter",
    "NETWORKS",
    "get_adapter",
    "list_networks",
]
