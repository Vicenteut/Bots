#!/usr/bin/env python3
"""
gdrive_upload.py - Upload v3 reels (MP4 + auto-generated .txt) to Google Drive
                   via rclone, after rendering. Used by news_to_reel.render_reel().

Reads:
    GDRIVE_REELS_FOLDER_ID env var (target Drive folder)
    DRIVE_UPLOAD_ENABLED env var (default "true", set "false" to skip)

Failures are NON-BLOCKING. If Drive is unreachable, reel still saves locally + DB.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

GDRIVE_REMOTE = "gdrive:"
DEFAULT_FOLDER_ID = "1CwsTyYECghK7UM2mLTAFDSv8XxzvP1Wu"


def _gdrive_folder_id() -> str:
    return os.environ.get("GDRIVE_REELS_FOLDER_ID", DEFAULT_FOLDER_ID)


def _slug(text: str, max_len: int = 40) -> str:
    """Filesystem-safe slug from text."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", text.lower()[:max_len * 2])
    return cleaned.strip("_")[:max_len]


def _platform_hashtags(topic_tag: str, raw_hashtags: list[str]) -> dict:
    """Build platform-specific hashtag sets from a base list + topic.
    Returns {'youtube': '...', 'instagram': '...', 'tiktok': '...', 'threads': '...', 'x': '...'}.
    """
    base = [h.lstrip("#") for h in raw_hashtags]
    if not base:
        # Fallback: derive from topic
        topic_map = {
            "politica": ["breaking", "geopolitics", "news"],
            "mercados": ["markets", "finance", "news"],
            "crypto": ["crypto", "bitcoin", "news"],
            "general": ["news", "breaking"],
        }
        base = topic_map.get(topic_tag or "general", ["news"])

    return {
        "youtube": " ".join(f"#{h}" for h in base[:5]),
        "instagram": " ".join(f"#{h}" for h in base[:10]),
        "tiktok": " ".join(f"#{h}" for h in (base[:3] + ["fyp"])),
        "threads": " ".join(f"#{h}" for h in base[:2]),
        "x": " ".join(f"#{h}" for h in base[:1]),
    }


def _generate_txt_metadata(reel_id: str, copy: dict, format_version: str = "v3_hyperframes") -> str:
    """Build the companion .txt for manual platform uploads (TikTok, etc.)."""
    hook = copy.get("hook", "")
    caption = copy.get("caption", "")
    topic = copy.get("topic_tag", "")
    label = copy.get("label", "")

    raw_hashtags = re.findall(r"#\w+", caption)
    platform_tags = _platform_hashtags(topic, raw_hashtags)

    bar = "=" * 63

    return f"""{bar}
  TITLE
{bar}

{hook}


{bar}
  DESCRIPTION (caption)
{bar}

{caption}


{bar}
  HASHTAGS (per platform)
{bar}

YouTube Shorts:
{platform_tags['youtube']}

Instagram Reels (10):
{platform_tags['instagram']}

TikTok (3 + #fyp):
{platform_tags['tiktok']}

Threads (2):
{platform_tags['threads']}

X / Twitter (1):
{platform_tags['x']}


{bar}
  METADATA
{bar}

Reel ID:        {reel_id}
Format:         {format_version}
Topic:          {topic}
Label:          {label}
Generated:      {datetime.now(timezone.utc).isoformat()}
Stat 1:         {copy.get('stat1', '')}
Stat 2:         {copy.get('stat2', '')}
Stat 3:         {copy.get('stat3', '')}
"""


def upload_reel_to_drive(reel_id: str, mp4_path: Path, copy: dict, format_version: str = "v3_hyperframes") -> dict:
    """Upload MP4 + auto-generated .txt to Google Drive. Returns dict with status and target filenames.

    Failures are caught and returned as {"status": "failed", "error": ...}.
    Does NOT raise (caller should never have its render flow broken by Drive issues).
    """
    if os.environ.get("DRIVE_UPLOAD_ENABLED", "true").lower() in {"false", "0", "no"}:
        return {"status": "disabled"}

    try:
        if not mp4_path.exists():
            return {"status": "failed", "error": f"MP4 not found: {mp4_path}"}

        topic = copy.get("topic_tag", "general") or "general"
        hook_slug = _slug(copy.get("hook", "reel"), max_len=50)
        friendly = f"{topic}_{hook_slug}_{reel_id[:8]}"

        # Write the companion .txt next to the MP4 (also keeps it local for reference)
        txt_path = mp4_path.parent / f"{friendly}.txt"
        txt_path.write_text(
            _generate_txt_metadata(reel_id, copy, format_version=format_version),
            encoding="utf-8",
        )

        folder_id = _gdrive_folder_id()
        mp4_target = f"{friendly}.mp4"
        txt_target = f"{friendly}.txt"

        # Upload both via rclone copyto (renames at destination)
        for src, target in [(mp4_path, mp4_target), (txt_path, txt_target)]:
            cmd = [
                "rclone", "copyto", str(src),
                f"{GDRIVE_REMOTE}{target}",
                f"--drive-root-folder-id={folder_id}",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode != 0:
                logger.warning(
                    "rclone failed for %s: stderr=%s", src.name, result.stderr[-500:]
                )
                return {
                    "status": "failed",
                    "error": f"rclone exit {result.returncode}: {result.stderr[-200:]}",
                }

        logger.info("Uploaded to Drive: %s + %s", mp4_target, txt_target)
        return {
            "status": "uploaded",
            "mp4_filename": mp4_target,
            "txt_filename": txt_target,
            "local_txt_path": str(txt_path),
        }

    except Exception as exc:
        logger.warning("Drive upload exception (non-blocking): %s", exc)
        return {"status": "failed", "error": str(exc)}
