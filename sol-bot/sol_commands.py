#!/usr/bin/env python3
"""
sol_commands.py — Manual command listener for Sol Bot (@napoleotics).

The owner sends news to Sol's Telegram bot; Sol generates a Threads post
using the full copywriting engine and optionally publishes it.

Usage via Telegram (owner only):
  <any text>              Treat as news title — generate post
  <title> | <context>    Title + extra context for richer generation
  /noticia <text>        Explicit news command (same as plain text)
  /publica               Publish the last generated pending post to Threads
  /publica threads       Publish to Threads
  /regenera              Regenerate last post with a different angle
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
import re
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from config import BASE_DIR, load_environment
from brain import call_brain, log_brain_action
from generator import generate_tweet, generate_combinada_tweet
from telegram_client import send_message
from topic_utils import classify_topic

load_environment()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Also write to file so the dashboard SSE log strip can tail it
_LOG_FILE = Path("/root/x-bot/logs/sol_commands.log")
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
_fh = logging.FileHandler(_LOG_FILE)
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logging.getLogger().addHandler(_fh)


def _atomic_write_json(path: Path, data) -> None:
    """Write JSON atomically using a temp file + os.replace to prevent corruption on crash."""
    tmp = path.parent / f".tmp_{path.name}"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


PENDING_FILE = BASE_DIR / "pending_tweet.json"
COMBO_FILE = BASE_DIR / "pending_combo.json"
MONITOR_PENDING_FILE = BASE_DIR / "monitor_pending.json"
PENDING_MEDIA_FILE = BASE_DIR / "pending_media.json"
PENDING_NEWS_FILE = BASE_DIR / "pending_news_text.txt"
MEDIA_DIR = BASE_DIR / "media"
PID_FILE = BASE_DIR / "sol_commands.pid"
BOT_DIR = str(BASE_DIR)
THREADS_POST_MAX_CHARS = 500

# Intent keywords -> post format (only matched on SHORT text with pending post)
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
                    "genera un post", "genera el post", "genera un post de esto",
                    "hazlo", "adelante", "procede", "post", "publica"]

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
        res = tg_api("getUpdates", {"offset": offset, "timeout": 30, "allowed_updates": ["message", "callback_query"]})
        return res.get("result", [])
    except Exception as e:
        logger.error(f"getUpdates error: {e}")
        return []


def send_generation_keyboard(news_preview: str):
    """Send an inline keyboard asking the owner which type of post to generate."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": f"Noticia guardada:\n{news_preview[:120]}{'...' if len(news_preview) > 120 else ''}\n\n¿Qué tipo de post?",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "🧩 Mixed", "callback_data": "gen_mixed"},
                {"text": "📰 Original", "callback_data": "gen_original"},
                {"text": "⚡ Generate", "callback_data": "gen_sol"},
            ]]
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        logger.error(f"send_generation_keyboard error: {e}")


