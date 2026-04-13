"""Shared topic classification helpers for Sol analytics."""
from __future__ import annotations

_TOPIC_KEYWORDS = {
    "crypto": [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "token", "stablecoin",
        "blockchain", "solana", "binance", "coinbase", "defi", "etf",
    ],
    "mercados": [
        "market", "markets", "stocks", "s&p", "nasdaq", "dow", "fed", "rates",
        "inflation", "cpi", "gdp", "treasury", "bond", "bonds", "oil", "gold",
        "dollar", "earnings", "recession", "liquidity", "yields", "wall street",
    ],
    "geopolitica": [
        "iran", "israel", "china", "russia", "ukraine", "nato", "war", "military",
        "sanctions", "tariff", "tariffs", "ceasefire", "hezbollah", "gaza", "taiwan",
        "strat", "hormuz", "brics", "eu", "un", "trump", "biden", "putin",
    ],
}


def classify_topic(text: str | None) -> str:
    """Return Sol's broad topic tag for a post-like text."""
    haystack = (text or "").lower()
    if not haystack.strip():
        return "general"

    scores = {
        topic: sum(1 for keyword in keywords if keyword in haystack)
        for topic, keywords in _TOPIC_KEYWORDS.items()
    }
    topic, score = max(scores.items(), key=lambda item: item[1])
    return topic if score > 0 else "general"
