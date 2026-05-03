#!/usr/bin/env python3
"""
sol_commands.py — Manual command listener for Sol Bot (@napoleotics).

The owner sends news to Sol's Telegram bot; Sol generates a tweet
using the full copywriting engine and optionally publishes it.

Usage via Telegram (owner only):
  <any text>              Treat as news title — generate tweet
  <title> | <context>    Title + extra context for richer generation
  /noticia <text>        Explicit news command (same as plain text)
  /publica               Publish the last generated pending tweet
  /publica x             Publish to X only
  /publica threads       Publish to Threads only
  /regenera              Regenerate last tweet with a different angle
  /wire                  Regenerate as breaking news (WIRE)
  /analisis              Regenerate as deep analysis (ANALISIS)
  /debate                Regenerate as debate/question (DEBATE)
  /conexion              Regenerate connecting macro dots (CONEXION)
  /status                Check if Sol is alive
  /ayuda                 Show available commands
"""

import json
import logging
import os
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from config import BASE_DIR, load_environment
from generator import generate_tweet
from telegram_client import send_message

load_environment()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PENDING_FILE = BASE_DIR / "pending_tweet.json"
MONITOR_PENDING_FILE = BASE_DIR / "monitor_pending.json"
BOT_DIR = str(BASE_DIR)

# Intent keywords → tweet type (only matched on SHORT text with pending tweet)
FORMAT_INTENTS = {
    "WIRE":     ["wire", "ultima hora", "última hora", "breaking", "flash"],
    "ANALISIS": ["analisis", "análisis", "analiza", "analizar", "profundo", "deep", "explica"],
    "DEBATE":   ["debate", "pregunta", "opinion", "opinión", "que piensas", "qué piensas"],
    "CONEXION": ["conexion", "conexión", "conecta", "macro", "relaciona", "el angulo", "el ángulo"],
}

REGEN_KEYWORDS = ["regenera", "regenerar", "otra vez", "de nuevo", "intenta de nuevo",
                  "cambia", "otro angulo", "otro ángulo", "diferente", "no me gusta"]

# Short confirmations that mean "generate from the last monitor headline"
CONFIRM_KEYWORDS = ["si", "sí", "dale", "ok", "okay", "genera", "generalo", "genéralo",
                    "genera un tweet", "genera el tweet", "genera un tweet de esto",
                    "hazlo", "adelante", "procede", "tweet", "twittea"]

# Feedback phrases that mean "you haven't published" or "that's wrong" — don't treat as news
FEEDBACK_NEGATIVE = ["no lo has publicado", "no publicaste", "no lo publicaste",
                     "no publico", "no publicó", "falta publicar", "no se publicó",
                     "no me gusta", "ese no", "no ese", "otro", "cambia"]


# ------------------------------------------------------------------
# Telegram polling helpers
# ------------------------------------------------------------------

def tg_api(method: str, payload: dict) -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/{method}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=35) as r:
        return json.loads(r.read().decode())


def get_updates(offset: int = 0) -> list:
    try:
        res = tg_api("getUpdates", {"offset": offset, "timeout": 30, "allowed_updates": ["message"]})
        return res.get("result", [])
    except Exception as e:
        logger.error(f"getUpdates error: {e}")
        return []


def _clean_monitor_text(text):
    """Remove monitor metadata from news text."""
    if not text:
        return text
    lns = text.split(chr(10))
    clean = []
    for ln in lns:
        s = ln.strip()
        # Skip monitor headers and source attributions
        if s.startswith("📡"):
            continue
        if s in ("BRICSNews", "WatcherGuru", "@BRICSNews", "@WatcherGuru"):
            continue
        if s.startswith("@-") and len(s) < 25:
            continue
        clean.append(ln)
    return chr(10).join(clean).strip()


