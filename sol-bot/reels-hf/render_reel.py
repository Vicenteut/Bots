#!/usr/bin/env python3
"""
render_reel.py — Hyperframes reel renderer with templating.

Reads a JSON file with reel content (label, hook, stat1/2/3, bg) and renders
an MP4 using the template at templates/reel.html.

Usage:
    python render_reel.py news_examples/fed.json
    python render_reel.py news_examples/fed.json --output out/fed.mp4
    python render_reel.py --help

The script:
1. Loads the JSON input
2. Reads templates/reel.html
3. Substitutes {{LABEL}}, {{HOOK}}, {{STAT1-3}}, {{BG}} placeholders
4. Writes to index.html (the file Hyperframes renders by default)
5. Calls `npx hyperframes render`
6. Reports the path to the produced MP4
"""

from __future__ import annotations

import argparse
import html as html_module
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Force UTF-8 stdout on Windows (default cp1252 can't print Unicode like ✓ ❌)
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# ----- Paths (resolved relative to this script's location) -----
SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = SCRIPT_DIR / "templates" / "reel.html"
INDEX_PATH = SCRIPT_DIR / "index.html"
RENDERS_DIR = SCRIPT_DIR / "renders"
ASSETS_DIR = SCRIPT_DIR / "assets"

# ----- Required fields in the input JSON -----
REQUIRED_FIELDS = ("label", "hook", "stat1", "stat2", "stat3", "bg")

# ----- Constraints (matching the visual layout) -----
MAX_LENGTHS = {
    "label": 12,
    "hook": 80,
    "stat1": 80,
    "stat2": 80,
    "stat3": 80,
}


def validate_input(data: dict) -> None:
    """Raise ValueError if input is missing fields or violates constraints."""
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")

    bg = data["bg"]
    bg_path = ASSETS_DIR / bg
    if not bg_path.exists():
        available = sorted(p.name for p in ASSETS_DIR.glob("*.mp4"))
        raise ValueError(
            f"Background video not found: assets/{bg}\n"
            f"Available: {available}"
        )

    for field, max_len in MAX_LENGTHS.items():
        value = data[field]
        if not isinstance(value, str):
            raise ValueError(f"Field '{field}' must be a string, got {type(value)}")
        if len(value) > max_len:
            print(
                f"⚠️  {field} is {len(value)} chars (max {max_len}). "
                f"It may overflow the visible area.",
                file=sys.stderr,
            )


def render_template(template_text: str, vars_dict: dict) -> str:
    """Substitute {{KEY}} placeholders in `template_text` with values from `vars_dict`.

    All values are HTML-escaped to prevent injection. The 'bg' value is also
    quote-escaped because it goes into an attribute (src=).
    """
    result = template_text
    for key, value in vars_dict.items():
        if not isinstance(value, str):
            continue
        # Escape HTML special chars (<, >, &, ", ')
        safe_value = html_module.escape(value, quote=True)
        placeholder = "{{" + key.upper() + "}}"
        result = result.replace(placeholder, safe_value)
    return result


def render_reel(input_json_path: Path, output_path: Path | None = None) -> Path:
    """Render a reel from a JSON input file. Returns the path to the produced MP4."""
    # Load input
    with input_json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    validate_input(data)

    # Auto-derive tts filename from input JSON name: centcom_hypersonic.json → tts_centcom_hypersonic.mp3
    json_stem = input_json_path.stem
    data["tts"] = f"tts_{json_stem}.mp3"
    tts_path = ASSETS_DIR / data["tts"]
    if not tts_path.exists():
        print(
            f"⚠️  TTS file not found: assets/{data['tts']}\n"
            f"   Generate it with: edge-tts --voice en-US-ChristopherNeural "
            f"--rate=+5% --pitch=-2Hz --text \"<your text>\" "
            f"--write-media assets/{data['tts']}",
            file=sys.stderr,
        )

    # Read template
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template not found: {TEMPLATE_PATH}")
    template_text = TEMPLATE_PATH.read_text(encoding="utf-8")

    # Substitute and write to index.html
    rendered_html = render_template(template_text, data)
    INDEX_PATH.write_text(rendered_html, encoding="utf-8")

    print(f"✓ Wrote {INDEX_PATH.relative_to(SCRIPT_DIR)} with substituted values")
    print(f"  bg:    {data['bg']}")
    print(f"  hook:  {data['hook']}")
    print(f"  label: {data['label']}")

    # Call hyperframes render
    # Note any pre-existing MP4s so we can detect what's NEW from this render
    pre_existing = {p.resolve() for p in RENDERS_DIR.glob("*.mp4")} if RENDERS_DIR.exists() else set()
    started_at = __import__("time").time()

    print("\n→ Running `npx hyperframes render`...")
    # shell=True is needed on Windows because npx is npx.cmd, NOT on Linux/Mac
    # (shell=True with a list on POSIX runs only `sh -c <first_arg>`, dropping the rest).
    use_shell = (os.name == "nt")
    result = subprocess.run(
        ["npx", "hyperframes", "render"],
        cwd=SCRIPT_DIR,
        shell=use_shell,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"hyperframes render failed with code {result.returncode}")

    # Find the NEW MP4 produced by THIS render (not any leftover from prior runs)
    all_mp4s = sorted(RENDERS_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    new_mp4s = [p for p in all_mp4s if p.resolve() not in pre_existing and p.stat().st_mtime >= started_at - 1]
    if not new_mp4s:
        raise RuntimeError(
            f"No NEW MP4 produced in {RENDERS_DIR} after render. "
            "Something failed silently in npx hyperframes."
        )
    latest = new_mp4s[-1]

    # Optionally rename/move to the output path
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(latest), str(output_path))
        latest = output_path

    return latest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a reel from a JSON input using the Hyperframes template.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n  python render_reel.py news_examples/fed.json -o out/fed.mp4",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to the JSON file with reel content",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Optional explicit output path. If omitted, MP4 stays in renders/",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"❌ Input file not found: {args.input}", file=sys.stderr)
        return 1

    try:
        output = render_reel(args.input, args.output)
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    print(f"\n✅ Reel ready: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
