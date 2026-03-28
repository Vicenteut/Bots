"""
sol_bridge.py — Bridge from Armandito to Sol Bot.

Allows Armandito to control Sol: generate tweets, publish, and check status.
Sol Bot lives at ../sol-bot/; this module imports it directly.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SOL_DIR = Path(__file__).resolve().parent.parent / "sol-bot"
PENDING_FILE = SOL_DIR / "pending_tweet.json"


def _sol_python(script_args: list[str], input_data: str | None = None, timeout: int = 60) -> tuple[bool, str]:
    """Run a Python command inside sol-bot's directory."""
    env = os.environ.copy()
    # Make sure sol-bot modules are importable
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{SOL_DIR}:{pythonpath}" if pythonpath else str(SOL_DIR)

    result = subprocess.run(
        [sys.executable] + script_args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(SOL_DIR),
        env=env,
        input=input_data,
    )
    ok = result.returncode == 0
    output = (result.stdout + result.stderr).strip()
    return ok, output


def sol_generate(text: str) -> str:
    """
    Generate a tweet from a news headline/text.

    Returns the generated tweet text, or raises on error.
    """
    # Use a small inline script so we don't need to touch sol-bot's files
    script = f"""
import sys
sys.path.insert(0, "{SOL_DIR}")
from generator import generate_tweet

headline = {{
    "title": {json.dumps(text)},
    "summary": {json.dumps(text)},
    "source": "armandito",
    "url": "",
}}
tweet = generate_tweet(headline)

# Save as pending for /publica
import json
from pathlib import Path
pending = {{
    "tweet": tweet,
    "headline": headline,
    "generated_at": "{datetime.now().isoformat()}",
}}
Path("{PENDING_FILE}").write_text(json.dumps(pending, ensure_ascii=False, indent=2))

print(tweet)
"""
    ok, output = _sol_python(["-c", script], timeout=90)
    if not ok or not output:
        raise RuntimeError(output or "Error desconocido generando tweet")
    return output


def sol_publish(target: str = "") -> str:
    """
    Publish the pending tweet.

    target: "" = both X+Threads, "x" = X only, "threads" = Threads only.
    Returns a status message.
    """
    if not PENDING_FILE.exists():
        return "No hay tweet pendiente. Genera uno primero con: sol: <titular>"

    try:
        pending = json.loads(PENDING_FILE.read_text())
        tweet = pending["tweet"]
    except Exception as e:
        return f"Error leyendo tweet pendiente: {e}"

    target = target.strip().lower()

    if target == "x":
        script_file = "post_thread.js"
        cmd = ["node", str(SOL_DIR / script_file), tweet]
        platform_label = "X"
    elif target == "threads":
        cmd = [sys.executable, str(SOL_DIR / "threads_publisher.py"), tweet]
        platform_label = "Threads"
    else:
        cmd = [sys.executable, str(SOL_DIR / "publish_dual.py"), tweet]
        platform_label = "X y Threads"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(SOL_DIR),
            env=os.environ.copy(),
        )
        if result.returncode == 0:
            PENDING_FILE.unlink(missing_ok=True)
            return f"Publicado en {platform_label}.\n\n{tweet[:120]}"
        else:
            err = (result.stderr or result.stdout or "")[-400:]
            return f"Error publicando en {platform_label}:\n{err}"
    except subprocess.TimeoutExpired:
        return f"Timeout publicando en {platform_label} (>3 min)."
    except Exception as e:
        return f"Error: {e}"


def sol_status() -> str:
    """Return Sol's current status and pending tweet info."""
    if not PENDING_FILE.exists():
        return "Sol Bot operativo.\nSin tweet pendiente.\n\nEnvia: sol: <titular> para generar uno."

    try:
        p = json.loads(PENDING_FILE.read_text())
        ts = p.get("generated_at", "")[:16]
        tweet = p.get("tweet", "")
        headline = p.get("headline", {}).get("title", "")[:80]
        return (
            f"Sol Bot operativo.\n\n"
            f"Tweet pendiente ({ts}):\n{tweet}\n\n"
            f"Noticia: {headline}\n\n"
            f"Responde 'sol publica' para publicar en X + Threads."
        )
    except Exception as e:
        return f"Sol operativo pero error leyendo pendiente: {e}"