def extract_reply_news(msg: dict) -> str | None:
    """Extract news text from any replied-to message."""
    reply = msg.get("reply_to_message", {})
    if not reply:
        return None
    original = reply.get("text") or reply.get("caption") or ""
    if not original or len(original.strip()) < 10:
        return None

    # Case 1: monitor message with Genero un tweet
    if "¿Genero un tweet?" in original or "Genero un tweet" in original:
        lines2 = original.split("\n\n")
        parts = [l for l in lines2 if l
                 and "Genero un tweet" not in l
                 and not l.startswith("📡")
                 and not l.startswith("@")
                 and l not in ("BRICSNews", "WatcherGuru", "@BRICSNews", "@WatcherGuru")]
        return "\n\n".join(parts).strip() if parts else None
    bot_skip = (
        "Publicando", "Generando", "Tweet generado", "Tweet [",
        "Publicado en", "Error en", "Error ", "Estado limpio",
        "Traduciendo", "Reintentando", "Sol Bot", "Comandos de Sol",
        "Regenerando", "Aqui estoy", "No hay", "Entendido",
    )
    stripped = original.strip()
    if any(stripped.startswith(p) for p in bot_skip):
        return None

    # Case 3: any other message - clean metadata and return
    return _clean_monitor_text(stripped)


# ------------------------------------------------------------------
# Command handlers
# ------------------------------------------------------------------

def cmd_status():
    pending = "ninguno"
    if PENDING_FILE.exists():
        try:
            p = json.loads(PENDING_FILE.read_text())
            ts = p.get("generated_at", "")[:16]
            preview = p.get("tweet", "")[:80]
            pending = f"({ts}) {preview}..."
        except Exception:
            pass
    send_message(f"Sol Bot operativo.\nPendiente: {pending}\nEnvia una noticia para generar un tweet.")


def detect_format_intent(text: str, has_pending: bool = False):
    """Return tweet_type if text is a format/regen request, else None.

    Free-text keyword matching only activates when:
    - There IS a pending tweet (so the user is clearly requesting a format change), AND
    - The text is SHORT (< 80 chars) — long text is almost always a news headline.
    Slash commands always work regardless.
    """
    lower = text.lower().strip()

    # Explicit slash commands always work
    if lower in ("/wire", "/urgente", "/breaking"):
        return "WIRE"
    if lower in ("/analisis", "/análisis"):
        return "ANALISIS"
    if lower in ("/debate",):
        return "DEBATE"
    if lower in ("/conexion", "/conexión"):
        return "CONEXION"
    if lower in ("/regenera", "/regenerar"):
        return "RANDOM"

    # Free-text keywords: only if there's a pending tweet AND text is short
    if not has_pending or len(text) >= 80:
        return None

    for tweet_type, keywords in FORMAT_INTENTS.items():
        for kw in keywords:
            if kw in lower:
                return tweet_type

    for kw in REGEN_KEYWORDS:
        if kw in lower:
            return "RANDOM"

    return None


def is_monitor_confirm(text: str) -> bool:
    """Return True if the user is confirming to generate from the last monitor headline."""
    lower = text.lower().strip()
    return any(lower == kw or lower.startswith(kw + " ") for kw in CONFIRM_KEYWORDS)


def cmd_regen(tweet_type: str = "RANDOM"):
    """Regenerate the last pending headline with a specific tweet type."""
    if not PENDING_FILE.exists():
        send_message("No hay noticia pendiente para regenerar. Envia una noticia primero.")
        return

    try:
        pending = json.loads(PENDING_FILE.read_text())
        headline = pending.get("headline")
        if not headline:
            send_message("No se encontro la noticia original. Envia la noticia de nuevo.")
            return
    except Exception as e:
        send_message(f"Error leyendo pendiente: {e}")
        return

    import random as _random
    if tweet_type == "RANDOM":
        tweet_type = _random.choice(["WIRE", "ANALISIS", "DEBATE", "CONEXION"])

    type_labels = {
        "WIRE": "Ultima Hora",
        "ANALISIS": "Analisis Profundo",
        "DEBATE": "Debate / Opinion",
        "CONEXION": "Conexion Macro",
    }
    send_message(f"Regenerando como {type_labels.get(tweet_type, tweet_type)}...")

    try:
        tweet = generate_tweet(headline, tweet_type=tweet_type, manual=True)
    except Exception as e:
        logger.error(f"regen error: {e}")
        send_message(f"Error regenerando: {e}")
        return

    pending["tweet"] = tweet
    pending["generated_at"] = datetime.now().isoformat()
    pending["tweet_type"] = tweet_type
    PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2))

    send_message(
        f"Tweet [{tweet_type}]:\n\n{tweet}\n\n"
        f"Responde /publica para publicar en X + Threads.\n"
        f"/publica x   — solo X\n"
        f"/publica threads   — solo Threads\n"
        f"/regenera   — otro angulo"
    )


