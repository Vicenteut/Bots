#!/usr/bin/env python3
"""
image_manager.py — Custom image manager for X Bot (@napoleotics)

Manages custom images sent via Telegram, with tag-based matching
to pair images with tweet headlines. Falls back to Unsplash via
image_fetcher.py when no custom image matches.

Paths:
  - Images stored in: /root/x-bot/images/custom/
  - Metadata JSON:    /root/x-bot/images/custom_images.json

Usage (CLI):
  python image_manager.py save <path> <tags,comma,separated> [description]
  python image_manager.py find "headline text"
  python image_manager.py list
  python image_manager.py delete <filename>

Usage (import):
  from image_manager import get_image_for_tweet, save_custom_image
"""

import os
import sys
import json
import shutil
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path("/root/x-bot")
IMAGES_DIR = BASE_DIR / "images" / "custom"
METADATA_FILE = BASE_DIR / "images" / "custom_images.json"

load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("image_manager")

# ---------------------------------------------------------------------------
# Keyword map — mirrors the one in image_fetcher.py
# Keep these in sync; add entries here when you add them there.
# ---------------------------------------------------------------------------

KEYWORD_MAP = {
    # Crypto
    "bitcoin":    ["bitcoin", "btc", "crypto", "halving", "mining"],
    "ethereum":   ["ethereum", "eth", "defi", "smart contract", "layer 2"],
    "crypto":     ["crypto", "token", "blockchain", "altcoin", "web3",
                   "stablecoin", "nft", "exchange", "binance", "coinbase"],
    # Geopolitics
    "war":        ["war", "conflict", "military", "troops", "invasion",
                   "missile", "drone", "ceasefire", "weapons", "nato"],
    "russia":     ["russia", "putin", "moscow", "kremlin", "russian"],
    "ukraine":    ["ukraine", "kyiv", "zelensky", "ukrainian"],
    "china":      ["china", "beijing", "xi jinping", "chinese", "ccp",
                   "taiwan", "south china sea"],
    "iran":       ["iran", "tehran", "iranian", "ayatollah", "hezbollah",
                   "houthi"],
    "israel":     ["israel", "netanyahu", "idf", "gaza", "hamas",
                   "west bank", "tel aviv"],
    "brics":      ["brics", "de-dollarization", "dedollarization",
                   "new development bank"],
    # Finance / Economy
    "economy":    ["economy", "gdp", "recession", "inflation", "deflation",
                   "interest rate", "employment", "jobs", "cpi"],
    "fed":        ["fed", "federal reserve", "powell", "rate hike",
                   "rate cut", "fomc", "monetary policy"],
    "markets":    ["market", "stock", "wall street", "s&p", "nasdaq",
                   "dow jones", "rally", "crash", "bear", "bull"],
    "gold":       ["gold", "silver", "precious metals", "commodities",
                   "xau"],
    "oil":        ["oil", "opec", "crude", "barrel", "petroleum",
                   "energy", "natural gas"],
    "dollar":     ["dollar", "usd", "currency", "forex", "yuan", "euro",
                   "yen", "peso"],
    "sanctions":  ["sanctions", "embargo", "blacklist", "tariff", "trade war",
                   "ban"],
    # Politics
    "trump":      ["trump", "maga", "republican", "gop"],
    "biden":      ["biden", "democrat", "white house"],
    "election":   ["election", "vote", "ballot", "poll", "campaign"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_dirs():
    """Create image dirs and metadata file if they don't exist."""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    if not METADATA_FILE.exists():
        METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        METADATA_FILE.write_text("[]", encoding="utf-8")


def _load_metadata() -> list[dict]:
    _ensure_dirs()
    try:
        data = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _save_metadata(entries: list[dict]):
    _ensure_dirs()
    METADATA_FILE.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def extract_keywords(text: str) -> set[str]:
    """Extract matching keywords from text using KEYWORD_MAP.

    Returns the set of *category* names whose trigger words appear in the
    lowercased text.  This is the same logic image_fetcher.py uses.
    """
    text_lower = text.lower()
    matched = set()
    for category, triggers in KEYWORD_MAP.items():
        for trigger in triggers:
            if trigger in text_lower:
                matched.add(category)
                break  # one hit per category is enough
    return matched


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def save_custom_image(
    file_path: str,
    tags: list[str],
    description: str = "",
) -> dict:
    """Copy an image to the custom images directory and register metadata.

    Args:
        file_path: Absolute or relative path to the source image.
        tags: List of keyword tags (e.g. ["bitcoin", "crypto", "markets"]).
        description: Optional human-readable description.

    Returns:
        The metadata dict that was stored.
    """
    _ensure_dirs()
    src = Path(file_path)
    if not src.exists():
        raise FileNotFoundError(f"Source image not found: {file_path}")

    # Unique filename: timestamp + original name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_name = f"{timestamp}_{src.name}"
    dest = IMAGES_DIR / dest_name

    shutil.copy2(src, dest)
    logger.info("Saved image to %s", dest)

    # Normalise tags to lowercase
    tags = [t.strip().lower() for t in tags if t.strip()]

    entry = {
        "filename": dest_name,
        "tags": tags,
        "description": description,
        "date_added": datetime.now().isoformat(),
    }

    entries = _load_metadata()
    entries.append(entry)
    _save_metadata(entries)

    logger.info("Metadata saved (%d tags: %s)", len(tags), ", ".join(tags))
    return entry


def find_best_image(headline_text: str) -> str | None:
    """Find the best matching custom image for a headline.

    Extracts keyword categories from *headline_text* and from each image's
    tags, then scores by overlap count.  Returns the absolute path to the
    best match, or None if nothing matches.
    """
    headline_keywords = extract_keywords(headline_text)
    if not headline_keywords:
        logger.debug("No keywords extracted from headline.")
        return None

    entries = _load_metadata()
    if not entries:
        return None

    best_score = 0
    best_entry = None

    for entry in entries:
        image_tags = set(t.lower() for t in entry.get("tags", []))
        # Tags can be category names OR raw trigger words; check both.
        # 1) Direct overlap between image tags and headline categories
        score = len(image_tags & headline_keywords)
        # 2) Also check if any image tag appears as a substring in headline
        headline_lower = headline_text.lower()
        for tag in image_tags:
            if tag in headline_lower and tag not in headline_keywords:
                score += 0.5  # partial credit for raw keyword match

        if score > best_score:
            best_score = score
            best_entry = entry

    if best_entry and best_score > 0:
        path = str(IMAGES_DIR / best_entry["filename"])
        logger.info(
            "Best custom image: %s (score=%.1f, tags=%s)",
            best_entry["filename"],
            best_score,
            best_entry["tags"],
        )
        return path

    logger.debug("No custom image matched headline keywords: %s", headline_keywords)
    return None


def list_images() -> list[dict]:
    """Return all stored custom images with their metadata."""
    entries = _load_metadata()
    for entry in entries:
        entry["path"] = str(IMAGES_DIR / entry["filename"])
        entry["exists"] = (IMAGES_DIR / entry["filename"]).exists()
    return entries


def delete_image(filename: str) -> bool:
    """Remove an image file and its metadata entry.

    Args:
        filename: Just the filename (not the full path).

    Returns:
        True if the image was found and removed, False otherwise.
    """
    entries = _load_metadata()
    new_entries = [e for e in entries if e["filename"] != filename]

    if len(new_entries) == len(entries):
        logger.warning("Image not found in metadata: %s", filename)
        return False

    # Delete the file
    image_path = IMAGES_DIR / filename
    if image_path.exists():
        image_path.unlink()
        logger.info("Deleted file: %s", image_path)
    else:
        logger.warning("File already missing: %s", image_path)

    _save_metadata(new_entries)
    logger.info("Metadata entry removed for: %s", filename)
    return True


# ---------------------------------------------------------------------------
# Integration: unified image getter
# ---------------------------------------------------------------------------

def get_image_for_tweet(
    headline_text: str,
    output_name: str = "tweet_image.jpg",
) -> str | None:
    """Get the best image for a tweet headline.

    1. Check custom images for a tag-based match.
    2. Fall back to Unsplash via image_fetcher.fetch_image().

    Args:
        headline_text: The headline / tweet text to match against.
        output_name: Filename for the output image (used by Unsplash fallback).

    Returns:
        Absolute path to the image, or None if nothing was found.
    """
    # --- Try custom images first ---
    custom_path = find_best_image(headline_text)
    if custom_path and Path(custom_path).exists():
        logger.info("Using custom image: %s", custom_path)
        return custom_path

    # --- Fall back to Unsplash ---
    try:
        from image_fetcher import fetch_image  # type: ignore

        unsplash_path = fetch_image(headline_text, output_name=output_name)
        if unsplash_path:
            logger.info("Using Unsplash image: %s", unsplash_path)
            return unsplash_path
    except ImportError:
        logger.warning(
            "image_fetcher module not found; Unsplash fallback unavailable."
        )
    except Exception as exc:
        logger.error("Unsplash fallback failed: %s", exc)

    logger.warning("No image found for headline: %s", headline_text[:80])
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli():
    if len(sys.argv) < 2:
        _usage()
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "save":
        if len(sys.argv) < 4:
            print("Usage: python image_manager.py save <path> <tags,comma,separated> [description]")
            sys.exit(1)
        file_path = sys.argv[2]
        tags = [t.strip() for t in sys.argv[3].split(",")]
        description = sys.argv[4] if len(sys.argv) > 4 else ""
        entry = save_custom_image(file_path, tags, description)
        print(f"Saved: {entry['filename']}")
        print(f"Tags:  {', '.join(entry['tags'])}")

    elif command == "find":
        if len(sys.argv) < 3:
            print("Usage: python image_manager.py find \"headline text\"")
            sys.exit(1)
        headline = sys.argv[2]
        result = find_best_image(headline)
        if result:
            print(f"Best match: {result}")
        else:
            print("No matching custom image found.")

    elif command == "list":
        images = list_images()
        if not images:
            print("No custom images stored.")
        else:
            print(f"{'Filename':<40} {'Tags':<35} {'Exists':<7} Description")
            print("-" * 100)
            for img in images:
                tags_str = ", ".join(img["tags"])
                exists = "yes" if img["exists"] else "MISSING"
                desc = img.get("description", "")[:30]
                print(f"{img['filename']:<40} {tags_str:<35} {exists:<7} {desc}")

    elif command == "delete":
        if len(sys.argv) < 3:
            print("Usage: python image_manager.py delete <filename>")
            sys.exit(1)
        filename = sys.argv[2]
        if delete_image(filename):
            print(f"Deleted: {filename}")
        else:
            print(f"Not found: {filename}")

    else:
        _usage()
        sys.exit(1)


def _usage():
    print("image_manager.py — Custom image manager for X Bot")
    print()
    print("Commands:")
    print("  save   <path> <tags,comma,separated> [description]")
    print("  find   \"headline text\"")
    print("  list")
    print("  delete <filename>")


if __name__ == "__main__":
    _cli()
