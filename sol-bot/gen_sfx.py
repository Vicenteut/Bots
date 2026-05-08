"""
gen_sfx.py — Synthesize 4 SFX files for Reels v2 sound design via ffmpeg.

These are functional placeholders. They use:
  - open_impact: 55Hz sub-bass + brown noise click + compression (cinematic boom)
  - whoosh_tail: filtered pink noise sweep (air-moving feel)
  - soft_ping: 1200Hz sine with sharp envelope (UI tick)
  - loop_thump: 48Hz sub-bass with longer decay (loop-seam masker)

Output: assets/reels/sfx/{open_impact,whoosh_tail,soft_ping,loop_thump}.wav

To upgrade later: replace the .wav files with curated Pixabay/Mixkit/Freesound
assets (no code change needed in gen_news_video_v2.py).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path("/root/x-bot/sol-bot")
SFX_DIR = ROOT / "assets" / "reels" / "sfx"
SFX_DIR.mkdir(parents=True, exist_ok=True)

FFMPEG = "/usr/bin/ffmpeg"
SR = 48000  # match the music bed sample rate


def run(cmd: list[str], label: str):
    print(f">>> Generating {label}...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"!!! FAILED {label}:\n{r.stderr[-1500:]}", file=sys.stderr)
        sys.exit(r.returncode)


def gen_open_impact():
    """Deep cinematic boom: 55Hz sub-bass with brown noise transient + compression."""
    out = SFX_DIR / "open_impact.wav"
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", "sine=frequency=55:duration=0.5",
        "-f", "lavfi", "-i", "anoisesrc=color=brown:duration=0.06",
        "-filter_complex",
        # mix sub-bass + brown noise click; envelope for snappy attack + decay
        "[0:a]volume=2.5,lowpass=f=120[sub];"
        "[1:a]volume=0.45,bandpass=f=400:width_type=h:w=600[click];"
        "[sub][click]amix=inputs=2:duration=longest:dropout_transition=0,"
        "afade=t=in:st=0:d=0.003,"
        "afade=t=out:st=0.18:d=0.32,"
        "acompressor=threshold=-12dB:ratio=4:attack=2:release=120,"
        "volume=0.95",
        "-ac", "2", "-ar", str(SR), "-t", "0.5",
        str(out),
    ]
    run(cmd, "open_impact.wav")


def gen_whoosh_tail():
    """Air-moving whoosh: bandpass-swept pink noise."""
    out = SFX_DIR / "whoosh_tail.wav"
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", "anoisesrc=color=pink:duration=0.45",
        "-af",
        "volume=0.7,"
        "highpass=f=400,"
        "lowpass=f=4500,"
        "afade=t=in:st=0:d=0.04,"
        "afade=t=out:st=0.18:d=0.27,"
        "acompressor=threshold=-15dB:ratio=2.5:attack=5:release=80",
        "-ac", "2", "-ar", str(SR), "-t", "0.45",
        str(out),
    ]
    run(cmd, "whoosh_tail.wav")


def gen_soft_ping():
    """Subtle UI tick: 1200Hz sine with sharp envelope."""
    out = SFX_DIR / "soft_ping.wav"
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", "sine=frequency=1200:duration=0.18",
        "-f", "lavfi", "-i", "sine=frequency=2400:duration=0.18",
        "-filter_complex",
        "[0:a]volume=0.55[fund];"
        "[1:a]volume=0.18[harm];"
        "[fund][harm]amix=inputs=2:duration=longest,"
        "afade=t=in:st=0:d=0.003,"
        "afade=t=out:st=0.04:d=0.14,"
        "lowpass=f=4000",
        "-ac", "2", "-ar", str(SR), "-t", "0.18",
        str(out),
    ]
    run(cmd, "soft_ping.wav")


def gen_loop_thump():
    """Low thump that masks the loop seam: 48Hz sub-bass with longer decay."""
    out = SFX_DIR / "loop_thump.wav"
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", "sine=frequency=48:duration=0.7",
        "-af",
        "volume=2.2,"
        "lowpass=f=110,"
        "afade=t=in:st=0:d=0.008,"
        "afade=t=out:st=0.25:d=0.45,"
        "acompressor=threshold=-12dB:ratio=4:attack=3:release=200,"
        "volume=0.9",
        "-ac", "2", "-ar", str(SR), "-t", "0.7",
        str(out),
    ]
    run(cmd, "loop_thump.wav")


def main():
    gen_open_impact()
    gen_whoosh_tail()
    gen_soft_ping()
    gen_loop_thump()
    print()
    print("=== SFX Library ===")
    for f in sorted(SFX_DIR.glob("*.wav")):
        size = f.stat().st_size
        print(f"  {f.name:<22} {size:>8} bytes")


if __name__ == "__main__":
    main()