def send_publish_keyboard(tweet_preview: str = "", media_note: str = ""):
    """Send the pending post with Publish / Regen / Cancel inline buttons."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    text = (
        f"{'📎 Con media adjunta.' + chr(10) if media_note else ''}"
        f"Tweet listo:{chr(10)}"
        f"{tweet_preview[:200] + '...' if len(tweet_preview) > 200 else tweet_preview}"
    )
    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "🧵 Publicar en Threads", "callback_data": "pub_threads"},
                ],
                [
                    {"text": "🔄 Regenerar", "callback_data": "btn_regen"},
                    {"text": "❌ Cancelar",  "callback_data": "btn_cancel"},
                ],
            ]
        },
    }
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        logger.error(f"send_publish_keyboard error: {e}")


def _get_media_status(media_path=None, tg_media_url=None) -> str:
    """Return the appropriate upload-status message based on media type."""
    path = media_path or tg_media_url or ""
    if not path:
        return "📤 Publicando..."
    if ".mp4" in path.lower() or "video" in path.lower():
        return "🎬 Subiendo con video..."
    return "📸 Subiendo con imagen..."


def _tg_download_media(file_id: str, media_type: str) -> dict | None:
    """Call Telegram getFile, download file locally, return metadata dict or None on failure."""
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        res = tg_api("getFile", {"file_id": file_id})
        file_path = res["result"]["file_path"]
        tg_file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"

        ext = os.path.splitext(file_path)[1] or (".jpg" if media_type == "photo" else ".mp4")
        MEDIA_DIR.mkdir(exist_ok=True)
        local_name = f"owner_{media_type}_{int(time.time())}{ext}"
        local_path = str(MEDIA_DIR / local_name)

        urllib.request.urlretrieve(tg_file_url, local_path)
        logger.info(f"Downloaded TG {media_type}: {local_path}")
        return {"local_path": local_path, "tg_file_url": tg_file_url, "media_type": media_type}
    except Exception as e:
        logger.error(f"Failed to download TG media (file_id={file_id}): {e}")
        return None


def handle_media_message(msg: dict, media_type: str):
    """Handle incoming photo or video sent directly by the owner."""
    caption = (msg.get("caption") or "").strip()

    if media_type == "photo":
        photos = msg.get("photo", [])
        if not photos:
            return
        file_id = photos[-1]["file_id"]  # largest size is last
    else:
        video = msg.get("video") or {}
        file_id = video.get("file_id", "")
        if not file_id:
            return

    label = "foto" if media_type == "photo" else "video"
    send_message(f"Descargando {label}...")

    media_info = _tg_download_media(file_id, media_type)
    if not media_info:
        send_message(f"Error descargando {label}. Intenta de nuevo.")
        return

    _atomic_write_json(PENDING_MEDIA_FILE, media_info)

    if caption:
        # Save caption as news text and show generation keyboard (media auto-attaches on generation)
        cmd_generate(caption)
    else:
        Label = "Foto" if media_type == "photo" else "Video"
        send_message(f"{Label} guardada ✅. Envía la noticia o /publica cuando estés listo.")


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


def _headlines_match(a: str, b: str) -> bool:
    """Return True if two headline strings refer to the same news item.

    Accepts exact match, substring containment, or ≥50% word overlap of the
    shorter headline.  Replaces the old "≥3 shared words" heuristic which was
    too loose (common words like "US / the / in" caused false positives).
    """
    if not a or not b:
        return False
    a_c, b_c = a.lower().strip(), b.lower().strip()
    if a_c == b_c or a_c in b_c or b_c in a_c:
        return True
    a_w = set(a_c.split())
    b_w = set(b_c.split())
    shorter = min(len(a_w), len(b_w))
    return shorter > 0 and len(a_w & b_w) / shorter >= 0.5


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
    send_message(f"Sol Bot operativo.\nPendiente: {pending}\nEnvia una noticia para generar un post.")


def detect_format_intent(text: str, has_pending: bool = False):
    """Return tweet_type if text is a format/regen request, else None.

    Free-text keyword matching only activates when:
    - There IS a pending post (so the user is clearly requesting a format change), AND
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

    # Free-text keywords: only if there's a pending post AND text is short
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


def cmd_regen(tweet_type: str = "RANDOM", instruction: str = ""):
    """Regenerate the last pending headline with a specific post format."""
    if not PENDING_FILE.exists():
        send_message("No hay post pendiente para regenerar.")
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

    if instruction:
        headline["instruction"] = instruction

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

    send_publish_keyboard(tweet)


def cmd_mixed(text: str = "", reply_news: str = None, target: str = "both"):
    """Generate WIRE + ANALISIS from the same headline and preview both before publishing."""
    # --- Resolve headline ---
    headline = None
    if reply_news:
        headline = {"title": reply_news, "summary": reply_news, "source": "reply", "url": ""}
    elif text and len(text) >= 10:
        if "|" in text:
            parts = text.split("|", 1)
            title, context = parts[0].strip(), parts[1].strip()
        else:
            title = context = text.strip()
        headline = {"title": title, "summary": context, "source": "manual", "url": ""}
    elif PENDING_FILE.exists():
        try:
            headline = json.loads(PENDING_FILE.read_text()).get("headline")
        except Exception:
            pass
    elif MONITOR_PENDING_FILE.exists():
        try:
            data = json.loads(MONITOR_PENDING_FILE.read_text())
            headline = data.get("headline")
            logger.info(f"[cmd_mixed] MONITOR_PENDING_FILE headline: {headline}")
        except Exception as e:
            logger.warning(f"[cmd_mixed] Failed to read MONITOR_PENDING_FILE: {e}")
    elif COMBO_FILE.exists():
        try:
            headline = json.loads(COMBO_FILE.read_text()).get("headline")
        except Exception:
            pass

    if not headline:
        send_message(
            "Necesito una noticia. Opciones:\n"
            "  /mixed <titular>\n"
            "  Responde a un titular del monitor con /mixed\n"
            "  O genera un post primero con /noticia"
        )
        return

    target_label = "Threads"
    send_message(f"Generando mixed ({target_label})...")

    try:
        tweet = generate_combinada_tweet(headline, manual=True)
    except Exception as e:
        logger.error(f"mixed error: {e}")
        send_message(f"Error generando mixed: {e}")
        return

    # Extract media from the pending source (if any)
    media_paths_combo = []
    media_type_combo = "photo"
    for src_file in (PENDING_FILE, MONITOR_PENDING_FILE):
        if src_file.exists():
            try:
                src_data = json.loads(src_file.read_text())
                _paths, _type = _load_media_from_pending(src_data)
                if _paths:
                    media_paths_combo = _paths
                    media_type_combo = _type
                    break
            except Exception:
                pass

    combo_payload = {
        "tweet": tweet,
        "headline": headline,
        "generated_at": datetime.now().isoformat(),
        "default_target": target,
    }
    if media_paths_combo:
        combo_payload["media_paths"] = media_paths_combo
        combo_payload["media_path"] = media_paths_combo[0]
        combo_payload["media_type"] = media_type_combo
    COMBO_FILE.write_text(json.dumps(combo_payload, ensure_ascii=False, indent=2))

    send_publish_keyboard(tweet)


