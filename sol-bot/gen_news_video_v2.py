"""
gen_news_video_v2.py — Reel renderer with motion + staggered text reveals.

Phase 1 of format optimization (per project plan):
- Continuous zoom-in motion on background (1.0x → 1.18x over duration)
  via crop+scale time-varying expressions (more reliable than zoompan on video)
- Hook (badge + title + logo) visible from t=0
- Body fades in at t=1.6 over 0.3s, giving a perceptual "reveal" event
- Result: ~3-4 distinct visual states across 18 seconds vs 1 in v1

Backwards-compatible: re-uses all v1 helpers from gen_news_video.

Usage:
    python3 gen_news_video_v2.py --title "Headline" --body "Optional subtext"
    python3 gen_news_video_v2.py --json sample.json

Output: /root/x-bot/sol-bot/media/reel_v2_<timestamp>.mp4
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

import gen_news_video as v1
from gen_news_video import (
    ASSETS, OUTPUT, FFMPEG, W, H, DURATION,
    load_font, wrap_text,
)

# ---------------------------------------------------------------------------
# Phase C — Fonts: Bebas Neue (hook/label, wire-style) + DM Serif Display
# (body, editorial). Falls back to DejaVu if files missing.
# ---------------------------------------------------------------------------
REELS_FONTS = ASSETS / "fonts"
LINUX_FONTS = Path("/usr/share/fonts/truetype")

TITLE_CANDIDATES = [
    REELS_FONTS / "BebasNeue-Regular.ttf",        # primary — wire/breaking
    LINUX_FONTS / "dejavu" / "DejaVuSerif-Bold.ttf",  # fallback
    LINUX_FONTS / "liberation" / "LiberationSerif-Bold.ttf",
    LINUX_FONTS / "dejavu" / "DejaVuSans-Bold.ttf",
]
BODY_CANDIDATES = [
    REELS_FONTS / "DMSerifDisplay-Regular.ttf",   # primary — editorial body
    LINUX_FONTS / "dejavu" / "DejaVuSerif.ttf",
    LINUX_FONTS / "liberation" / "LiberationSerif-Regular.ttf",
    LINUX_FONTS / "dejavu" / "DejaVuSans.ttf",
]
LABEL_CANDIDATES = [
    REELS_FONTS / "BebasNeue-Regular.ttf",        # match hook
    LINUX_FONTS / "dejavu" / "DejaVuSans-Bold.ttf",
    LINUX_FONTS / "liberation" / "LiberationSans-Bold.ttf",
]

# Font sizes — tuned for Bebas Neue's narrower glyphs (need bigger pt for
# similar perceptual weight vs DejaVu Serif Bold).
TITLE_SIZE = 110   # was 78 with DejaVu
BODY_SIZE  = 42    # was 44 with DejaVu (DM Serif is wide, slightly smaller)
LABEL_SIZE = 40    # was 36 with DejaVu (Bebas is condensed, can be bigger)


# Reveal timing (seconds)
HOOK_REVEAL_START = 0.0
HOOK_REVEAL_DURATION = 0.25
BODY_REVEAL_START = 1.6
BODY_REVEAL_DURATION = 0.35

# Background pool — random selection with recently-used penalty
BACKGROUNDS_DIR = ASSETS / "backgrounds"
RECENT_BG_FILE = ASSETS / ".recent_backgrounds.json"
RECENT_BG_HISTORY = 10  # how many recent picks to penalize

# SFX timing + level (linear volume; -3dB ≈ 0.708, -4dB ≈ 0.631, -2dB ≈ 0.794)
SFX_DIR = ASSETS / "sfx"
SFX_EVENTS = [
    # (filename,            t_start_sec, volume_linear)
    ("open_impact.wav",     0.0,         1.00),  # punchy first frame
    ("whoosh_tail.wav",     0.40,        0.708),  # hook settle
    ("soft_ping.wav",       1.60,        0.631),  # body reveal
    ("loop_thump.wav",      17.50,       0.794),  # masks loop seam
]


# ---------------------------------------------------------------------------
# Pillow rendering — split into top (always visible) and body (fades in)
# ---------------------------------------------------------------------------

def _build_gradient_band(W_=W, H_=H):
    """Dark vignette gradient + horizontal band. Same visual as v1."""
    card = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))

    gradient = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gradient)
    for y in range(H_):
        center_dist = abs(y - H_ / 2) / (H_ / 2)
        alpha = int(110 * center_dist + 30)
        gd.line([(0, y), (W_, y)], fill=(0, 0, 0, alpha))
    gradient = gradient.filter(ImageFilter.GaussianBlur(radius=18))
    card.alpha_composite(gradient)

    band_h = 720
    band_y = (H_ - band_h) // 2 - 60
    band = Image.new("RGBA", (W_, band_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    for y in range(band_h):
        edge = min(y, band_h - y) / (band_h / 2)
        a = int(150 * min(edge, 1.0))
        bd.line([(0, y), (W_, y)], fill=(0, 0, 0, a))
    band = band.filter(ImageFilter.GaussianBlur(radius=24))
    card.alpha_composite(band, (0, band_y))

    return card


def _layout(title: str, draw):
    """Compute y-coordinates so card_top and card_body align identically."""
    title_font = load_font(TITLE_CANDIDATES, TITLE_SIZE)
    title_lines = wrap_text(title.upper(), title_font, W - 140, draw)
    # Bebas Neue has tighter vertical metrics — line_h padding adjusted accordingly
    line_h = draw.textbbox((0, 0), "Ag", font=title_font)[3] + 4
    title_block_h = line_h * len(title_lines)
    title_y = (H - title_block_h) // 2 - 80
    label_y = 220
    body_y = title_y + title_block_h + 50
    return {
        "label_y": label_y,
        "title_y": title_y,
        "title_block_h": title_block_h,
        "title_lines": title_lines,
        "title_line_h": line_h,
        "body_y": body_y,
        "title_font": title_font,
    }


def render_card_top(title: str, label: str = "BREAKING") -> Path:
    """Always-visible layer: gradient + band + label badge + title + logo (no body)."""
    card = _build_gradient_band()
    draw = ImageDraw.Draw(card)
    label_font = load_font(LABEL_CANDIDATES, LABEL_SIZE)
    layout = _layout(title, draw)

    # Label badge — Bebas Neue's basic charset doesn't include the "●" bullet,
    # so we draw a small white pill manually next to the text instead.
    label_text = label.upper()
    lw = draw.textbbox((0, 0), label_text, font=label_font)[2]
    pill_d = 14         # small pill diameter (acts as the leading "●")
    pill_gap = 14       # space between pill and text
    pad_x = 32
    pad_y_top = 14
    pad_y_bot = 16
    badge_w = lw + pill_d + pill_gap + pad_x * 2
    ly = layout["label_y"]
    badge_x0 = (W - badge_w) // 2
    badge_y0 = ly - pad_y_top
    badge_y1 = ly + LABEL_SIZE + pad_y_bot - LABEL_SIZE // 4
    draw.rectangle(
        [badge_x0, badge_y0, badge_x0 + badge_w, badge_y1],
        fill=(180, 30, 30, 230),
    )
    # Draw the leading pill (replaces the "●")
    pill_cy = (badge_y0 + badge_y1) // 2
    pill_x0 = badge_x0 + pad_x
    draw.ellipse(
        [pill_x0, pill_cy - pill_d // 2, pill_x0 + pill_d, pill_cy + pill_d // 2],
        fill=(255, 255, 255, 255),
    )
    draw.text(
        (pill_x0 + pill_d + pill_gap, ly),
        label_text, font=label_font, fill=(255, 255, 255, 255),
    )

    # Title with shadow
    for i, line in enumerate(layout["title_lines"]):
        lw = draw.textbbox((0, 0), line, font=layout["title_font"])[2]
        x = (W - lw) // 2
        y = layout["title_y"] + i * layout["title_line_h"]
        for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
            draw.text((x + dx, y + dy), line, font=layout["title_font"], fill=(0, 0, 0, 200))
        draw.text((x, y), line, font=layout["title_font"], fill=(255, 255, 255, 255))

    # Logo (static, throughout video)
    logo_path = ASSETS / "logo.png"
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        target_w = 540
        ratio = target_w / logo.width
        logo = logo.resize((target_w, int(logo.height * ratio)), Image.LANCZOS)
        lx = (W - logo.width) // 2
        ly2 = H - logo.height - 140
        card.alpha_composite(logo, (lx, ly2))

    out = ASSETS / "_card_top.png"
    card.save(out)
    return out


def render_card_body(title: str, body: str) -> Path | None:
    """Body-only layer on transparent bg. Returns None if body empty."""
    if not body:
        return None

    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    body_font = load_font(BODY_CANDIDATES, BODY_SIZE)
    layout = _layout(title, draw)

    body_lines = wrap_text(body, body_font, W - 180, draw)
    bline_h = draw.textbbox((0, 0), "Ag", font=body_font)[3] + 10
    for i, line in enumerate(body_lines):
        lw = draw.textbbox((0, 0), line, font=body_font)[2]
        x = (W - lw) // 2
        y = layout["body_y"] + i * bline_h
        # Body in light grey (matches v1)
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            draw.text((x + dx, y + dy), line, font=body_font, fill=(0, 0, 0, 160))
        draw.text((x, y), line, font=body_font, fill=(230, 230, 230, 255))

    out = ASSETS / "_card_body.png"
    card.save(out)
    return out


# ---------------------------------------------------------------------------
# Background selection — random pool with recently-used penalty
# ---------------------------------------------------------------------------

def _load_recent_bgs() -> list[str]:
    """Read the last N background filenames used (most recent first)."""
    try:
        if RECENT_BG_FILE.exists():
            data = json.loads(RECENT_BG_FILE.read_text(encoding="utf-8"))
            return list(data.get("recent", []))[:RECENT_BG_HISTORY]
    except Exception:
        pass
    return []


def _save_recent_bg(bg_name: str) -> None:
    """Push a filename to the recently-used list (de-duplicated, capped)."""
    recent = _load_recent_bgs()
    recent = [b for b in recent if b != bg_name]
    recent.insert(0, bg_name)
    recent = recent[:RECENT_BG_HISTORY]
    try:
        RECENT_BG_FILE.write_text(json.dumps({"recent": recent}), encoding="utf-8")
    except Exception:
        pass


def list_backgrounds() -> list[dict]:
    """Return all available backgrounds with their tags + thumbnail path.

    Reads tags from `_tags.json` next to the videos. Videos without a tag
    entry get an auto-generated label from the filename.
    """
    if not BACKGROUNDS_DIR.exists():
        return []
    tags_file = BACKGROUNDS_DIR / "_tags.json"
    tags_data: dict = {}
    if tags_file.exists():
        try:
            tags_data = json.loads(tags_file.read_text(encoding="utf-8"))
        except Exception:
            tags_data = {}

    out = []
    for path in sorted(BACKGROUNDS_DIR.glob("*.mp4")):
        meta = tags_data.get(path.name, {})
        thumb = path.with_suffix(".jpg")
        out.append({
            "filename": path.name,
            "path": str(path),
            "thumbnail_filename": thumb.name if thumb.exists() else None,
            "label": meta.get("label") or path.stem.replace("_", " ").title(),
            "tags": meta.get("tags") or [],
            "notes": meta.get("notes") or "",
            "size_bytes": path.stat().st_size,
        })
    return out


def get_background_by_filename(filename: str) -> Path | None:
    """Return the path for a specific background by filename.
    Returns None if filename is empty or file doesn't exist."""
    if not filename:
        return None
    candidate = BACKGROUNDS_DIR / filename
    if candidate.exists() and candidate.suffix == ".mp4":
        return candidate
    return None