def cmd_reset():
    """Clear all pending state."""
    PENDING_FILE.unlink(missing_ok=True)
    MONITOR_PENDING_FILE.unlink(missing_ok=True)
    send_message("Estado limpio. Envia una noticia para empezar de nuevo.")


def _translate_text(text: str) -> str:
    """Translate text to Spanish using the generator's API client."""
    from generator import _get_client, _call_api
    client, is_or = _get_client()
    model = "anthropic/claude-haiku-4-5" if is_or else "claude-haiku-4-5-20251001"
    system = "Eres un traductor. Traduce el texto al español de forma fiel y natural. No añadas comentarios ni explicaciones, solo la traducción."
    return _call_api(client, model, system, text, 300, is_or).strip()


def cmd_publish_translated(reply_news: str = None):
    """Translate the raw monitor headline to Spanish and publish as-is."""
    media_path = None
    media_type = "photo"
    text = None

    if reply_news:
        text = reply_news
        if MONITOR_PENDING_FILE.exists():
            try:
                data = json.loads(MONITOR_PENDING_FILE.read_text())
                media_path = data.get("media_path")
                media_type = data.get("media_type", "photo")
            except Exception:
                pass
    elif MONITOR_PENDING_FILE.exists():
        try:
            data = json.loads(MONITOR_PENDING_FILE.read_text())
            text = data["headline"]["title"]
            media_path = data.get("media_path")
            media_type = data.get("media_type", "photo")
        except Exception as e:
            send_message(f"Error leyendo noticia: {e}")
            return
    else:
        send_message("No hay noticia pendiente del monitor.")
        return

    if media_path and not os.path.exists(media_path):
        media_path = None

    send_message("Traduciendo...")
    try:
        translated = _translate_text(text)
    except Exception as e:
        send_message(f"Error traduciendo: {e}")
        return

    media_note = f" + {'video' if media_type == 'video' else 'imagen'}" if media_path else ""
    send_message(f"Publicando traducción{media_note}: {translated[:80]}...")

    if media_path:
        _publish_both(translated, media_path, media_type)
    else:
        _publish_both(translated)

    MONITOR_PENDING_FILE.unlink(missing_ok=True)


def cmd_publish_original(reply_news: str = None, target: str = "both"):
    """Publish the raw monitor headline as-is, no tweet generation."""
    media_path = None
    media_type = "photo"
    text = None

    if reply_news:
        text = reply_news
        if MONITOR_PENDING_FILE.exists():
            try:
                data = json.loads(MONITOR_PENDING_FILE.read_text())
                media_path = data.get("media_path")
                media_type = data.get("media_type", "photo")
            except Exception:
                pass
    elif MONITOR_PENDING_FILE.exists():
        try:
            data = json.loads(MONITOR_PENDING_FILE.read_text())
            text = data["headline"]["title"]
            media_path = data.get("media_path")
            media_type = data.get("media_type", "photo")
        except Exception as e:
            send_message(f"Error leyendo noticia del monitor: {e}")
            return
    else:
        send_message("No hay noticia pendiente del monitor.")
        return

    if media_path and not os.path.exists(media_path):
        media_path = None

    media_note = f" + {'video' if media_type == 'video' else 'imagen'}" if media_path else ""
    send_message(f"Publicando original{media_note}: {text[:80]}...")

    if target == "x":
        _publish_x(text, media_path, media_type)
    elif target == "threads":
        _publish_threads(text, media_path, media_type)
    elif media_path:
        _publish_both(text, media_path, media_type)
    else:
        _publish_both(text)

    MONITOR_PENDING_FILE.unlink(missing_ok=True)