def cmd_reset():
    """Clear all pending state."""
    PENDING_FILE.unlink(missing_ok=True)
    COMBO_FILE.unlink(missing_ok=True)
    logger.warning("[MONITOR_PENDING_FILE] Deleting in cmd_reset()")
    MONITOR_PENDING_FILE.unlink(missing_ok=True)
    PENDING_MEDIA_FILE.unlink(missing_ok=True)
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
                pending_title = data.get("headline", {}).get("title", "")
                if _headlines_match(reply_news, pending_title):
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

    _publish_threads(translated, media_path, media_type)

    logger.warning("[MONITOR_PENDING_FILE] Deleting in cmd_publish_translated()")
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
                pending_title = data.get("headline", {}).get("title", "")
                if _headlines_match(reply_news, pending_title):
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

    _publish_threads(text, media_path, media_type)

    logger.warning("[MONITOR_PENDING_FILE] Deleting in cmd_publish_original()")
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
                pending_title = data.get("headline", {}).get("title", "")
                if _headlines_match(reply_news, pending_title):
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

    send_message(f"Generando post para:\n{headline['title'][:120]}...")

    try:
        tweet = generate_tweet(headline, tweet_type=tweet_type, manual=True)
    except Exception as e:
        logger.error(f"generate_tweet error: {e}")
        send_message(f"Error generando post: {e}")
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
    logger.warning("[MONITOR_PENDING_FILE] Deleting in cmd_generate_from_monitor()")
    MONITOR_PENDING_FILE.unlink(missing_ok=True)

    media_note = "x" if media_paths else ""
    send_publish_keyboard(tweet, media_note=media_note)


def cmd_ayuda():
    send_message(
        "Comandos de Sol Bot:\n\n"
        "GENERAR:\n"
        "  <noticia>      Genera post desde titular\n"
        "  titulo | contexto  Con contexto extra\n\n"
        "FORMATO (regenera el ultimo post):\n"
        "  /wire          Ultima hora / breaking\n"
        "  /analisis      Analisis profundo\n"
        "  /debate        Pregunta / opinion\n"
        "  /conexion      Angulo macro\n"
        "  /regenera      Otro angulo aleatorio\n"
        "  /mixed         WIRE + ANALISIS en secuencia\n"
        "  /mixed threads Solo Threads\n\n"
        "PUBLICAR:\n"
        "  /publica       Publica en Threads\n"
        "  /publica threads  Publica en Threads\n\n"
        "PUBLICAR SIN GENERAR:\n"
        "  /original      Publica original en Threads\n"
        "  /to             Solo Threads original\n"
        "  /traduce       Traduce al espanol y publica\n\n"
        "SCHEDULER:\n"
        "  /publica 1  publica post 1 del scheduler\n"
        "  /publica 2  publica post 2\n\n"
        "  /status        Estado del bot\n"
        "  /ayuda         Este menu"
    )


def cmd_generate(text: str):
    """Receive news text, save it, and ask the owner which type of post to generate."""
    text = text.strip()

    # Strip /noticia prefix if present
    if text.lower().startswith("/noticia"):
        text = text[8:].strip()

    if len(text) < 10:
        send_message("Noticia muy corta. Envia el titulo completo (minimo 10 caracteres).")
        return

    PENDING_NEWS_FILE.write_text(text, encoding="utf-8")
    send_generation_keyboard(text)


