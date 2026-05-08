#!/usr/bin/env python3
"""List all voices in your ElevenLabs account with their IDs."""
import os
import sys
from pathlib import Path

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv(Path(__file__).resolve().parent / ".env")

client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
result = client.voices.search()

print(f"\n🎙️  {len(result.voices)} voices in your account:\n")
print(f"{'VOICE ID':<25} {'NAME':<35} CATEGORY")
print("-" * 80)
for v in result.voices:
    cat = getattr(v, "category", "—") or "—"
    print(f"{v.voice_id:<25} {v.name:<35} {cat}")