def _load_media_from_pending(data: dict):
    """Extract media_paths and media_type from monitor_pending data. Returns (paths_list, type)."""
    media_type = data.get("media_type", "photo")
    # Prefer new media_paths list, fall back to single media_path
    paths = data.get("media_paths") or ([data["media_path"]] if data.get("media_path") else [])
    # Filter to paths that actually exist
    paths = [p for p in paths if os.path.exists(p)]
    return paths, media_type


def cmd_generate_from_monitor(reply_news: str = None, tweet_type: str = None):
    """Generate tweet from the last headline the monitor forwarded (or reply context)."""
    media_paths = []
    media_type = "photo"

    if reply_news:
        headline = {"title": reply_news, "summary": reply_news, "source": "reply", "url": ""}
        if MONITOR_PENDING_FILE.exists():
            try:
                data = json.loads(MONITOR_PENDING_FILE.read_text())
                media_paths, media_type = _load_media_from_pending(data)
            except Exception:
                pass
    elif MONITOR_PENDING_FILE.exists():
        try:
            data = json.loads(MONITOR_PENDING_FILE.read_text())
            headline = data.get("headline")
            media_paths, media_type = _load_media_from_pending(data)
            if not headline:
                send_message("No se encontro la noticia del monitor. Envíame el titular directamente.")
                return
        except Exception as e:
            send_message(f"Error leyendo noticia del monitor: {e}")
            return
    else:
        send_message("No hay noticia pendiente del monitor. Envíame el titular directamente.")
        return

    send_message(f"Generando tweet para:\n{headline['title'][:120]}...")

    try:
        tweet = generate_tweet(headline, tweet_type=tweet_type, manual=True)
    except Exception as e:
        logger.error(f"generate_tweet error: {e}")
        send_message(f"Error generando tweet: {e}")
        return

    pending = {
        "tweet": tweet,
        "headline": headline,
        "generated_at": datetime.now().isoformat(),
    }
    if media_paths:
        pending["media_paths"] = media_paths
        pending["media_path"] = media_paths[0]  # backward compat
        pending["media_type"] = media_type
    media_path = media_paths[0] if media_paths else None

    PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2))
    MONITOR_PENDING_FILE.unlink(missing_ok=True)

    if media_paths:
        n = len(media_paths)
        label = "video" if media_type == "video" else (f"{n} imagenes" if n > 1 else "imagen")
        media_note = f"\n📎 Con {label} adjunto."
    else:
        media_note = ""
    send_message(
        f"Tweet generado:{media_note}\n\n{tweet}\n\n"
        f"Responde /publica para publicar en X + Threads.\n"
        f"/publica x   — solo X\n"
        f"/publica threads   — solo Threads\n"
        f"/regenera   — otro angulo"
    )


def cmd_ayuda():
    send_message(
        "Comandos de Sol Bot:\n\n"
        "GENERAR:\n"
        "  <noticia>      Genera tweet desde titular\n"
        "  titulo | contexto  Con contexto extra\n\n"
        "FORMATO (regenera el ultimo tweet):\n"
        "  /wire          Ultima hora / breaking\n"
        "  /analisis      Analisis profundo\n"
        "  /debate        Pregunta / opinion\n"
        "  /conexion      Angulo macro\n"
        "  /regenera      Otro angulo aleatorio\n\n"
        "PUBLICAR:\n"
        "  /publica       X + Threads\n"
        "  /publica x     Solo X\n"
        "  /publica threads  Solo Threads\n\n"
        "PUBLICAR SIN GENERAR:\n"
        "  /original      Publica original en X + Threads\n"
        "  /xo             Solo X original\n"
        "  /to             Solo Threads original\n"
        "  /traduce       Traduce al espanol y publica\n\n"
        "SCHEDULER:\n"
        "  /publica 1  publica tweet 1 del scheduler\n"
        "  /publica 2  publica tweet 2\n\n"
        "  /status        Estado del bot\n"
        "  /ayuda         Este menu"
    )


