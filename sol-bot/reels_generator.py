#!/usr/bin/env python3
"""
reels_generator.py , v3 copy generator for The Clam Letter reels.

Produces label + hook + 3 humanized stats + tts narration text + caption,
designed for the Hyperframes data-card-5beat format.

Reuses generator.py for client setup, topic detection, and memory continuity
to keep DB analytics consistent across v2 and v3.

Output schema (compatible with v2 reels table , extra fields added):
    {
      # NEW v3 fields:
      "stat1": str,             # ≤80 chars, humanized fact
      "stat2": str,             # ≤80 chars
      "stat3": str,             # ≤80 chars
      "tts_text": str,          # ~30 words = ~12s narration

      # v2-compatible fields (so DB row + dashboard render stays valid):
      "hook": str,              # ≤80 chars (the headline shown on screen)
      "body": str,              # = stat1 + " · " + stat2 (fallback for v2 templates)
      "caption": str,           # 500-1200 chars (post description)
      "label": str,             # BREAKING | DEVELOPING | ANALYSIS | MARKETS
      "rhetorical_move": "data_card_5beat",
      "topic_tag": str,         # via reused _detect_topic()
      "numeric_highlights": list[str],
    }
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

# Reuse from generator.py for consistency
from generator import (
    MODEL_MAP_ANTHROPIC,
    MODEL_MAP_AUTO,
    _call_api,
    _detect_topic,
    _get_client,
)
from memory import get_memory

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Background suggestion (item #7 of 2026-05-02 pending list)
# ------------------------------------------------------------------

_BG_TAGS_CACHE: dict | None = None

# Tags that match too generally; excluded from scoring.
_GENERIC_BG_TAGS = {"control_room", "geopolitics", "default", "map", "neutral"}


def _load_bg_tags() -> dict:
    global _BG_TAGS_CACHE
    if _BG_TAGS_CACHE is None:
        path = Path(__file__).parent / "assets/reels/backgrounds/_tags.json"
        try:
            _BG_TAGS_CACHE = json.loads(path.read_text())
        except Exception:
            _BG_TAGS_CACHE = {}
    return _BG_TAGS_CACHE


def _pick_suggested_bg(headline: dict) -> tuple[str, int]:
    """Keyword-match headline against _tags.json. Returns (filename, score)."""
    tags = _load_bg_tags()
    text = (headline.get("title", "") + " " + headline.get("summary", "")).lower()
    best_file, best_score = "ancient_map.mp4", 0
    for filename, meta in tags.items():
        if filename == "ancient_map.mp4":
            continue
        specific = [t for t in meta.get("tags", []) if t not in _GENERIC_BG_TAGS]
        score = sum(1 for t in specific if t in text)
        if score > best_score:
            best_score, best_file = score, filename
    return best_file, best_score

# Length budgets (tight enough to fit visual layout)
HOOK_MAX_CHARS = 80
STAT_MAX_CHARS = 80
TTS_MAX_CHARS = 280  # ~30 words = ~12s narration
CAPTION_MIN_CHARS = 500
CAPTION_MAX_CHARS = 1200
VALID_LABELS = {"BREAKING", "DEVELOPING", "ANALYSIS", "MARKETS"}


SYSTEM_PROMPT = """You are the senior writer for The Clam Letter , a political-economy commentary brand.
Voice: punchy, declarative, slightly contrarian. Skeptical of consensus. Factual, dry, never melodramatic.

You produce copy for vertical news reels (1080×1920, 15s). The visual format is a 5-beat "data card":
1. BADGE (label, 1 word) , e.g., BREAKING / ANALYSIS
2. HOOK (≤80 chars) , the news headline, often paraphrased for punch
3. STAT 1 (≤80 chars) , first contextual fact, a relatable number/comparison
4. STAT 2 (≤80 chars) , second contextual fact
5. STAT 3 (≤80 chars) , third contextual fact

Plus you write the TTS NARRATION (read by a news-radio voice) and the long-form CAPTION (post description).

Your discipline:
- Hooks: actor + verb + specific outcome. Avoid hedges ("may", "could").
- Stats: HUMANIZE technical numbers. Translate jargon into common-sense framing.
    "44% odds" → "Less than 1-in-2 chance"
    "$119/barrel" → "Oil at ~$120 a barrel"
    "OPEC+ produces 43M b/d" → "OPEC nations control ~40% of world oil"
    "Russia signed Iran defense pact 2025" → "Russia and Iran signed a defense pact in 2025"