def pick_background(explicit_filename: str | None = None) -> Path:
    """Pick a background. If `explicit_filename` is provided and exists, use it.
    Otherwise fall back to random selection with inverse-square recently-used penalty.

    Search order for random:
      1. assets/reels/backgrounds/*.mp4 (the new pool)
      2. assets/reels/background.mp4 (legacy single-file fallback)
    """
    if explicit_filename:
        explicit = get_background_by_filename(explicit_filename)
        if explicit is not None:
            _save_recent_bg(explicit.name)
            return explicit
        # If user requested an explicit bg that doesn't exist, fail loudly.
        raise FileNotFoundError(
            f"Background not found: {explicit_filename}. "
            f"Available: {[p.name for p in BACKGROUNDS_DIR.glob('*.mp4')]}"
        )

    pool: list[Path] = []
    if BACKGROUNDS_DIR.exists():
        pool = sorted(BACKGROUNDS_DIR.glob("*.mp4"))

    if not pool:
        legacy = ASSETS / "background.mp4"
        if legacy.exists():
            return legacy
        raise FileNotFoundError(
            f"No background videos found. Add at least one .mp4 to {BACKGROUNDS_DIR}"
        )

    if len(pool) == 1:
        _save_recent_bg(pool[0].name)
        return pool[0]

    recent = _load_recent_bgs()
    weights = []
    for path in pool:
        try:
            idx = recent.index(path.name)
            # idx 0 = most recent → weight 1/4 ≈ 0.25
            # idx 9 = oldest in history → weight 1/121 ≈ 0.008
            weights.append(1.0 / (idx + 2) ** 2)
        except ValueError:
            weights.append(1.0)  # never used recently → full weight

    chosen = random.choices(pool, weights=weights, k=1)[0]
    _save_recent_bg(chosen.name)
    return chosen