def cmd_generate(text: str):
    text = text.strip()

    # Strip /noticia prefix if present
    if text.lower().startswith("/noticia"):
        text = text[8:].strip()

    if len(text) < 10:
        send_message("Noticia muy corta. Envia el titulo completo (minimo 10 caracteres).")
        return

    # Parse "title | context" format
    if "|" in text:
        parts = text.split("|", 1)
        title = parts[0].strip()
        context = parts[1].strip()
    else:
        title = text
        context = text  # use full text as context too

    headline = {
        "title": title,
        "summary": context,
        "source": "manual",
        "url": "",
    }

    send_message(f"Generando tweet para:\n{title[:120]}...")

    try:
        tweet = generate_tweet(headline, tweet_type=None, manual=True)
    except Exception as e:
        logger.error(f"generate_tweet error: {e}")
        send_message(f"Error generando tweet: {e}")
        return

    # Check if monitor_pending has media matching this headline
    _media_paths = []
    _media_type = "photo"
    if MONITOR_PENDING_FILE.exists():
        try:
            _mp_data = json.loads(MONITOR_PENDING_FILE.read_text())
            _mp_title = _mp_data.get("headline", {}).get("title", "")
            # Match if headline text overlaps significantly
            if _mp_title and (title in _mp_title or _mp_title in title
                    or len(set(title.lower().split()) & set(_mp_title.lower().split())) >= 3):
                _media_paths, _media_type = _load_media_from_pending(_mp_data)
                if _media_paths:
                    logger.info(f"Media recovered from monitor_pending: {len(_media_paths)} files")
        except Exception:
            pass

    # Save pending tweet
    pending = {
        "tweet": tweet,
        "headline": headline,
        "generated_at": datetime.now().isoformat(),
    }
    if _media_paths:
        pending["media_paths"] = _media_paths
        pending["media_path"] = _media_paths[0]
        pending["media_type"] = _media_type
    PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2))

    send_message(
        f"Tweet generado:\n\n{tweet}\n\n"
        f"Responde /publica para publicar en X + Threads.\n"
        f"/publica x   — solo X\n"
        f"/publica threads   — solo Threads"
    )



def cmd_publish_from_sched(n: int):
    sched_file = BASE_DIR / f'pending_sched_{n}.json'
    if not sched_file.exists():
        all_sched = sorted(BASE_DIR.glob('pending_sched_*.json'))
        if not all_sched:
            send_message(f'No hay tweet {n} del scheduler. Espera el proximo ciclo.')
        else:
            nums = [f.stem.replace("pending_sched_", "") for f in all_sched]
            send_message(f'No existe tweet {n}. Disponibles: {", ".join(nums)}')
        return
    try:
        data = json.loads(sched_file.read_text())
    except Exception as e:
        send_message(f'Error leyendo tweet {n}: {e}')
        return
    PENDING_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    sched_file.unlink(missing_ok=True)
    tweet = data.get("tweet", "")
    media_type = data.get("media_type", "photo")
    raw_paths = data.get("media_paths") or ([data["media_path"]] if data.get("media_path") else [])
    media_paths = [p for p in raw_paths if os.path.exists(p)]
    media_path = media_paths[0] if media_paths else None
    if media_paths:
        label = "video" if media_type == "video" else (f"{len(media_paths)} imagenes" if len(media_paths) > 1 else "imagen")
        media_note = f" + {label}"
    else:
        media_note = ""
    send_message(f"Publicando tweet {n}{media_note}: {tweet[:80]}...")
    _publish_both(tweet, media_path, media_type, media_paths=media_paths)
    PENDING_FILE.unlink(missing_ok=True)


