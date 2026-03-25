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
  /status                Check if Sol is alive
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
BOT_DIR = str(BASE_DIR)


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
        tweet = generate_tweet(headline)
    except Exception as e:
        logger.error(f"generate_tweet error: {e}")
        send_message(f"Error generando tweet: {e}")
        return

    # Save pending tweet
    pending = {
        "tweet": tweet,
        "headline": headline,
        "generated_at": datetime.now().isoformat(),
    }
    PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2))

    send_message(
        f"Tweet generado:\n\n{tweet}\n\n"
        f"Responde /publica para publicar en X + Threads.\n"
        f"/publica x   — solo X\n"
        f"/publica threads   — solo Threads"
    )


def cmd_publish(args: str = ""):
    if not PENDING_FILE.exists():
        send_message("No hay tweet pendiente. Envia una noticia primero.")
        return

    try:
        pending = json.loads(PENDING_FILE.read_text())
        tweet = pending["tweet"]
    except Exception as e:
        send_message(f"Error leyendo tweet pendiente: {e}")
        return

    target = args.strip().lower()  # "x", "threads", or "" (both)

    send_message(f"Publicando: {tweet[:80]}...")

    if target == "x":
        _publish_x(tweet)
    elif target == "threads":
        _publish_threads(tweet)
    else:
        _publish_both(tweet)

    # Clear pending
    PENDING_FILE.unlink(missing_ok=True)


def _publish_x(tweet: str):
    try:
        r = subprocess.run(
            ["node", os.path.join(BOT_DIR, "post_thread.js"), tweet],
            capture_output=True, text=True, timeout=180, cwd=BOT_DIR,
        )
        if r.returncode == 0:
            send_message("Publicado en X.")
        else:
            send_message(f"Error en X:\n{r.stderr[-400:]}")
    except subprocess.TimeoutExpired:
        send_message("Timeout publicando en X (>3 min).")
    except Exception as e:
        send_message(f"Error X: {e}")


def _publish_threads(tweet: str):
    try:
        r = subprocess.run(
            ["python3", os.path.join(BOT_DIR, "threads_publisher.py"), tweet],
            capture_output=True, text=True, timeout=60, cwd=BOT_DIR,
        )
        if r.returncode == 0:
            send_message("Publicado en Threads.")
        else:
            send_message(f"Error en Threads:\n{r.stderr[-400:]}")
    except subprocess.TimeoutExpired:
        send_message("Timeout publicando en Threads.")
    except Exception as e:
        send_message(f"Error Threads: {e}")


def _publish_both(tweet: str):
    try:
        r = subprocess.run(
            ["python3", os.path.join(BOT_DIR, "publish_dual.py"), tweet],
            capture_output=True, text=True, timeout=180, cwd=BOT_DIR,
        )
        if r.returncode == 0:
            send_message("Publicado en X y Threads.")
        else:
            send_message(f"Error publicando:\n{r.stderr[-400:]}")
    except subprocess.TimeoutExpired:
        send_message("Timeout publicando (>3 min).")
    except Exception as e:
        send_message(f"Error: {e}")


# ------------------------------------------------------------------
# Main dispatch
# ------------------------------------------------------------------

def handle_message(text: str):
    text = text.strip()

    if text.startswith("/status"):
        cmd_status()
    elif text.startswith("/publica"):
        args = text[8:].strip()
        cmd_publish(args)
    elif text.startswith("/noticia"):
        cmd_generate(text)
    else:
        # Any plain text = treat as news
        cmd_generate(text)


def main():
    owner_chat_id = str(os.getenv("TELEGRAM_CHAT_ID", ""))
    offset = 0

    logger.info("Sol commands listener started")
    send_message("Sol Bot listo para recibir noticias. Envia cualquier titular para generar un tweet.")

    while True:
        updates = get_updates(offset)

        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text = msg.get("text", "")

            if chat_id != owner_chat_id:
                logger.debug(f"Ignored message from chat {chat_id}")
                continue

            if text:
                try:
                    handle_message(text)
                except Exception as e:
                    logger.error(f"Error handling message: {e}")
                    send_message(f"Error interno: {e}")

        time.sleep(1)


if __name__ == "__main__":
    main()