# ---------------------------------------------------------------------------
# ffmpeg compositing — single-pass with motion + reveals
# ---------------------------------------------------------------------------

def _bg_motion_filter(duration: int) -> str:
    """
    Continuous zoom-in via zoompan filter.

    zoompan is the ffmpeg-4.4-compatible way to apply per-frame zoom.
    With d=1, each input frame produces one output frame; `on` is the
    global output frame counter (0 → duration*fps - 1).

    Zoom goes linearly from 1.0 → 1.18 across the duration.
    """
    fps = 30
    total_frames = duration * fps
    # zoom = 1 + 0.18 * (on / total_frames). At on=0 → 1.0; at on=total_frames-1 → ~1.18
    zoom_expr = f"1+0.18*on/{total_frames}"

    # zoompan output is fixed size W×H, so we must pre-crop to W×H first
    # (otherwise the source is e.g. 1920x1080 widescreen and zoompan would distort).
    return (
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},"
        f"eq=brightness=-0.05:saturation=1.1:contrast=1.05,"
        f"zoompan=z='{zoom_expr}':d=1:s={W}x{H}:fps={fps}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    )


def _resolve_sfx_inputs(duration: int) -> list[tuple[Path, float, float]]:
    """Return list of (path, t_start, volume) for SFX files that exist on disk
    AND fire within [0, duration]. Missing files are silently skipped — the
    rest of the audio mix still works, just with fewer hits."""
    out = []
    for name, t_start, vol in SFX_EVENTS:
        path = SFX_DIR / name
        if path.exists() and 0.0 <= t_start < duration:
            out.append((path, t_start, vol))
    return out