def cmd_publish(args: str = ""):
    if not PENDING_FILE.exists():
        send_message("No hay tweet pendiente. Envia una noticia primero.")
        return

    try:
        pending = json.loads(PENDING_FILE.read_text())
        tweet = pending["tweet"]
        media_type = pending.get("media_type", "photo")
        # Support both old single media_path and new media_paths list
        raw_paths = pending.get("media_paths") or ([pending["media_path"]] if pending.get("media_path") else [])
        media_paths = [p for p in raw_paths if os.path.exists(p)]
        media_path = media_paths[0] if media_paths else None
    except Exception as e:
        send_message(f"Error leyendo tweet pendiente: {e}")
        return

    target = args.strip().lower()  # "x", "threads", or "" (both)

    if media_paths:
        n = len(media_paths)
        label = "video" if media_type == "video" else (f"{n} imagenes" if n > 1 else "imagen")
        media_note = f" + {label}"
    else:
        media_note = ""
    send_message(f"Publicando{media_note}: {tweet[:80]}...")

    if target == "x":
        _publish_x(tweet, media_path, media_type, media_paths=media_paths)
    elif target == "threads":
        _publish_threads(tweet, media_path, media_type)
    else:
        _publish_both(tweet, media_path, media_type, media_paths=media_paths)

    # Clear pending
    PENDING_FILE.unlink(missing_ok=True)


def _publish_x(tweet: str, media_path: str = None, media_type: str = "photo", media_paths: list = None):
    cmd = ["node", os.path.join(BOT_DIR, "post_thread.js")]
    if media_type == "video" and media_path:
        cmd += ["--video", media_path]
    elif media_paths and len(media_paths) > 1:
        # Multiple images: --images img1.jpg,img2.jpg
        cmd += ["--images", ",".join(media_paths)]
    elif media_path:
        cmd += ["--image", media_path]
    cmd.append(tweet)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=BOT_DIR)
        if r.returncode == 0:
            send_message("Publicado en X.")
        else:
            send_message(f"Error en X:\n{r.stderr[-400:]}")
    except subprocess.TimeoutExpired:
        send_message("Timeout publicando en X (>3 min).")
    except Exception as e:
        send_message(f"Error X: {e}")


def _publish_threads(tweet: str, media_path: str = None, media_type: str = "photo"):
    cmd = ["python3", os.path.join(BOT_DIR, "threads_publisher.py")]
    if media_path:
        flag = "--video" if media_type == "video" else "--image"
        cmd += [flag, media_path]
    cmd.append(tweet)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=BOT_DIR)
        if r.returncode == 0:
            send_message("Publicado en Threads.")
        else:
            send_message(f"Error en Threads:\n{r.stderr[-400:]}")
    except subprocess.TimeoutExpired:
        send_message("Timeout publicando en Threads.")
    except Exception as e:
        send_message(f"Error Threads: {e}")


def _publish_both(tweet, media_path=None, media_type="photo", media_paths=None):
    results = []
    # --- X ---
    cmd = ["node", os.path.join(BOT_DIR, "post_thread.js")]
    if media_type == "video" and media_path:
        cmd += ["--video", media_path]
    elif media_paths and len(media_paths) > 1:
        cmd += ["--images", ",".join(media_paths)]
    elif media_path:
        cmd += ["--image", media_path]
    cmd.append(tweet)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=BOT_DIR)
        results.append("X: Publicado" if r.returncode == 0 else f"X: Error {r.stderr[-200:]}")
    except subprocess.TimeoutExpired:
        results.append("X: Timeout")
    except Exception as e:
        results.append(f"X: Error {e}")
    # --- Threads ---
    cmd2 = ["python3", os.path.join(BOT_DIR, "threads_publisher.py"), "--quiet"]
    if media_path:
        flag = "--video" if media_type == "video" else "--image"
        cmd2 += [flag, media_path]
    cmd2.append(tweet)
    try:
        r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=60, cwd=BOT_DIR)
        results.append("Threads: Publicado" if r2.returncode == 0 else f"Threads: Error {r2.stderr[-200:]}")
    except subprocess.TimeoutExpired:
        results.append("Threads: Timeout")
    except Exception as e:
        results.append(f"Threads: Error {e}")
    send_message("Publicacion dual:\n- " + "\n- ".join(results))

# ------------------------------------------------------------------
# Main dispatch
# ------------------------------------------------------------------

