"""
Generate a 9:16 news Reel/TikTok video for The Clam Letter (Linux/VPS variant).

Usage:
    python3 gen_news_video.py --title "Headline here" --body "Optional subtext"
    python3 gen_news_video.py --json sample.json

Output: /root/x-bot/sol-bot/media/reel_<timestamp>.mp4
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).parent
ASSETS = ROOT / "assets" / "reels"
OUTPUT = ROOT / "media"
OUTPUT.mkdir(exist_ok=True)

FFMPEG = Path("/usr/bin/ffmpeg")

W, H = 1080, 1920
DURATION = 18

LINUX_FONTS = Path("/usr/share/fonts/truetype")
TITLE_CANDIDATES = [
    LINUX_FONTS / "dejavu" / "DejaVuSerif-Bold.ttf",
    LINUX_FONTS / "liberation" / "LiberationSerif-Bold.ttf",
    LINUX_FONTS / "dejavu" / "DejaVuSans-Bold.ttf",
]
BODY_CANDIDATES = [
    LINUX_FONTS / "dejavu" / "DejaVuSerif.ttf",
    LINUX_FONTS / "liberation" / "LiberationSerif-Regular.ttf",
    LINUX_FONTS / "dejavu" / "DejaVuSans.ttf",
]
LABEL_CANDIDATES = [
    LINUX_FONTS / "dejavu" / "DejaVuSans-Bold.ttf",
    LINUX_FONTS / "liberation" / "LiberationSans-Bold.ttf",
]


def load_font(candidates, size):
    for p in candidates:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def wrap_text(text, font, max_width, draw):
    words = text.split()
    lines, line = [], []
    for word in words:
        trial = " ".join(line + [word])
        w = draw.textbbox((0, 0), trial, font=font)[2]
        if w <= max_width or not line:
            line.append(word)
        else:
            lines.append(" ".join(line))
            line = [word]
    if line:
        lines.append(" ".join(line))
    return lines


def render_text_card(title: str, body: str, label: str = "BREAKING") -> Path:
    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    gradient = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gradient)
    for y in range(H):
        center_dist = abs(y - H / 2) / (H / 2)
        alpha = int(110 * center_dist + 30)
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    gradient = gradient.filter(ImageFilter.GaussianBlur(radius=18))
    card.alpha_composite(gradient)

    band_h = 720
    band_y = (H - band_h) // 2 - 60
    band = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    for y in range(band_h):
        edge = min(y, band_h - y) / (band_h / 2)
        a = int(150 * min(edge, 1.0))
        bd.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    band = band.filter(ImageFilter.GaussianBlur(radius=24))
    card.alpha_composite(band, (0, band_y))

    draw = ImageDraw.Draw(card)

    label_font = load_font(LABEL_CANDIDATES, 36)
    title_font = load_font(TITLE_CANDIDATES, 78)
    body_font = load_font(BODY_CANDIDATES, 44)

    label_text = f"●  {label.upper()}"
    lw = draw.textbbox((0, 0), label_text, font=label_font)[2]
    label_y = 220
    draw.rectangle([(W - lw) // 2 - 28, label_y - 12, (W + lw) // 2 + 28, label_y + 50],
                   fill=(180, 30, 30, 230))
    draw.text(((W - lw) // 2, label_y), label_text, font=label_font, fill=(255, 255, 255, 255))

    title_lines = wrap_text(title.upper(), title_font, W - 140, draw)
    line_h = draw.textbbox((0, 0), "Ag", font=title_font)[3] + 12
    block_h = line_h * len(title_lines)
    title_y = (H - block_h) // 2 - 80
    for i, line in enumerate(title_lines):
        lw = draw.textbbox((0, 0), line, font=title_font)[2]
        x = (W - lw) // 2
        y = title_y + i * line_h
        for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
            draw.text((x + dx, y + dy), line, font=title_font, fill=(0, 0, 0, 200))
        draw.text((x, y), line, font=title_font, fill=(255, 255, 255, 255))

    if body:
        body_lines = wrap_text(body, body_font, W - 180, draw)
        bline_h = draw.textbbox((0, 0), "Ag", font=body_font)[3] + 10
        body_y = title_y + block_h + 60
        for i, line in enumerate(body_lines):
            lw = draw.textbbox((0, 0), line, font=body_font)[2]
            x = (W - lw) // 2
            y = body_y + i * bline_h
            draw.text((x, y), line, font=body_font, fill=(230, 230, 230, 255))

    logo_path = ASSETS / "logo.png"
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        target_w = 540
        ratio = target_w / logo.width
        logo = logo.resize((target_w, int(logo.height * ratio)), Image.LANCZOS)
        lx = (W - logo.width) // 2
        ly = H - logo.height - 140
        card.alpha_composite(logo, (lx, ly))

    out = ASSETS / "_text_card.png"
    card.save(out)
    return out


def compose_video(text_card: Path, out_path: Path, duration: int = DURATION):
    bg = ASSETS / "background.mp4"
    music = ASSETS / "music.mp3"

    cmd = [
        str(FFMPEG), "-y",
        "-stream_loop", "-1", "-t", str(duration), "-i", str(bg),
        "-stream_loop", "-1", "-t", str(duration), "-i", str(music),
        "-loop", "1", "-t", str(duration), "-i", str(text_card),
        "-filter_complex",
        (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},"
            f"eq=brightness=-0.05:saturation=1.1:contrast=1.05[bg];"
            f"[bg][2:v]overlay=0:0:format=auto[v];"
            f"[1:a]afade=t=in:st=0:d=0.6,afade=t=out:st={duration-0.8}:d=0.8,"
            f"volume=0.85[a]"
        ),
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-b:v", "8M", "-maxrate", "10M", "-bufsize", "16M", "-profile:v", "high", "-level", "4.2",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-r", "30",
        "-t", str(duration),
        "-movflags", "+faststart",
        str(out_path),
    ]
    print(">>> Running ffmpeg...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FFMPEG STDERR:")
        print(result.stderr[-3000:])
        sys.exit(result.returncode)
    print(f">>> Done: {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", help="Headline text")
    parser.add_argument("--body", default="", help="Optional subtext / context")
    parser.add_argument("--label", default="BREAKING", help="Top label (default: BREAKING)")
    parser.add_argument("--json", help="Path to JSON file with title/body/label")
    parser.add_argument("--out", help="Output filename (default: media/reel_<ts>.mp4)")
    parser.add_argument("--duration", type=int, default=DURATION)
    args = parser.parse_args()

    if args.json:
        data = json.loads(Path(args.json).read_text(encoding="utf-8"))
        title = data["title"]
        body = data.get("body", "")
        label = data.get("label", "BREAKING")
    elif args.title:
        title = args.title
        body = args.body
        label = args.label
    else:
        parser.error("Provide --title or --json")

    out = Path(args.out) if args.out else OUTPUT / f"reel_{int(time.time())}.mp4"

    print(f">>> Title: {title}")
    print(f">>> Body:  {body[:100]}{'...' if len(body) > 100 else ''}")
    print(">>> Rendering text card...")
    card = render_text_card(title, body, label)
    print(f">>> Card: {card}")
    compose_video(card, out, args.duration)


if __name__ == "__main__":
    main()