def _do_generate(text: str):
    """Actually generate a Sol analysis tweet from already-validated news text."""
    # Parse "title | context" format
    if "|" in text:
        parts = text.split("|", 1)
        title = parts[0].strip()
        context = parts[1].strip()
    else:
        title = text
        context = text

    headline = {
        "title": title,
        "summary": context,
        "source": "manual",
        "url": "",
    }

    send_message(f"Generando post para:\n{title[:120]}...")

    try:
        tweet = generate_tweet(headline, tweet_type=None, manual=True)
    except Exception as e:
        logger.error(f"generate_tweet error: {e}")
        send_message(f"Error generando post: {e}")
        return

    # Check if monitor_pending has media matching this headline
    _media_paths = []
    _media_type = "photo"
    if MONITOR_PENDING_FILE.exists():
        try:
            _mp_data = json.loads(MONITOR_PENDING_FILE.read_text())
            _mp_title = _mp_data.get("headline", {}).get("title", "")
            if _mp_title and _headlines_match(title, _mp_title):
                _media_paths, _media_type = _load_media_from_pending(_mp_data)
                if _media_paths:
                    logger.info(f"Media recovered from monitor_pending: {len(_media_paths)} files")
        except Exception:
            pass

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

    # Auto-attach any pending owner media (sent before the news text)
    media_note = ""
    if PENDING_MEDIA_FILE.exists() and not _media_paths:
        try:
            pm = json.loads(PENDING_MEDIA_FILE.read_text())
            pending["media_path"] = pm["local_path"]
            pending["media_paths"] = [pm["local_path"]]
            pending["media_type"] = pm["media_type"]
            pending["tg_media_url"] = pm["tg_file_url"]
            PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2))
            PENDING_MEDIA_FILE.unlink(missing_ok=True)
            label = "video" if pm["media_type"] == "video" else "imagen"
            media_note = f"\n📎 Con {label} adjunta."
            logger.info(f"Auto-attached owner media: {pm['local_path']}")
        except Exception as e:
            logger.error(f"Error attaching pending media: {e}")

    send_publish_keyboard(tweet, media_note=media_note)



def cmd_publish_from_sched(n: int):
    sched_file = BASE_DIR / f'pending_sched_{n}.json'
    if not sched_file.exists():
        all_sched = sorted(BASE_DIR.glob('pending_sched_*.json'))
        if not all_sched:
            send_message(f'No hay post {n} del scheduler. Espera el proximo ciclo.')
        else:
            nums = [f.stem.replace("pending_sched_", "") for f in all_sched]
            send_message(f'No existe tweet {n}. Disponibles: {", ".join(nums)}')
        return
    try:
        data = json.loads(sched_file.read_text())
    except Exception as e:
        send_message(f'Error leyendo post {n}: {e}')
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
    send_message(f"Publicando post {n}{media_note}: {tweet[:80]}...")
    _publish_threads(tweet, media_path, media_type, media_paths=media_paths)
    PENDING_FILE.unlink(missing_ok=True)


def cmd_publish(args: str = ""):
    if COMBO_FILE.exists():
        _publish_combo(args)
        return

    if not PENDING_FILE.exists():
        send_message("No hay post pendiente. Envia una noticia primero.")
        return

    try:
        pending = json.loads(PENDING_FILE.read_text())
        tweet = pending["tweet"]
        media_type = pending.get("media_type", "photo")
        # Support both old single media_path and new media_paths list
        raw_paths = pending.get("media_paths") or ([pending["media_path"]] if pending.get("media_path") else [])
        media_paths = [p for p in raw_paths if os.path.exists(p)]
        media_path = media_paths[0] if media_paths else None
        tg_media_url = pending.get("tg_media_url")
    except Exception as e:
        send_message(f"Error leyendo post pendiente: {e}")
        return

    # Also check PENDING_MEDIA_FILE as fallback if no media in pending post
    if not media_path and PENDING_MEDIA_FILE.exists():
        try:
            pm = json.loads(PENDING_MEDIA_FILE.read_text())
            media_path = pm["local_path"] if os.path.exists(pm.get("local_path", "")) else None
            tg_media_url = pm.get("tg_file_url")
            media_type = pm.get("media_type", "photo")
            if media_path:
                media_paths = [media_path]
        except Exception:
            pass

    target = args.strip().lower()  # Legacy args are ignored; publishing is Threads-only.

    if media_paths:
        n = len(media_paths)
        label = "video" if media_type == "video" else (f"{n} imagenes" if n > 1 else "imagen")
        media_note = f" + {label}"
    else:
        media_note = ""
    send_message(f"Publicando{media_note}: {tweet[:80]}...")

    _publish_threads(tweet, media_path, media_type, tg_media_url=tg_media_url, media_paths=media_paths)

    for f in [PENDING_MEDIA_FILE] + list(MEDIA_DIR.glob("owner_*")):
        try:
            if f.exists():
                f.unlink()
        except (OSError, FileNotFoundError) as e:
            logger.warning(f"[cleanup] Could not delete {f}: {e}")

    # Clear pending
    PENDING_FILE.unlink(missing_ok=True)

    # Clean up Telegram-sourced owner media
    if tg_media_url and media_path and os.path.exists(media_path):
        try:
            os.unlink(media_path)
            logger.info(f"Deleted TG owner media file: {media_path}")
        except Exception as e:
            logger.warning(f"Could not delete TG media file: {e}")
    PENDING_MEDIA_FILE.unlink(missing_ok=True)