def compose_video_v2(
    card_top: Path,
    card_body: Path | None,
    out_path: Path,
    duration: int = DURATION,
    background_filename: str | None = None,
):
    """Compose v2 reel: bg motion + always-on top card + late-fading body card +
    layered SFX hits with light bus compression for glue.

    If `background_filename` is provided, use that exact bg. Otherwise pick
    randomly from `assets/reels/backgrounds/` with recently-used penalty.
    Falls back to legacy `assets/reels/background.mp4` if the pool is empty.
    """
    bg = pick_background(explicit_filename=background_filename)
    print(f">>> [v2] Background: {bg.name}{' (explicit)' if background_filename else ' (random)'}")
    music = ASSETS / "music.mp3"

    # Inputs (in order: 0=bg, 1=music, 2=card_top, [3=card_body], [4..]=sfx)
    cmd = [str(FFMPEG), "-y",
           "-stream_loop", "-1", "-t", str(duration), "-i", str(bg),
           "-stream_loop", "-1", "-t", str(duration), "-i", str(music),
           "-loop", "1", "-t", str(duration), "-i", str(card_top)]
    body_idx = None
    if card_body is not None:
        cmd.extend(["-loop", "1", "-t", str(duration), "-i", str(card_body)])
        body_idx = 3

    # SFX inputs go after body card
    sfx_events = _resolve_sfx_inputs(duration)
    next_idx = (body_idx + 1) if body_idx is not None else 3
    sfx_input_idx = []
    for path, _, _ in sfx_events:
        cmd.extend(["-i", str(path)])
        sfx_input_idx.append(next_idx)
        next_idx += 1

    bg_motion = _bg_motion_filter(duration)

    hook_fade = (
        f"[2:v]format=rgba,fade=in:st={HOOK_REVEAL_START}:"
        f"d={HOOK_REVEAL_DURATION}:alpha=1[hook_fade]"
    )

    fg_lines = [
        f"[0:v]{bg_motion}[bg]",
        hook_fade,
        f"[bg][hook_fade]overlay=0:0:format=auto[bg_with_top]",
    ]

    if body_idx is not None:
        fg_lines.append(
            f"[{body_idx}:v]format=rgba,"
            f"fade=in:st={BODY_REVEAL_START}:d={BODY_REVEAL_DURATION}:alpha=1[body_fade]"
        )
        fg_lines.append("[bg_with_top][body_fade]overlay=0:0:format=auto[v]")
    else:
        fg_lines.append("[bg_with_top]copy[v]")

    # ----- audio mix -----
    # Music bed: existing fade in/out + volume attenuation (slightly lower than
    # v1's 0.85 to leave headroom for SFX hits).
    fg_lines.append(
        f"[1:a]afade=t=in:st=0:d=0.6,"
        f"afade=t=out:st={duration-0.8}:d=0.8,"
        f"volume=0.78[bed]"
    )

    if sfx_events:
        # Process each SFX: volume + delay-to-placement
        sfx_labels = []
        for i, (idx, (_, t_start, vol)) in enumerate(zip(sfx_input_idx, sfx_events)):
            delay_ms = int(t_start * 1000)
            label = f"s{i}"
            fg_lines.append(
                f"[{idx}:a]volume={vol:.3f},adelay={delay_ms}|{delay_ms}[{label}]"
            )
            sfx_labels.append(f"[{label}]")

        # Mix bed + all SFX. duration=first → length matches bed (= duration).
        # acompressor glues the mix and prevents clipping when SFX stack with bed.
        mix_inputs = "[bed]" + "".join(sfx_labels)
        n_inputs = 1 + len(sfx_labels)
        fg_lines.append(
            f"{mix_inputs}amix=inputs={n_inputs}:duration=first:dropout_transition=0,"
            f"acompressor=threshold=-18dB:ratio=3:attack=20:release=250[a]"
        )
    else:
        # No SFX assets present → just rename [bed] to [a]
        fg_lines.append("[bed]acopy[a]")

    cmd.extend([
        "-filter_complex", ";".join(fg_lines),
        "-map", "[v]", "-map", "[a]",
        # preset=fast trades ~5% larger file for ~30-40% faster encoding;
        # critical to keep the synchronous /api/reels/generate call under
        # Cloudflare's 100s timeout. Quality difference is imperceptible at
        # the bitrates we target (8 Mbps avg).
        "-c:v", "libx264", "-preset", "fast",
        "-b:v", "8M", "-maxrate", "10M", "-bufsize", "16M",
        "-profile:v", "high", "-level", "4.2",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-r", "30", "-t", str(duration),
        "-movflags", "+faststart",
        "-threads", "0",  # use all available CPU cores
        str(out_path),
    ])

    sfx_summary = (
        f"{len(sfx_events)} SFX events" if sfx_events
        else "no SFX (assets missing — falling back to bed only)"
    )
    print(f">>> [v2] Running ffmpeg (motion + staggered reveals + {sfx_summary})...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FFMPEG STDERR:")
        print(result.stderr[-3500:])
        sys.exit(result.returncode)
    print(f">>> [v2] Done: {out_path}")


