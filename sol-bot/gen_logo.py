"""Generate transparent PNG logo for The Clam Letter overlay (Linux/VPS variant)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "assets" / "reels" / "logo.png"
W, H = 900, 240

LINUX_FONTS = Path("/usr/share/fonts/truetype")
TITLE_FONT_CANDIDATES = [
    LINUX_FONTS / "dejavu" / "DejaVuSerif-Bold.ttf",
    LINUX_FONTS / "liberation" / "LiberationSerif-Bold.ttf",
    LINUX_FONTS / "dejavu" / "DejaVuSans-Bold.ttf",
]
TAG_FONT_CANDIDATES = [
    LINUX_FONTS / "dejavu" / "DejaVuSans.ttf",
    LINUX_FONTS / "liberation" / "LiberationSans-Regular.ttf",
]


def load(candidates, size):
    for p in candidates:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def main():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    title = "THE CLAM LETTER"
    tag = "P O L I T I C A L   C O M M E N T A R Y"

    title_font = load(TITLE_FONT_CANDIDATES, 68)
    tag_font = load(TAG_FONT_CANDIDATES, 20)

    tw, th = draw.textbbox((0, 0), title, font=title_font)[2:]
    title_y = 50
    draw.text(((W - tw) // 2, title_y), title, font=title_font, fill=(255, 255, 255, 255))

    gw, gh = draw.textbbox((0, 0), tag, font=tag_font)[2:]
    draw.text(((W - gw) // 2, title_y + th + 22), tag, font=tag_font, fill=(220, 220, 220, 230))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(f"Logo saved: {OUT} ({W}x{H})")


if __name__ == "__main__":
    main()