def _extract_threads_result(output: str) -> dict:
    result = {}
    for line in (output or "").splitlines():
        if line.startswith("[THREADS_RESULT]"):
            try:
                parsed = json.loads(line.split("]", 1)[1].strip())
                if isinstance(parsed, dict):
                    result = parsed
            except Exception:
                pass
    return result


def _media_kind(media_type: str, media_paths: list) -> str:
    if media_type == "video" and media_paths:
        return "video"
    if len(media_paths) > 1:
        return "carousel"
    if len(media_paths) == 1:
        return "image"
    return "text"


def _classify_publish_result(output: str, returncode: int, media_kind: str) -> dict:
    parsed = _extract_threads_result(output)
    post_id = parsed.get("post_id") if parsed else None
    success = returncode == 0 and bool(post_id or parsed.get("success"))
    category = parsed.get("category") if parsed else None
    message = parsed.get("message") if parsed else None
    if not success and not category:
        lower = (output or "").lower()
        if "token" in lower or "permission" in lower or "unauthorized" in lower:
            category = "AUTH_ERROR"
        elif "content-type" in lower or "media url" in lower or "no valid image" in lower or "container failed" in lower:
            category = "MEDIA_ERROR"
        elif "timed out" in lower or "timeout" in lower:
            category = "TIMEOUT"
        elif "http error" in lower or "meta error" in lower or "fbtrace_id" in lower:
            category = "META_ERROR"
        else:
            category = "FAILED"
    if not message and not success:
        lines = [ln.strip() for ln in (output or "").splitlines() if ln.strip()]
        interesting = [ln for ln in lines if "[ERROR]" in ln or "[META ERROR]" in ln or "Container failed" in ln]
        message = (interesting[-1] if interesting else (lines[-1] if lines else "Threads publish failed"))
    return {
        "success": success,
        "post_id": post_id,
        "status": "OK" if success else (category or "FAILED"),
        "error_category": None if success else category,
        "error_message": None if success else message,
        "fbtrace_id": parsed.get("fbtrace_id") if parsed else None,
        "public_media_urls": parsed.get("media_urls") if isinstance(parsed.get("media_urls"), list) else [],
        "media_kind": parsed.get("media_type") or media_kind,
    }


