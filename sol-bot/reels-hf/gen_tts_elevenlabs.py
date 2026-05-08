#!/usr/bin/env python3
"""
gen_tts_elevenlabs.py — Generate TTS audio for reel headlines using ElevenLabs.

Reads `news_examples/*.json`, takes the `tts_text` field, and produces
`assets/tts_<news_name>.mp3` using ElevenLabs' API.

Voice: Adam (deep American male, news-anchor authoritative)
Model: eleven_turbo_v2_5 (fast, high quality, low latency)

Usage:
    python gen_tts_elevenlabs.py news_examples/centcom_hypersonic.json
    python gen_tts_elevenlabs.py news_examples/*.json     # batch
    python gen_tts_elevenlabs.py --all                    # all in news_examples/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Force UTF-8 on Windows
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

ASSETS_DIR = SCRIPT_DIR / "assets"
NEWS_DIR = SCRIPT_DIR / "news_examples"

# ---- Voice & model config ----
# Adam — pNInz6obpgDQGcFmaJgB — deep, authoritative, news anchor feel
VOICE_ID = "pNInz6obpgDQGcFmaJgB"
MODEL_ID = "eleven_turbo_v2_5"  # fast + high quality

# Voice settings tuned for "alert/news" tone — slightly more urgent than default
VOICE_SETTINGS = {
    "stability": 0.40,        # lower = more dynamic/expressive
    "similarity_boost": 0.85, # higher = closer to source voice
    "style": 0.55,            # 0-1, "newscaster"-ish boost
    "use_speaker_boost": True,
}


def get_client() -> ElevenLabs:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("❌ ELEVENLABS_API_KEY not set. Add it to .env", file=sys.stderr)
        sys.exit(1)
    return ElevenLabs(api_key=api_key)


def generate_tts(client: ElevenLabs, text: str, output_path: Path, voice_id: str) -> None:
    print(f"  → Generating: {output_path.name}")
    audio_iter = client.text_to_speech.convert(
        voice_id=voice_id,
        model_id=MODEL_ID,
        text=text,
        voice_settings=VOICE_SETTINGS,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        for chunk in audio_iter:
            if chunk:
                f.write(chunk)
    print(f"  ✓ Wrote {output_path.relative_to(SCRIPT_DIR)} ({output_path.stat().st_size // 1024} KB)")


def process_json_file(client: ElevenLabs, json_path: Path, voice_id: str) -> None:
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    text = data.get("tts_text")
    if not text:
        print(f"⚠️  Skipping {json_path.name}: no 'tts_text' field", file=sys.stderr)
        return

    output_path = ASSETS_DIR / f"tts_{json_path.stem}.mp3"
    print(f"\n📰 {json_path.stem}")
    print(f"  Text: {text[:80]}{'...' if len(text) > 80 else ''}")
    generate_tts(client, text, output_path, voice_id)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate ElevenLabs TTS for reel headlines",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="JSON file(s) with 'tts_text' field. Omit + use --all for batch.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process every JSON in news_examples/",
    )
    parser.add_argument(
        "--voice-id",
        default=VOICE_ID,
        help=f"Override voice ID (default: {VOICE_ID} = Adam)",
    )
    args = parser.parse_args()

    voice_id = args.voice_id

    if args.all:
        targets = sorted(NEWS_DIR.glob("*.json"))
        if not targets:
            print(f"❌ No JSON files in {NEWS_DIR}", file=sys.stderr)
            return 1
    elif args.inputs:
        targets = args.inputs
    else:
        parser.print_help()
        return 1

    print(f"🎙️  ElevenLabs TTS — voice: {voice_id}, model: {MODEL_ID}")
    client = get_client()
    for json_path in targets:
        if not json_path.exists():
            print(f"⚠️  Skipping missing file: {json_path}", file=sys.stderr)
            continue
        process_json_file(client, json_path, voice_id)

    print(f"\n✅ Done. {len(targets)} file(s) processed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