- TTS narration: headline + 1 short synthesis sentence. ~30 words total. The voice fills 12-13 seconds; on-screen text reinforces visually.
- Caption: 500-1200 chars, contrarian Clam Letter style. Three paragraphs typically:
    1. Restate news + key context
    2. The contrarian/analytical angle (this is the brand's voice)
    3. Closing implication or observation
  End with a blank line + 3-5 hashtags.
- English only. No emojis. No "BREAKING:" prefix in the hook (label renders separately).
- IMPORTANT: NEVER use em-dashes (—). Use commas, periods, or colons instead. This applies to hook, stats, tts_text, and caption.
"""


FEW_SHOT_EXAMPLES = """\
EXAMPLE 1 , Input: "President Trump says UAE exiting OPEC will lower gas and oil prices"

{
  "label": "BREAKING",
  "hook": "TRUMP: UAE EXITING OPEC WILL LOWER GAS PRICES",
  "stat1": "UAE = ~7 of every 100 OPEC barrels",
  "stat2": "Half a US gas price = taxes + refining",
  "stat3": "OPEC nations control ~40% of world oil",
  "tts_text": "Breaking. President Trump says the UAE exiting OPEC will lower gas and oil prices. The math behind that claim doesn't add up.",
  "caption": "Trump just claimed the UAE will exit OPEC , and that gas prices will fall as a result.\\n\\nWorth adding context:\\n\\nThe UAE pumps roughly 3 million barrels a day. OPEC+ pumps over 40 million. One member walking changes the cartel's politics, not the global supply curve.\\n\\nUS retail gas isn't priced off OPEC anymore. It moves with refining capacity, regional demand, and federal+state taxes.\\n\\n, The Clam Letter\\n\\n#breaking #iran #oil #opec #trump",
  "numeric_highlights": ["7%", "40%"]
}

EXAMPLE 2 , Input: "Iranian Parliament Speaker Ghalibaf says President Trump cranked oil up to $120 from the US blockade in the Strait of Hormuz"

{
  "label": "BREAKING",
  "hook": "IRAN: 'TRUMP CRANKED OIL TO $120 WITH HORMUZ BLOCKADE'",
  "stat1": "20% of world oil passes through Hormuz daily",
  "stat2": "US 5th Fleet patrols the strait from Bahrain",
  "stat3": "Iran has threatened blockade for 40+ years",
  "tts_text": "Breaking. Iran's Parliament Speaker says President Trump pushed oil prices to one hundred twenty dollars per barrel, with the U.S. blockade of the Strait of Hormuz. Twenty percent of the world's oil flows through this waterway.",
  "caption": "Iran's Parliament Speaker Ghalibaf says Trump 'cranked oil up to $120' via the US blockade of the Strait of Hormuz.\\n\\nA few asterisks worth adding:\\n\\nThe Strait of Hormuz carries roughly 20 percent of global oil shipments daily , about 17 million barrels.\\n\\nThe US 5th Fleet patrols the strait from a base in Bahrain. There is no formal US blockade in place; what's being called a blockade is enhanced naval presence and inspections.\\n\\nIran has threatened to close Hormuz for over four decades and has never executed a full closure.\\n\\n, The Clam Letter\\n\\n#breaking #iran #oil #hormuz #brentcrude",
  "numeric_highlights": ["$120", "20%", "40 years"]
}
"""


def _extract_json(raw: str) -> dict[str, Any]:
    """Extract the first JSON object from a string."""
    # Strip code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    # Find the first complete JSON object
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in response: {raw[:200]}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e} -- raw: {raw[:300]}") from e


def _clip(s: str, max_chars: int) -> str:
    s = (s or "").strip().strip('"').strip("'")
    if len(s) <= max_chars:
        return s
    return s[:max_chars].rstrip()


def generate_reel_copy(
    headline: dict,
    label: str = "BREAKING",
    move_override: str | None = None,
) -> dict:
    """
    Generate copy for a 9:16 v3 (Hyperframes) news reel.

    Args:
        headline: dict with keys {title, summary, source}
        label: badge text. Default BREAKING.
        move_override: ignored in v3 (kept for v2 API compat).

    Returns:
        dict with keys: label, hook, stat1, stat2, stat3, tts_text, body,
                        caption, rhetorical_move, topic_tag, numeric_highlights.
    """
    topic = _detect_topic(headline)
    memory = get_memory()
    continuity = memory.build_continuity_prompt() if memory else ""
    system = SYSTEM_PROMPT + ("\n\n" + continuity if continuity else "")

    label_norm = (label or "BREAKING").upper()
    if label_norm not in VALID_LABELS:
        label_norm = "BREAKING"

    user_prompt = f"""{FEW_SHOT_EXAMPLES}

NOW DO THIS ONE.

News: {headline.get('title', '')}
Context: {(headline.get('summary') or '')[:400]}
Source: {headline.get('source', '')}
Topic: {topic}
Label on screen: {label_norm}

Output STRICT JSON (no markdown, no commentary), matching the example schema exactly:
{{"label": "...", "hook": "...", "stat1": "...", "stat2": "...", "stat3": "...", "tts_text": "...", "caption": "...", "numeric_highlights": ["..."]}}

Constraints:
- hook ≤{HOOK_MAX_CHARS} chars, ALL-CAPS friendly
- stat1, stat2, stat3 ≤{STAT_MAX_CHARS} chars each, HUMANIZED (no raw jargon)
- tts_text ≤{TTS_MAX_CHARS} chars (~30 words); first word should be "Breaking." for alert tone
- caption {CAPTION_MIN_CHARS}-{CAPTION_MAX_CHARS} chars, three-paragraph contrarian breakdown
- numeric_highlights: 0-5 items lifted from hook+stats, each ≤20 chars
- English only
"""

    # Use Haiku for cost , this is short-form copy work
    if os.getenv("OPENROUTER_API_KEY"):
        model = MODEL_MAP_AUTO.get("DEBATE", "anthropic/claude-haiku-4-5")
    else:
        model = MODEL_MAP_ANTHROPIC.get("WIRE", "claude-haiku-4-5-20251001")

    client, is_or = _get_client()
    raw = _call_api(client, model, system, user_prompt, 1500, is_or)

    parsed = _extract_json(raw)

    # Clip + sanitize
    hook = _clip(parsed.get("hook"), HOOK_MAX_CHARS)
    stat1 = _clip(parsed.get("stat1"), STAT_MAX_CHARS)
    stat2 = _clip(parsed.get("stat2"), STAT_MAX_CHARS)
    stat3 = _clip(parsed.get("stat3"), STAT_MAX_CHARS)
    tts_text = (parsed.get("tts_text") or "").strip()
    if len(tts_text) > TTS_MAX_CHARS:
        tts_text = tts_text[:TTS_MAX_CHARS].rstrip()
    caption = (parsed.get("caption") or "").strip().strip('"')

    # Numeric highlights , keep ≤20 char strings
    nums_raw = parsed.get("numeric_highlights") or []
    if not isinstance(nums_raw, list):
        nums_raw = []
    numeric_highlights = [str(n).strip()[:20] for n in nums_raw if str(n).strip()][:5]

    # v2-compat: body fallback so dashboard cards still render content
    body = f"{stat1} · {stat2}" if stat1 and stat2 else (hook or "")

    result = {
        # New v3 fields
        "stat1": stat1,
        "stat2": stat2,
        "stat3": stat3,
        "tts_text": tts_text,
        # v2-compatible
        "hook": hook,
        "body": body,
        "caption": caption,
        "label": label_norm,
        "rhetorical_move": "data_card_5beat",
        "topic_tag": topic,
        "numeric_highlights": numeric_highlights,
    }

    # === Phase 1: minimum trash-edit fields with safe defaults ===
    # Phase 2 will let an LLM choose template_variant + hook_block + cta;
    # for Phase 1 we derive them from existing fields.
    label_to_template = {
        "BREAKING": "shock",
        "DEVELOPING": "shock",
        "ANALYSIS": "analysis",
        "MARKETS": "markets",
    }
    result["template_variant"] = label_to_template.get(label_norm, "shock")

    result["hook_block"] = {
        "variant": "shock",
        "text": hook,
        "tts_lead": tts_text.split(".")[0] + "." if "." in tts_text else tts_text,
    }
    # NOTE: top-level "hook" stays a string for v2-dashboard compat.
    # render_reel_hf._build_payload accepts either string or dict at spec["hook"].

    result["rehook"] = {
        "text": stat2 or stat1 or "",
        "interrupt_kind": "zoom_punch",
    }

    result["cta"] = {
        "variant": "comment_bait",
        "text": "",
        "tts_close": "",
    }

    result["beats"] = [
        {"t": 2.0, "type": "stat", "text": stat1, "emphasis_words": []},
        {"t": 5.0, "type": "stat", "text": stat2, "emphasis_words": []},
        {"t": 9.0, "type": "stat", "text": stat3, "emphasis_words": []},
    ]

    suggested_bg, bg_score = _pick_suggested_bg(headline)
    result["suggested_bg"] = suggested_bg
    result["suggested_bg_score"] = bg_score

    logger.info(
        "v3 reel copy generated",
        extra={
            "hook_len": len(hook),
            "tts_len": len(tts_text),
            "topic": topic,
            "suggested_bg": suggested_bg,
            "bg_score": bg_score,
        },
    )
    return result