def handle_message(text: str, reply_news: str = None):
    text = text.strip()
    lower = text.lower()

    # ── Slash commands (always exact match first) ────────────────────
    if lower.startswith("/status"):
        cmd_status()
    elif lower.startswith("/publica"):
        args = text[8:].strip()
        # /publica 1  or /publica 2 -> publish scheduler tweet
        if args.isdigit():
            cmd_publish_from_sched(int(args))
        else:
            cmd_publish(args)
    elif lower.startswith("/noticia"):
        cmd_generate(text)
    elif lower.startswith("/ayuda") or lower.startswith("/help") or lower.startswith("/commands") or lower.startswith("/comandos"):
        cmd_ayuda()
    elif lower in ("/reset", "/limpiar", "/clear"):
        cmd_reset()
    elif lower in ("/original", "/reenviar", "/asis"):
        cmd_publish_original(reply_news=reply_news)
    elif lower in ("/original x", "/publica xo", "/xo"):
        cmd_publish_original(reply_news=reply_news, target="x")
    elif lower in ("/original threads", "/publica to", "/to"):
        cmd_publish_original(reply_news=reply_news, target="threads")
    elif lower in ("/traduce", "/traducir", "/translate"):
        cmd_publish_translated(reply_news=reply_news)
    elif lower in ("/wire", "/urgente", "/breaking", "/analisis", "/análisis",
                   "/debate", "/conexion", "/conexión", "/regenera", "/regenerar"):
        tweet_type = detect_format_intent(text, has_pending=True)
        if reply_news:
            cmd_generate_from_monitor(reply_news=reply_news, tweet_type=tweet_type or "WIRE")
        else:
            cmd_regen(tweet_type or "RANDOM")

    # ── Free text ────────────────────────────────────────────────────
    else:
        has_pending = PENDING_FILE.exists()

        # 1. "publica este [texto]" — publish command without slash
        if lower.startswith("publica ") or lower == "publica":
            args = text[7:].strip().lstrip("este").strip()
            # "publica 1" or "publica 2" -> publish scheduler tweet
            if args.isdigit():
                cmd_publish_from_sched(int(args))
            else:
                cmd_publish(args)

        # 2. Negative feedback → don't hallucinate, ask what to do
        elif any(fb in lower for fb in FEEDBACK_NEGATIVE):
            if has_pending:
                send_message(
                    "Entendido. ¿Qué quieres hacer?\n\n"
                    "/publica — publicar el tweet actual\n"
                    "/regenera — otro ángulo\n"
                    "/wire /analisis /debate /conexion — cambiar formato\n"
                    "/reset — empezar de nuevo"
                )
            else:
                send_message("No hay tweet pendiente. Envíame una noticia para generar uno.")

        # 3. Reply to monitor message OR short confirmation → generate from that headline
        elif reply_news or (is_monitor_confirm(text) and not has_pending):
            cmd_generate_from_monitor(reply_news=reply_news)

        # 4. Format/regen intent (only if pending tweet exists + text is short)
        elif detect_format_intent(text, has_pending=has_pending):
            fmt = detect_format_intent(text, has_pending=has_pending)
            cmd_regen(fmt)

        # 5. Short greeting → acknowledge, don't treat as news
        elif len(text) < 10 and any(g in lower for g in ["hola", "hey", "hi", "test", "buenas", "ola"]):
            pending_info = "Hay un tweet pendiente de publicar." if has_pending else "No hay noticia pendiente."
            monitor_info = " Hay una noticia del monitor lista." if MONITOR_PENDING_FILE.exists() else ""
            send_message(f"Aquí estoy. {pending_info}{monitor_info}\n/ayuda para ver comandos.")

        # 6. Everything else → treat as a new news headline
        else:
            cmd_generate(text)


def main():
    owner_chat_id = str(os.getenv("TELEGRAM_CHAT_ID", ""))
    offset = 0

    logger.info("Sol commands listener started")

    while True:
        updates = get_updates(offset)

        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text = msg.get("text", "") or msg.get("caption", "")

            if chat_id != owner_chat_id:
                logger.debug(f"Ignored message from chat {chat_id}")
                continue

            if text:
                try:
                    reply_news = extract_reply_news(msg)
                    handle_message(text, reply_news=reply_news)
                except Exception as e:
                    logger.error(f"Error handling message: {e}")
                    send_message(f"Error interno: {e}")

        time.sleep(1)


if __name__ == "__main__":
    main()