def _append_publish_log(platform: str, success: bool, tweet: str, tweet_id: str = None,
                         tweet_type: str = None, model_used: str = None,
                         has_media: bool = False, media_type: str = "text",
                         media_count: int = 0, status: str = None,
                         error_category: str = None, error_message: str = None,
                         fbtrace_id: str = None, public_media_urls: list = None):
    """Append one publish event to logs/publish_log.json. Never raises."""
    try:
        import tempfile
        log_path = BASE_DIR.parent / "logs" / "publish_log.json"
        entry = {
            "published_at": datetime.now().isoformat(),
            "platform": platform,
            "success": success,
            "tweet_id": tweet_id,
            "text_preview": (tweet or "")[:80],
            "tweet_type": tweet_type,
            "topic_tag": classify_topic(tweet),
            "model_used": model_used,
            "char_count": len(tweet) if tweet else 0,
            "has_media": has_media,
            "media_type": media_type,
            "media_count": media_count,
            "status": status or ("OK" if success else "FAILED"),
            "error_category": error_category,
            "error_message": (error_message or "")[:500] if error_message else None,
            "fbtrace_id": fbtrace_id,
            "public_media_urls": public_media_urls or [],
        }
        if log_path.exists():
            try:
                history = json.loads(log_path.read_text())
                if not isinstance(history, list):
                    history = []
            except Exception:
                history = []
        else:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            history = []
        history.append(entry)
        # Atomic write: write to temp file then rename to avoid corruption on crash
        fd, tmp = tempfile.mkstemp(dir=str(log_path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(history, ensure_ascii=False, indent=2))
            os.replace(tmp, str(log_path))
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
    except Exception as e:
        logger.error(f"[publish_log] Failed to append entry: {e}")


def _read_pending_meta() -> tuple:
    """Return (tweet_type, model_used) from pending_tweet.json, or (None, None)."""
    try:
        if PENDING_FILE.exists():
            p = json.loads(PENDING_FILE.read_text())
            return p.get("tweet_type"), p.get("model_used")
    except Exception:
        pass
    return None, None


def _publish_threads(tweet: str, media_path: str = None, media_type: str = "photo", tg_media_url: str = None, media_paths: list = None):
    tweet_type, model_used = _read_pending_meta()
    media_paths = media_paths or ([media_path] if media_path else [])
    media_paths = [p for p in media_paths if p]
    media_kind = _media_kind(media_type, media_paths)
    if len(tweet) > THREADS_POST_MAX_CHARS:
        send_message(f"Post demasiado largo para Threads: {len(tweet)}/{THREADS_POST_MAX_CHARS} chars. Regenera antes de publicar.")
        _append_publish_log("threads", False, tweet, tweet_type=tweet_type, model_used=model_used,
                            media_type=media_kind, media_count=len(media_paths),
                            status="VALIDATION_ERROR", error_category="VALIDATION_ERROR",
                            error_message=f"Post too long: {len(tweet)}/{THREADS_POST_MAX_CHARS}")
        return False
    primary_media = tg_media_url or (media_paths[0] if media_paths else media_path)
    send_message(_get_media_status(primary_media, tg_media_url))

    cmd = ["python3", os.path.join(BOT_DIR, "threads_publisher.py"), "--quiet"]
    if media_type == "video" and primary_media:
        cmd += ["--video", primary_media]
    elif tg_media_url:
        cmd += ["--image", tg_media_url]
    else:
        for mp in media_paths:
            cmd += ["--image", mp]
    cmd.append(tweet)

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=360 if media_type == "video" else 120, cwd=BOT_DIR)
        combined_output = (r.stdout or "") + (r.stderr or "")
        parsed_result = _classify_publish_result(combined_output, r.returncode, media_kind)
        if r.returncode == 0 and parsed_result["success"]:
            if "[ERROR]" in (r.stdout or ""):
                logger.warning(f"Threads media issue: {r.stdout[:300]}")
            m = re.search(r"ID:\s*(\d+)", r.stdout or "")
            post_id = parsed_result["post_id"] or (m.group(1) if m else None)
            _append_publish_log("threads", True, tweet, tweet_id=post_id,
                                  tweet_type=tweet_type, model_used=model_used,
                                  has_media=bool(media_paths), media_type=parsed_result["media_kind"],
                                  media_count=len(media_paths), status="OK",
                                  public_media_urls=parsed_result["public_media_urls"])
            send_message("Publicado en Threads.")
            for f in [PENDING_MEDIA_FILE] + list(MEDIA_DIR.glob("owner_*")):
                try:
                    if f.exists():
                        f.unlink()
                except (OSError, FileNotFoundError) as e:
                    logger.warning(f"[cleanup] Could not delete {f}: {e}")
            return True

        combined = (r.stdout or "")[-500:] + "\n" + (r.stderr or "")[-500:]
        _append_publish_log("threads", False, tweet, tweet_type=tweet_type, model_used=model_used,
                            has_media=bool(media_paths), media_type=parsed_result["media_kind"],
                            media_count=len(media_paths), status=parsed_result["status"],
                            error_category=parsed_result["error_category"],
                            error_message=parsed_result["error_message"],
                            fbtrace_id=parsed_result["fbtrace_id"],
                            public_media_urls=parsed_result["public_media_urls"])
        short_error = parsed_result["error_message"] or combined.strip()[-400:]
        trace = f"\nfbtrace_id: {parsed_result['fbtrace_id']}" if parsed_result.get("fbtrace_id") else ""
        send_message(f"Error en Threads [{parsed_result['status']}]:\n{short_error[:400]}{trace}")
        return False
    except subprocess.TimeoutExpired:
        _append_publish_log("threads", False, tweet, tweet_type=tweet_type, model_used=model_used,
                            has_media=bool(media_paths), media_type=media_kind,
                            media_count=len(media_paths), status="TIMEOUT",
                            error_category="TIMEOUT",
                            error_message="Timeout publicando en Threads")
        send_message("Timeout publicando en Threads.")
        return False
    except Exception as e:
        _append_publish_log("threads", False, tweet, tweet_type=tweet_type, model_used=model_used,
                            has_media=bool(media_paths), media_type=media_kind,
                            media_count=len(media_paths), status="FAILED",
                            error_category="FAILED", error_message=str(e))
        send_message(f"Error Threads: {e}")
        return False


