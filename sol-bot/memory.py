#!/usr/bin/env python3
"""
memory.py — Continuity & context memory for Sol Bot.
Stores recent tweets so Sol doesn't repeat topics and maintains
consistent opinions across posts.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).resolve().parent / "context.json"
DEFAULT_LIMIT = 15


class SolMemory:
    def __init__(self, path: Path = DEFAULT_PATH, limit: int = DEFAULT_LIMIT):
        self.path = Path(path)
        self.limit = limit
        self._entries: list[dict] = []
        self._load()

    # ------------------------------------------------------------------
    # Internal I/O
    # ------------------------------------------------------------------

    def _load(self):
        if self.path.exists():
            try:
                self._entries = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"[memory] Could not load {self.path}: {e}")
                self._entries = []
        else:
            self._entries = []

    def _save(self):
        try:
            self.path.write_text(
                json.dumps(self._entries, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error(f"[memory] Could not save {self.path}: {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_tweet(
        self,
        tweet_text: str,
        tweet_type: str,
        topic_tag: str,
        platform: str = "x",
    ):
        """Append a published tweet to memory, trimming to limit."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "topic_tag": topic_tag.lower().strip(),
            "tweet_text": tweet_text[:280],
            "tweet_type": tweet_type.upper(),
            "platform": platform.lower(),
        }
        self._entries.append(entry)
        # Keep only the most recent N entries
        self._entries = self._entries[-self.limit:]
        self._save()
        logger.info(f"[memory] Saved tweet [{tweet_type}/{topic_tag}]")

    def get_context_block(self, last_n: int = 8) -> str:
        """
        Returns a formatted string of recent tweets for injection into prompt.
        Format: YYYY-MM-DD HH:MM [TYPE/topic]: text...
        """
        recent = self._entries[-last_n:] if self._entries else []
        if not recent:
            return ""

        lines = []
        for e in reversed(recent):  # most recent first
            try:
                ts = datetime.fromisoformat(e["timestamp"])
                ts_str = ts.strftime("%Y-%m-%d %H:%M")
            except (ValueError, KeyError):
                ts_str = "???"
            tweet_type = e.get("tweet_type", "?")
            topic = e.get("topic_tag", "?")
            text = e.get("tweet_text", "")[:120]
            lines.append(f"{ts_str} [{tweet_type}/{topic}]: {text}")

        return "\n".join(lines)

    def get_tags_seen(self, last_n_days: int = 7) -> list[str]:
        """Returns unique topic tags seen in the last N days."""
        cutoff = datetime.now() - timedelta(days=last_n_days)
        tags = set()
        for e in self._entries:
            try:
                ts = datetime.fromisoformat(e["timestamp"])
                if ts >= cutoff:
                    tags.add(e.get("topic_tag", "").lower())
            except (ValueError, KeyError):
                continue
        return list(tags)

    def get_recent_topics(self, hours: int = 12) -> list[str]:
        """Returns topic tags from the last N hours (for deduplication)."""
        cutoff = datetime.now() - timedelta(hours=hours)
        topics = []
        for e in self._entries:
            try:
                ts = datetime.fromisoformat(e["timestamp"])
                if ts >= cutoff:
                    topics.append(e.get("topic_tag", "").lower())
            except (ValueError, KeyError):
                continue
        return topics

    def times_covered(self, topic_tag: str, last_n_days: int = 7) -> int:
        """How many times a topic has been covered in the last N days."""
        cutoff = datetime.now() - timedelta(days=last_n_days)
        count = 0
        for e in self._entries:
            try:
                ts = datetime.fromisoformat(e["timestamp"])
                if ts >= cutoff and e.get("topic_tag", "").lower() == topic_tag.lower():
                    count += 1
            except (ValueError, KeyError):
                continue
        return count

    def build_continuity_prompt(self) -> str:
        """
        Builds the continuity section to inject into the system prompt.
        Returns empty string if no memory exists.
        """
        block = self.get_context_block()
        if not block:
            return ""

        return f"""
Your last published tweets:
{block}

CONTINUITY RULES:
- DO NOT repeat topics from the last 12 hours.
- If following up on a previous topic, reference it naturally: "Update on what I mentioned yesterday..." or "This confirms what I flagged on [day]..."
- Stay consistent in your opinions. Don't contradict a previous take without explaining the change.
- If the same topic appears 3+ times this week, find the angle you haven't covered yet.
- ALWAYS write in English regardless of previous tweet language.
""".strip()


# Singleton for use across modules
_memory_instance: SolMemory | None = None


def get_memory() -> SolMemory:
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = SolMemory()
    return _memory_instance
