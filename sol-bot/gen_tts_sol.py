#!/usr/bin/env python3
"""
gen_tts_sol.py — ElevenLabs TTS wrapper for Sol Bot v3 reels.

Generates MP3 narration files (Joe Stokes — News Radio Narrator) into the
reels-hf assets directory, ready for the Hyperframes renderer to consume.

Used by render_reel_hf.py during the v3 pipeline.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv()

logger = logging.getLogger(__name__)

# Mark — Natural Conversations (user's personal professional voice clone)
DEFAULT_VOICE_ID = "UgBBYS2sOqTuMpoF3BR0"
MODEL_ID = "eleven_turbo_v2_5"

# Voice settings tuned for "alert/news" tone
VOICE_SETTINGS = {
    "stability": 0.40,
    "similarity_boost": 0.85,
    "style": 0.55,
    "use_speaker_boost": True,
}

# Where reels-hf expects assets
SOL_BOT_ROOT = Path(__file__).resolve().parent
REELS_HF_ASSETS = SOL_BOT_ROOT / "reels-hf" / "assets"

# Maximum acceptable TTS duration to fit in 15s reel.
# Reel template has data-duration=14.5 starting at 0.5s → audio plays for 14.5s.
TTS_MAX_DURATION_SEC = 14.5


def _get_client() -> ElevenLabs:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY not set. Add it to /root/x-bot/sol-bot/.env"
        )
    return ElevenLabs(api_key=api_key)


def _audio_duration_sec(path: Path) -> float:
    """Use ffprobe to get audio duration. Returns 0.0 on failure."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def _apply_speedup(input_path: Path, factor: float) -> None:
    """Speed up an MP3 in-place using ffmpeg atempo (no pitch shift)."""
    if abs(factor - 1.0) < 0.02:
        return  # no-op
    tmp = input_path.with_suffix(".speedup.mp3")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(input_path),
            "-filter:a", f"atempo={factor:.3f}",
            "-vn", str(tmp),
        ],
        capture_output=True, check=True, timeout=30,
    )
    tmp.replace(input_path)


def generate_tts(
    text: str,
    output_path: Path,
    voice_id: str = DEFAULT_VOICE_ID,
    auto_fit: bool = True,
) -> Path:
    """
    Generate TTS MP3 from text and save to output_path.

    Args:
        text: Words to synthesize. Should already be ≤280 chars (~30 words).
        output_path: Where to write the MP3.
        voice_id: ElevenLabs voice. Default = Joe Stokes.
        auto_fit: If True and resulting audio exceeds TTS_MAX_DURATION_SEC,
                  apply ffmpeg atempo speedup to fit. Better than truncating.

    Returns:
        Path to the produced MP3.
    """
    if not text or not text.strip():
        raise ValueError("TTS text is empty")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    client = _get_client()
    audio_iter = client.text_to_speech.convert(
        voice_id=voice_id,
        model_id=MODEL_ID,
        text=text.strip(),
        voice_settings=VOICE_SETTINGS,
    )
    with output_path.open("wb") as f:
        for chunk in audio_iter:
            if chunk:
                f.write(chunk)

    duration = _audio_duration_sec(output_path)
    logger.info(
        "TTS generated: %s (%.2fs, %d chars)",
        output_path.name, duration, len(text),
    )

    if auto_fit and duration > TTS_MAX_DURATION_SEC:
        # Slight speedup so it fits the reel without truncating the last word.
        # atempo > 1.4 starts to sound rushed for radio-narrator tone — cap there.
        target_factor = duration / TTS_MAX_DURATION_SEC
        factor = min(target_factor, 1.4)
        logger.info(
            "TTS too long (%.2fs > %.2fs), applying atempo=%.2f",
            duration, TTS_MAX_DURATION_SEC, factor,
        )
        _apply_speedup(output_path, factor)
        if target_factor > 1.4:
            logger.warning(
                "TTS still slightly long after capped speedup. "
                "Consider shortening tts_text in the generator output."
            )

    return output_path


def generate_tts_for_reel(reel_id: str, tts_text: str, voice_id: str = DEFAULT_VOICE_ID) -> Path:
    """
    Convenience wrapper: write to reels-hf/assets/tts_<reel_id>.mp3.
    Returns the path to the produced MP3.
    """
    output_path = REELS_HF_ASSETS / f"tts_{reel_id}.mp3"
    return generate_tts(tts_text, output_path, voice_id=voice_id, auto_fit=True)