def _publish_both(tweet, media_path=None, media_type="photo", media_paths=None, tg_media_url=None):
    """Compatibility wrapper: legacy dual calls publish Threads only."""
    return _publish_threads(tweet, media_path=media_path, media_type=media_type,
                            tg_media_url=tg_media_url, media_paths=media_paths)


def _publish_combo(args: str = ""):
    """Publish a single mixed post from pending_combo.json to Threads only."""
    try:
        data = json.loads(COMBO_FILE.read_text())
    except Exception as e:
        send_message(f"Error leyendo combo pendiente: {e}")
        return

    tweet = data.get("tweet", "")
    media_paths, media_type = _load_media_from_pending(data)
    media_path = media_paths[0] if media_paths else None

    _publish_threads(tweet, media_path=media_path, media_type=media_type, media_paths=media_paths)

    COMBO_FILE.unlink(missing_ok=True)
    send_message("Mixed publicado en Threads.")
    for f in [PENDING_MEDIA_FILE] + list(MEDIA_DIR.glob("owner_*")):
        try:
            if f.exists():
                f.unlink()
        except (OSError, FileNotFoundError) as e:
            logger.warning(f"[cleanup] Could not delete {f}: {e}")


# ------------------------------------------------------------------
# Brain dispatch
# ------------------------------------------------------------------

def _dispatch_brain_action(action: str, instruction: str, text: str, reply_news: str = None):
    """Map a brain-classified action to the appropriate command function."""
    pending_exists = PENDING_FILE.exists() or COMBO_FILE.exists()

    if action == "generate_sol":
        cmd_generate(text)  # preserves keyboard UX — user picks type after

    elif action == "generate_mixed":
        cmd_mixed(text, reply_news=reply_news)

    elif action == "generate_original":
        cmd_publish_original(reply_news=reply_news)

    elif action in ("publish", "publish_threads_only"):
        if not pending_exists:
            send_message("No hay nada pendiente para publicar. ¿Querés generar algo primero?")
            return
        if action == "publish_threads_only":
            target = "threads"
        else:
            target = "threads"
        cmd_publish(target)

    elif action == "regenerate":
        if not PENDING_FILE.exists():
            send_message("No hay post pendiente para regenerar.")
            return
        cmd_regen("RANDOM")

    elif action == "regenerate_with_instruction":
        if not PENDING_FILE.exists():
            send_message("No hay post pendiente para regenerar.")
            return
        cmd_regen("RANDOM", instruction=instruction)

    elif action == "cancel":
        cmd_reset()

    else:  # unknown
        send_message("No entendí. ¿Qué querés hacer?\n/ayuda para ver comandos disponibles.")


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
        # /publica 1  or /publica 2 -> publish scheduler post
        if args.isdigit():
            cmd_publish_from_sched(int(args))
            log_brain_action("publish", text)
        else:
            cmd_publish(args)
            _pub_action = "publish_threads_only"
            log_brain_action(_pub_action, text)
    elif lower.startswith("/noticia"):
        cmd_generate(text)
        log_brain_action("generate_sol", text)
    elif lower.startswith("/ayuda") or lower.startswith("/help") or lower.startswith("/commands") or lower.startswith("/comandos"):
        cmd_ayuda()
    elif lower in ("/reset", "/limpiar", "/clear"):
        cmd_reset()
        log_brain_action("cancel", text)
    elif lower in ("/original", "/reenviar", "/asis"):
        cmd_publish_original(reply_news=reply_news)
        log_brain_action("generate_original", text)
    elif lower in ("/original threads", "/publica to", "/to"):
        cmd_publish_original(reply_news=reply_news, target="threads")
        log_brain_action("publish_threads_only", text)
    elif lower in ("/traduce", "/traducir", "/translate"):
        cmd_publish_translated(reply_news=reply_news)
        log_brain_action("generate_original", text)
    elif lower.startswith("/mixed"):
        parts = text.split()
        target = "threads"
        if len(parts) > 1 and parts[1].lower() in ("threads", "thread"):
            target = "threads"
        # Any remaining text after the command (and optional platform flag) is the inline headline
        skip = 1 + (1 if len(parts) > 1 and parts[1].lower() in ("threads", "thread") else 0)
        inline = " ".join(parts[skip:]).strip()
        cmd_mixed(inline, reply_news=reply_news, target=target)
        log_brain_action("generate_mixed", text)
    elif lower in ("/wire", "/urgente", "/breaking", "/analisis", "/análisis",
                   "/debate", "/conexion", "/conexión", "/regenera", "/regenerar"):
        tweet_type = detect_format_intent(text, has_pending=True)
        if reply_news:
            cmd_generate_from_monitor(reply_news=reply_news, tweet_type=tweet_type or "WIRE")
        else:
            cmd_regen(tweet_type or "RANDOM")
        log_brain_action("regenerate", text)

    # ── Free text → brain classifies intent ─────────────────────────
    else:
        result = call_brain(text, reply_news=reply_news)
        _dispatch_brain_action(result["action"], result["instruction"], text, reply_news)