def render_reel_v2(
    copy: dict,
    out_path: Path,
    duration: int = DURATION,
    background_filename: str | None = None,
) -> Path:
    """Drop-in render entry point. Mirrors v1 signature for news_to_reel.py compat.

    `background_filename` (optional): exact bg file to use. If None, random pick.
    Can also be supplied via copy["background_filename"] for backwards compat
    with callers that route everything through the copy dict.
    """
    title = copy["hook"]
    body = copy.get("body", "")
    label = copy.get("label", "BREAKING")
    bg_filename = background_filename or copy.get("background_filename")

    print(f">>> [v2] Title: {title}")
    print(f">>> [v2] Body:  {body[:100]}{'...' if len(body) > 100 else ''}")
    print(">>> [v2] Rendering top card...")
    card_top = render_card_top(title, label)
    print(f">>> [v2] Top card: {card_top}")

    print(">>> [v2] Rendering body card...")
    card_body = render_card_body(title, body)
    if card_body:
        print(f">>> [v2] Body card: {card_body}")

    compose_video_v2(card_top, card_body, out_path, duration,
                     background_filename=bg_filename)
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", help="Headline text")
    parser.add_argument("--body", default="", help="Optional subtext")
    parser.add_argument("--label", default="BREAKING")
    parser.add_argument("--json", help="Path to JSON file with title/body/label")
    parser.add_argument("--out", help="Output filename")
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

    out = Path(args.out) if args.out else OUTPUT / f"reel_v2_{int(time.time())}.mp4"
    render_reel_v2({"hook": title, "body": body, "label": label}, out, args.duration)


if __name__ == "__main__":
    main()
