"""Bridge between Armandito and Sol-bot."""
import json
import os
import re
import subprocess
from pathlib import Path

SOL_BOT_DIR = Path(__file__).resolve().parent.parent / "sol-bot"
PENDING_FILE = Path(__file__).resolve().parent.parent / "sol_pending.json"


def get_pending_drafts() -> list:
    """Read pending tweet drafts saved by sol-bot's scheduler."""
    if not PENDING_FILE.exists():
        return []
    try:
        with open(PENDING_FILE) as f:
            data = json.load(f)
        return data.get("drafts", [])
    except Exception:
        return []


def _remove_draft(index: int) -> None:
    """Remove a draft by 1-based index from the pending file."""
    drafts = get_pending_drafts()
    if 1 <= index <= len(drafts):
        drafts.pop(index - 1)
    if drafts:
        try:
            with open(PENDING_FILE, "w") as f:
                json.dump({"drafts": drafts}, f)
        except Exception:
            pass
    else:
        try:
            PENDING_FILE.unlink(missing_ok=True)
        except Exception:
            pass


def publish_draft(index: int) -> str:
    """Publish a pending draft by its 1-based index."""
    drafts = get_pending_drafts()
    if not drafts:
        return "No hay borradores pendientes de Sol. Usa 'sol run' para generar nuevos."
    if index < 1 or index > len(drafts):
        return f"Numero invalido. Hay {len(drafts)} borrador(es) (1-{len(drafts)})."

    draft = drafts[index - 1]
    tweet_text = draft.get("tweet", "")
    image_path = draft.get("image_path")

    if not tweet_text:
        return "El borrador no tiene texto."

    cmd = ["python3", str(SOL_BOT_DIR / "publish_dual.py")]
    if image_path and os.path.exists(image_path):
        cmd.extend(["--image", image_path])
    cmd.append(tweet_text)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=str(SOL_BOT_DIR)
        )
        if result.returncode == 0:
            _remove_draft(index)
            output = result.stdout.strip()
            summary = output[-300:] if len(output) > 300 else output
            return f"Publicado en X y Threads.\n{summary}"
        else:
            err = (result.stderr or result.stdout or "").strip()
            return f"Error al publicar:\n{err[:300]}"
    except subprocess.TimeoutExpired:
        return "Timeout al publicar (2 min). Intenta de nuevo."
    except Exception as e:
        return f"Error: {str(e)[:100]}"


def run_analytics() -> str:
    """Run sol-bot analytics tracker and return the report."""
    try:
        result = subprocess.run(
            ["python3", str(SOL_BOT_DIR / "analytics_tracker.py")],
            capture_output=True, text=True, timeout=60, cwd=str(SOL_BOT_DIR)
        )
        output = result.stdout.strip()
        if output:
            clean = re.sub(r"<[^>]+>", "", output)
            return clean[:1000] if len(clean) > 1000 else clean
        return "No se pudo obtener el reporte de analytics."
    except subprocess.TimeoutExpired:
        return "Timeout obteniendo analytics."
    except Exception as e:
        return f"Error: {str(e)[:100]}"


def run_scheduler() -> str:
    """Run sol-bot scheduler to generate new tweet drafts."""
    try:
        result = subprocess.run(
            ["python3", str(SOL_BOT_DIR / "scheduler.py")],
            capture_output=True, text=True, timeout=300, cwd=str(SOL_BOT_DIR)
        )
        drafts = get_pending_drafts()
        if drafts:
            lines = [f"Sol genero {len(drafts)} borrador(es):\n"]
            for d in drafts:
                i = d.get("index", drafts.index(d) + 1)
                text = d.get("tweet", "")[:120]
                src = d.get("source", "")
                lines.append(f"{i}. {text}...\n   Fuente: {src}")
            lines.append(f'\nDi "publica N" para publicar el borrador N.')
            return "\n".join(lines)
        output = result.stdout.strip()
        return output[:400] if output else "Scheduler ejecutado. Sin borradores nuevos."
    except subprocess.TimeoutExpired:
        return "Timeout ejecutando scheduler (5 min)."
    except Exception as e:
        return f"Error: {str(e)[:100]}"


def get_status() -> str:
    """Get sol-bot status and pending drafts."""
    env_ok = (SOL_BOT_DIR / ".env").exists()
    drafts = get_pending_drafts()

    lines = [
        "Estado de Sol:",
        f"  Config: {'OK' if env_ok else 'Sin .env en sol-bot/'}",
        f"  Borradores pendientes: {len(drafts)}",
    ]

    if drafts:
        lines.append("\nBorradores:")
        for d in drafts:
            i = d.get("index", drafts.index(d) + 1)
            text = d.get("tweet", "")[:80]
            lines.append(f"  {i}. {text}...")
        lines.append(f'\nDi "publica N" para publicar.')

    return "\n".join(lines)