def main():
    # --- PID lock: prevent duplicate instances ---
    if PID_FILE.exists():
        try:
            existing_pid = int(PID_FILE.read_text().strip())
            os.kill(existing_pid, 0)  # signal 0 = check existence only
            logger.error(
                f"sol_commands already running (PID {existing_pid}). "
                "Kill it first or remove sol_commands.pid."
            )
            return
        except (ProcessLookupError, ValueError):
            logger.warning("Stale PID file found — overwriting.")
    PID_FILE.write_text(str(os.getpid()))
    # ---

    owner_chat_id = str(os.getenv("TELEGRAM_CHAT_ID", ""))
    offset = 0

    logger.info("Sol commands listener started")

    try:
        while True:
            updates = get_updates(offset)

            for update in updates:
                offset = update["update_id"] + 1

                # ── Inline keyboard button press ──────────────────────────
                if "callback_query" in update:
                    cq = update["callback_query"]
                    cq_id = cq["id"]
                    cq_chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
                    callback_data = cq.get("data", "")
                    # Always answer to remove the loading spinner
                    try:
                        tg_api("answerCallbackQuery", {"callback_query_id": cq_id})
                    except Exception as e:
                        logger.warning(f"answerCallbackQuery error: {e}")
                    if cq_chat_id != owner_chat_id:
                        logger.debug(f"Ignored callback from chat {cq_chat_id}")
                        continue
                    news_text = ""
                    if PENDING_NEWS_FILE.exists():
                        try:
                            news_text = PENDING_NEWS_FILE.read_text(encoding="utf-8").strip()
                            PENDING_NEWS_FILE.unlink(missing_ok=True)
                        except Exception as e:
                            logger.error(f"Error reading pending news: {e}")
                    if callback_data == "gen_sol":
                        if news_text:
                            _do_generate(news_text)
                        else:
                            send_message("No hay noticia guardada. Envía el titular de nuevo.")
                    elif callback_data == "gen_mixed":
                        if news_text:
                            cmd_mixed(news_text)
                        else:
                            send_message("No hay noticia guardada. Envía el titular de nuevo.")
                    elif callback_data == "gen_original":
                        cmd_publish_original()
                    elif callback_data == "pub_threads":
                        cmd_publish("threads")
                    elif callback_data == "btn_regen":
                        cmd_regen("RANDOM")
                    elif callback_data == "btn_cancel":
                        cmd_reset()
                    elif callback_data == "mon_generate":
                        cmd_generate_from_monitor()
                    elif callback_data == "mon_mixed":
                        if MONITOR_PENDING_FILE.exists():
                            try:
                                _mpd = json.loads(MONITOR_PENDING_FILE.read_text())
                                _hl = _mpd.get("headline", {})
                                _title = _hl.get("title", "") if isinstance(_hl, dict) else str(_hl)
                                cmd_mixed(_title)
                            except Exception:
                                cmd_mixed("", reply_news=None)
                        else:
                            send_message("No hay noticia pendiente del monitor. Envíame el titular directamente.")
                    elif callback_data == "mon_original":
                        cmd_publish_original()
                    elif callback_data == "mon_ignore":
                        logger.warning("[MONITOR_PENDING_FILE] Deleting in mon_ignore callback")
                        MONITOR_PENDING_FILE.unlink(missing_ok=True)
                        send_message("Noticia ignorada. 🚫")
                    continue

                # ── Regular message ───────────────────────────────────────
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "") or msg.get("caption", "")

                if chat_id != owner_chat_id:
                    logger.debug(f"Ignored message from chat {chat_id}")
                    continue

                # Handle incoming photo or video from owner
                if msg.get("photo") or msg.get("video"):
                    media_type = "video" if msg.get("video") else "photo"
                    try:
                        handle_media_message(msg, media_type)
                    except Exception as e:
                        logger.error(f"Error handling media: {e}")
                        send_message(f"Error procesando media: {e}")
                    continue  # Caption is handled inside handle_media_message; skip text re-processing

                if text:
                    try:
                        reply_news = extract_reply_news(msg)
                        handle_message(text, reply_news=reply_news)
                    except Exception as e:
                        logger.error(f"Error handling message: {e}")
                        send_message(f"Error interno: {e}")

            time.sleep(1)
    finally:
        PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
