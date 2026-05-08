#!/usr/bin/env python3
"""
render_reel_hf.py — Hyperframes (v3) renderer wrapper for Sol Bot.

Glues together:
    1. Copy data → JSON file in reels-hf/news_examples/
    2. TTS generation (gen_tts_sol) → reels-hf/assets/tts_<id>.mp3
    3. Subprocess call to reels-hf/render_reel.py → MP4
    4. Thumbnail extraction via ffmpeg

Public API matches the v2 renderer signature shape so news_to_reel.py can
swap renderers transparently via env var REELS_RENDERER=v3.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from gen_tts_sol import generate_tts_for_reel
from tts_align import AlignWord, align_words

logger = logging.getLogger(__name__)

SOL_BOT_ROOT = Path(__file__).resolve().parent
REELS_HF_DIR = SOL_BOT_ROOT / "reels-hf"
REELS_HF_NEWS = REELS_HF_DIR / "news_examples"
REELS_HF_ASSETS = REELS_HF_DIR / "assets"
MEDIA_DIR = SOL_BOT_ROOT / "media"
MEDIA_DIR.mkdir(exist_ok=True)

DEFAULT_DURATION_SEC = 15

# Background mapping: copy_data["bg"] should already be a filename like grok_01.mp4.
# This is the same set of bgs the v2 dashboard exposes.
DEFAULT_BG = "grok_01.mp4"

TEMPLATE_BY_VARIANT = {
    "shock": "tpl_shock.html",
    "character": "tpl_character.html",
    "markets": "tpl_markets.html",
    "analysis": "tpl_analysis.html",
}
LEGACY_TEMPLATE = "reel.html"  # the existing single-template fallback
TEMPLATES_DIR = REELS_HF_DIR / "templates"


def _select_template(spec: dict) -> str:
    variant = (spec.get("template_variant") or "").lower()
    return TEMPLATE_BY_VARIANT.get(variant, LEGACY_TEMPLATE)


def _emphasis_times(spec: dict, words: list[AlignWord]) -> list[float]:
    """For each emphasis_word in any beat, find the first aligned word that
    matches (case-insensitive, punctuation-stripped) and emit its start time."""
    targets: list[str] = []
    for beat in spec.get("beats") or []:
        for w in beat.get("emphasis_words") or []:
            if isinstance(w, str) and w.strip():
                targets.append(w.strip().lower())
    times: list[float] = []
    for tgt in targets:
        for aw in words:
            if aw.word.lower() == tgt:
                times.append(aw.start)
                break
    return times


CTA_PHRASE = ["follow", "the", "clam", "letter"]
KARAOKE_CHUNK_SIZE = 2


def _split_cta_tail(words: list[AlignWord]) -> tuple[list[AlignWord], list[AlignWord]]:
    """Return (body_words, cta_words). The CTA tail is the trailing run of
    words matching CTA_PHRASE (case-insensitive, punctuation-stripped). If
    not present, cta_words is empty and body_words = words.
    """
    if len(words) < len(CTA_PHRASE):
        return words, []
    n = len(CTA_PHRASE)
    # Search from right so nested matches don't fool us.
    for start in range(len(words) - n, -1, -1):
        candidate = [w.word.lower().strip(".,;:!?") for w in words[start:start + n]]
        if candidate == CTA_PHRASE:
            return words[:start], words[start:start + n]
    return words, []


def _escape_word(w: str) -> str:
    return (w or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _apply_gold(hook: str, gold: str | None) -> str:
    """Wrap the first case-insensitive occurrence of `gold` in the hook with
    <span class="gold">…</span>. Markets template's `.hook-line .gold` rule
    paints it #ffd500 so the eye has a clear focal point. No-op if `gold`
    is empty or not found.
    """
    if not gold or not hook:
        return hook
    pattern = re.compile(re.escape(gold), re.IGNORECASE)
    return pattern.sub(lambda m: f'<span class="gold">{m.group(0)}</span>', hook, count=1)


def _normalize_kw(s: str) -> str:
    """Lowercase + strip surrounding punctuation for keyword matching."""
    return (s or "").lower().strip(".,;:!?\"'()[]")


def _karaoke_html_chunked(
    words: list[AlignWord],
    chunk_size: int = KARAOKE_CHUNK_SIZE,
    keyword_words: list[str] | None = None,
) -> str:
    """Render words as <div class="kchunk" data-c="N"> blocks of `chunk_size`
    words each; karaokeRolling() in GSAP shows one chunk at a time.

    Words whose normalized form is in `keyword_words` get an extra `kw-key`
    class — CSS pre-paints them gold and JS punches them harder (scale 1.20
    vs 1.12) so the eye latches onto the headline-defining tokens.
    """
    if not words:
        return ""
    keys = {_normalize_kw(k) for k in (keyword_words or []) if k}
    chunks_html: list[str] = []
    for ci_start in range(0, len(words), chunk_size):
        chunk = words[ci_start:ci_start + chunk_size]
        chunk_idx = ci_start // chunk_size
        spans = []
        for offset, w in enumerate(chunk):
            global_i = ci_start + offset
            cls = "kw"
            if keys and _normalize_kw(w.word) in keys:
                cls = "kw kw-key"
            spans.append(f'<span class="{cls}" data-i="{global_i}">{_escape_word(w.word)}</span>')
        chunks_html.append(
            f'<div class="kchunk" data-c="{chunk_idx}">' + " ".join(spans) + "</div>"
        )
    return "".join(chunks_html)


def _beats_payload(spec: dict) -> tuple[list[str], list[float | None]]:
    """Extract up to 3 beat texts + their times for the {{BEAT1..3}} stamps.
    Pads with empty strings / None so templates don't render '{{BEAT3}}'
    literal placeholders if the spec has fewer beats."""
    beats = spec.get("beats") or []
    texts: list[str] = []
    times: list[float | None] = []
    for i in range(3):
        if i < len(beats) and isinstance(beats[i], dict):
            texts.append(str(beats[i].get("text") or ""))
            t = beats[i].get("t")
            times.append(float(t) if isinstance(t, (int, float)) else None)
        else:
            texts.append("")
            times.append(None)
    return texts, times


def _build_payload(spec: dict, words: list[AlignWord], tts_filename: str) -> dict:
    hook = spec.get("hook")
    if isinstance(hook, dict):
        hook_text = hook.get("text", "") or ""
    else:
        hook_text = str(hook or "")

    rehook = spec.get("rehook")
    if isinstance(rehook, dict):
        rehook_text = rehook.get("text", "") or ""
    else:
        rehook_text = ""

    beat_texts, beat_times = _beats_payload(spec)

    body_words, cta_words = _split_cta_tail(words)
    # If we found the CTA phrase, the body karaoke excludes it and we expose
    # CTA_TIME for the dedicated #cta-stamp slide-in. Otherwise CTA_TIME is
    # null and the template skips the stamp gracefully.
    cta_time = cta_words[0].start if cta_words else None
    cta_text = "Follow The Clam Letter" if cta_words else ""

    # Reel duration is flexible per spec. 15s default for shock/character (impact),
    # 18s recommended for analysis variants (more breathing room for argument).
    duration = float(spec.get("duration_sec") or DEFAULT_DURATION_SEC)
    tts_start = 0.4
    loop_tail = 0.5  # sfx-loop sits in the last loop_tail seconds
    tts_duration = max(duration - tts_start - 0.1, 1.0)
    loop_start = max(duration - loop_tail, 0.0)

    # Gold word treatment for the markets template title — wraps a single
    # word in <span class="gold">. Other templates ignore the markup safely.
    hook_with_gold = _apply_gold(hook_text, spec.get("gold_word"))

    return {
        "LABEL": spec.get("label", "BREAKING"),
        "HOOK": hook_with_gold,
        "HOOK_HTML": hook_text,
        "REHOOK": rehook_text,
        "BEAT1": beat_texts[0],
        "BEAT2": beat_texts[1],
        "BEAT3": beat_texts[2],
        "BEATS_TIMES_JSON": json.dumps(beat_times),
        "BG": spec.get("background") or DEFAULT_BG,
        "TTS": tts_filename,
        "BIG_NUM": (spec.get("numeric_highlights") or [""])[0],
        "TICKER_TEXT": (spec.get("topic_tag") or "").upper() + "  •  THE CLAM LETTER  •  ",
        "KARAOKE_HTML": _karaoke_html_chunked(
            body_words, keyword_words=spec.get("keyword_words")
        ),
        "EMPHASIS_TIMES_JSON": json.dumps(_emphasis_times(spec, words)),
        "KARAOKE_WORDS_JSON": json.dumps([w.__dict__ for w in body_words]),
        "CTA_TIME": "null" if cta_time is None else f"{cta_time:.3f}",
        "CTA_TEXT": cta_text,
        "DURATION": f"{duration:g}",
        "TTS_DURATION": f"{tts_duration:g}",
        "LOOP_START": f"{loop_start:g}",
        # Markets template — brand-tag is the small line under "THE CLAM LETTER".
        # Defaults to spec.brand_tag → spec.label → "BREAKING".
        "BRAND_TAG": (spec.get("brand_tag") or spec.get("label") or "BREAKING").upper(),
        # Markets template — ticker scrolls left for TICKER_DURATION seconds.
        # We use duration-1 so the scroll spans the whole reel less the entrance.
        "TICKER_DURATION": f"{max(duration - 1.0, 1.0):g}",
    }


def _render_template(template_name: str, payload: dict, output_path: Path) -> None:
    src = TEMPLATES_DIR / template_name
    if not src.exists():
        # legacy fallback may be at reels-hf root
        src = REELS_HF_DIR / template_name
    if not src.exists():
        raise FileNotFoundError(f"Template not found: {template_name}")
    text = src.read_text(encoding="utf-8")
    for k, v in payload.items():
        text = text.replace("{{" + k + "}}", str(v))
    output_path.write_text(text, encoding="utf-8")


# Render lock — Hyperframes uses index.html as scratch space; serialize concurrent renders.
_RENDER_LOCK = SOL_BOT_ROOT / ".reels_hf.lock"


def _acquire_lock(timeout_sec: int = 600) -> None:
    """Wait for any in-progress render to finish before starting a new one."""
    start = time.time()
    while _RENDER_LOCK.exists():
        if time.time() - start > timeout_sec:
            # Stale lock — assume previous process died
            logger.warning("Stale render lock detected after %ds, removing", timeout_sec)
            try:
                _RENDER_LOCK.unlink()
            except FileNotFoundError:
                pass
            break
        time.sleep(2)
    _RENDER_LOCK.touch()


def _release_lock() -> None:
    try:
        _RENDER_LOCK.unlink()
    except FileNotFoundError:
        pass



def _normalize_for_social(mp4_path: Path) -> bool:
    """Re-encode the MP4 in-place with strict settings that all social platforms accept.

    Hyperframes' default encoding works fine for download/preview but Instagram's container
    pipeline can ERROR on edge-case bitrates / GOP structures / metadata. This pass normalizes:
        - H.264 High@4.0, yuv420p (universal)
        - 128k AAC (IG's recommended max for Reels)
        - GOP=2s (IG keyframe expectation)
        - Stripped metadata + chapters
        - moov atom at front (faststart)
    """
    if not mp4_path.exists():
        return False
    tmp = mp4_path.with_suffix(".social.mp4")
    cmd = [
        "ffmpeg", "-y", "-i", str(mp4_path),
        "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.0",
        "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
        "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        "-map_metadata", "-1", "-map_chapters", "-1",
        str(tmp),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=180)
        if result.returncode != 0:
            logger.warning("Social-normalize ffmpeg failed (keeping original): %s",
                           result.stderr[-300:].decode(errors="ignore"))
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(mp4_path)
        return True
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("Social-normalize exception: %s", e)
        tmp.unlink(missing_ok=True)
        return False


def _extract_thumbnail(mp4_path: Path, jpg_path: Path, at_sec: float = 1.0) -> bool:
    """Pull a single frame as JPEG. Returns True on success."""
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(at_sec),
                "-i", str(mp4_path),
                "-frames:v", "1",
                "-q:v", "3",
                str(jpg_path),
            ],
            capture_output=True, check=True, timeout=20,
        )
        return jpg_path.exists()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning("Thumbnail extraction failed: %s", e)
        return False


def render_reel(
    copy_data: dict,
    reel_id: str | None = None,
    bg: str | None = None,
) -> dict:
    """
    Render a v3 reel from generated copy data.

    Args:
        copy_data: dict from reels_generator.generate_reel_copy() — must contain
                   hook, stat1, stat2, stat3, tts_text, label.
        reel_id: optional reel identifier. Generated if not provided.
        bg: background video filename (e.g., "grok_01.mp4"). Default grok_01.

    Returns:
        {
            "reel_id": str,
            "local_path": str,           # path to MP4
            "thumbnail_path": str | None,
            "duration_sec": int,
            "format_version": "v3_hyperframes",
        }
    """
    reel_id = reel_id or f"reel_{uuid.uuid4().hex[:8]}"
    bg_filename = bg or DEFAULT_BG

    output_mp4 = MEDIA_DIR / f"reel_{reel_id}.mp4"
    output_jpg = MEDIA_DIR / f"reel_{reel_id}.jpg"

    # Validate the bg exists in reels-hf/assets/
    bg_path = REELS_HF_ASSETS / bg_filename
    if not bg_path.exists():
        raise FileNotFoundError(
            f"Background video not found: {bg_path}. "
            f"Expected one of grok_01.mp4 / grok_02.mp4 / grok_03.mp4 in {REELS_HF_ASSETS}"
        )

    _acquire_lock()
    try:
        # 1. Generate TTS narration. Auto-fit cap scales with the reel's
        # duration_sec — a 20s reel gets a 19s budget, so Mark can deliver
        # ~44 words at natural pace without atempo speedup desync'ing the
        # karaoke. See script structure rules in gen_tts_sol.py.
        # Re-uses tts_<reel_id>.mp3 if it already exists on disk so iterations
        # on layout don't burn ElevenLabs credits.
        tts_text = copy_data.get("tts_text", "").strip()
        tts_path = None
        if not tts_text:
            logger.warning("No tts_text in copy_data; reel will have no narration")
        else:
            cached = REELS_HF_ASSETS / f"tts_{reel_id}.mp3"
            if cached.exists() and cached.stat().st_size > 1024:
                logger.info("Reusing cached TTS: %s", cached.name)
                tts_path = cached
            else:
                duration_sec = float(copy_data.get("duration_sec") or DEFAULT_DURATION_SEC)
                tts_cap = max(duration_sec - 1.0, 1.0)
                tts_path = generate_tts_for_reel(reel_id, tts_text, max_duration_sec=tts_cap)
                logger.info("Generated TTS: %s (cap %.1fs)", tts_path.name, tts_cap)

        # 2. Word-level alignment for karaoke (best-effort; empty list on failure)
        words: list[AlignWord] = []
        if tts_path is not None:
            try:
                words = align_words(tts_path)
            except Exception as e:
                logger.warning("align_words failed (continuing without karaoke): %s", e)

        # 3. Pick template + render index.html for Hyperframes
        template_name = _select_template(copy_data)
        payload = _build_payload(
            copy_data,
            words=words,
            tts_filename=tts_path.name if tts_path else "",
        )
        index_path = REELS_HF_DIR / "index.html"
        _render_template(template_name, payload, index_path)
        logger.info("Rendered template %s -> index.html (%d words aligned)",
                    template_name, len(words))

        # 4. Render via Hyperframes
        logger.info("Starting Hyperframes render for reel %s ...", reel_id)
        start = time.time()
        result = subprocess.run(
            ["npx", "hyperframes", "render", "-o", str(output_mp4)],
            cwd=REELS_HF_DIR,
            capture_output=True, text=True, timeout=600,
        )
        elapsed = time.time() - start

        if result.returncode != 0:
            logger.error(
                "Hyperframes render failed (exit %d) after %.1fs:\nSTDOUT:\n%s\nSTDERR:\n%s",
                result.returncode, elapsed, result.stdout[-2000:], result.stderr[-2000:],
            )
            raise RuntimeError(f"Hyperframes render failed: exit {result.returncode}")

        if not output_mp4.exists():
            raise RuntimeError(f"Render reported success but no MP4 at {output_mp4}")

        logger.info("Render complete: %s (%.1fs, %.1f MB)",
                    output_mp4.name, elapsed, output_mp4.stat().st_size / 1024 / 1024)

        # 5. Re-encode for IG/TikTok/YT compatibility (strict settings, in-place)
        normalized = _normalize_for_social(output_mp4)
        if normalized:
            logger.info("Social-normalize OK (%.1f MB)",
                        output_mp4.stat().st_size / 1024 / 1024)

        # 6. Extract thumbnail
        thumb_ok = _extract_thumbnail(output_mp4, output_jpg, at_sec=2.0)

        return {
            "reel_id": reel_id,
            "local_path": str(output_mp4),
            "thumbnail_path": str(output_jpg) if thumb_ok else None,
            "duration_sec": int(copy_data.get("duration_sec") or DEFAULT_DURATION_SEC),
            "format_version": "v3_hyperframes",
        }
    finally:
        _release_lock()


# ----- CLI for manual testing -----
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Render a v3 reel from copy JSON.")
    parser.add_argument("copy_json", type=Path, help="Path to JSON with copy data")
    parser.add_argument("--bg", default=DEFAULT_BG)
    parser.add_argument("--reel-id", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    with args.copy_json.open(encoding="utf-8") as f:
        data = json.load(f)
    result = render_reel(data, reel_id=args.reel_id, bg=args.bg)
    print(json.dumps(result, indent=2))
