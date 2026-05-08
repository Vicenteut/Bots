"""Generate 1024x1024 app icon for TikTok / Meta / YouTube reviewer submissions.

Style: dark navy bg + thin gold border + 'TCL' monogram top + 'THE CLAM LETTER' bottom.
Square, centered, readable at small sizes.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path("/root/x-bot/sol-bot/assets/reels/app_icon_1024.png")
SIZE = 1024

# Colors — dark editorial newsprint palette
BG = (15, 18, 28, 255)            # near-black navy
BG_GRADIENT_END = (28, 33, 48, 255)
BORDER = (188, 158, 96, 255)      # warm gold
MONO_FILL = (245, 240, 230, 255)  # warm white
SUB_FILL = (200, 200, 210, 255)
TAG_FILL = (180, 180, 190, 220)

LINUX_FONTS = Path("/usr/share/fonts/truetype")
TITLE_CANDIDATES = [
    LINUX_FONTS / "dejavu" / "DejaVuSerif-Bold.ttf",
    LINUX_FONTS / "liberation" / "LiberationSerif-Bold.ttf",
    LINUX_FONTS / "dejavu" / "DejaVuSans-Bold.ttf",
]
TAG_CANDIDATES = [
    LINUX_FONTS / "dejavu" / "DejaVuSans-Bold.ttf",
    LINUX_FONTS / "liberation" / "LiberationSans-Bold.ttf",
]


def load(candidates, size):
    for p in candidates:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def vertical_gradient(size, top, bottom):
    img = Image.new("RGB", (size, size), top[:3])
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        for x in range(size):
            px[x, y] = (r, g, b)
    return img.convert("RGBA")


def main():
    img = vertical_gradient(SIZE, BG, BG_GRADIENT_END)
    draw = ImageDraw.Draw(img)

    # Outer thin border
    border_w = 8
    inset = 36
    draw.rectangle(
        [inset, inset, SIZE - inset - 1, SIZE - inset - 1],
        outline=BORDER, width=border_w,
    )

    # Decorative top + bottom small lines
    draw.line([(SIZE * 0.18, 130), (SIZE * 0.82, 130)], fill=BORDER, width=3)
    draw.line([(SIZE * 0.18, SIZE - 130), (SIZE * 0.82, SIZE - 130)], fill=BORDER, width=3)

    # Big "TCL" monogram center
    mono_font = load(TITLE_CANDIDATES, 360)
    mono = "TCL"
    bbox = draw.textbbox((0, 0), mono, font=mono_font)
    mw, mh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    mx = (SIZE - mw) // 2 - bbox[0]
    my = (SIZE - mh) // 2 - bbox[1] - 30
    # subtle drop shadow
    draw.text((mx + 6, my + 6), mono, font=mono_font, fill=(0, 0, 0, 180))
    draw.text((mx, my), mono, font=mono_font, fill=MONO_FILL)

    # Subtitle "THE CLAM LETTER" below monogram
    sub_font = load(TITLE_CANDIDATES, 60)
    sub = "THE CLAM LETTER"
    sb = draw.textbbox((0, 0), sub, font=sub_font)
    sw = sb[2] - sb[0]
    draw.text(((SIZE - sw) // 2 - sb[0], SIZE - 230), sub, font=sub_font, fill=MONO_FILL)

    # Tag line
    tag_font = load(TAG_CANDIDATES, 28)
    tag = "P O L I T I C A L   C O M M E N T A R Y"
    tb = draw.textbbox((0, 0), tag, font=tag_font)
    tw = tb[2] - tb[0]
    draw.text(((SIZE - tw) // 2 - tb[0], SIZE - 160), tag, font=tag_font, fill=TAG_FILL)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG", optimize=True)
    print(f"Saved: {OUT}  ({SIZE}x{SIZE})  size_bytes={OUT.stat().st_size}")


if __name__ == "__main__":
    main()
