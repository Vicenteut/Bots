#!/usr/bin/env python3
"""
content_calendar.py — Reactive content calendar for Sol Bot.
Implements weighted day-based type selection + breaking news override.
FIXED: Now passes SYSTEM_PROMPT to all Claude API calls.
"""

import random
import logging
from datetime import datetime

from config import load_environment, get_env, get_required_env
from telegram_client import send_message
from generator import SYSTEM_PROMPT, get_model, _detect_topic, _get_client, _call_api
from memory import get_memory

load_environment()

logger = logging.getLogger(__name__)

ANTHROPIC_KEY = get_env("ANTHROPIC_API_KEY")
DAY_NAMES_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# ------------------------------------------------------------------
# Reactive day weights — probability per post format per day
# ------------------------------------------------------------------

DAY_WEIGHTS = {
    0: {"ANALISIS": 0.60, "DEBATE": 0.20, "CONEXION": 0.15, "WIRE": 0.05},  # Mon
    1: {"WIRE": 0.30, "DEBATE": 0.35, "ANALISIS": 0.25, "CONEXION": 0.10},  # Tue
    2: {"ANALISIS": 0.40, "CONEXION": 0.35, "DEBATE": 0.15, "WIRE": 0.10},  # Wed
    3: {"DEBATE": 0.40, "ANALISIS": 0.35, "CONEXION": 0.15, "WIRE": 0.10},  # Thu
    4: {"CONEXION": 0.45, "ANALISIS": 0.30, "DEBATE": 0.15, "WIRE": 0.10},  # Fri
    5: {"ANALISIS": 0.50, "CONEXION": 0.30, "DEBATE": 0.20, "WIRE": 0.00},  # Sat
    6: {"ANALISIS": 0.55, "CONEXION": 0.30, "DEBATE": 0.15, "WIRE": 0.00},  # Sun
}

BREAKING_KEYWORDS = [
    "just in", "breaking", "urgent", "alerta", "ultima hora", "última hora",
    "confirma", "colapsa", "renuncia", "acuerdo", "ataque", "explosion",
    "explosión", "crisis", "emergencia", "intervención", "intervencion",
]

# Thread-type schedule (which days produce threads vs single posts)
THREAD_DAYS = {0, 2, 5}  # Mon, Wed, Sat


# ------------------------------------------------------------------
# Type selection
# ------------------------------------------------------------------

def is_breaking(headline: dict) -> bool:
    text = (headline.get("title", "") + " " + headline.get("summary", "")).lower()
    return any(kw in text for kw in BREAKING_KEYWORDS)


def get_tweet_type(headline: dict) -> str:
    """Select post format reactively: breaking -> WIRE, else weighted by day."""
    if is_breaking(headline):
        logger.info("[calendar] Breaking news detected → forcing WIRE")
        return "WIRE"
    day = datetime.now().weekday()
    weights = DAY_WEIGHTS[day]
    # Filter zero-weight types
    valid = {k: v for k, v in weights.items() if v > 0}
    return random.choices(list(valid.keys()), weights=list(valid.values()))[0]


# ------------------------------------------------------------------
# Prompt builders per type — all use SYSTEM_PROMPT
# ------------------------------------------------------------------

def _build_prompt(tipo: str, headlines: list[dict]) -> tuple[str, bool]:
    """
    Build (user_prompt, is_thread) for a given post format.
    Returns the prompt and whether to parse as thread.
    """
    def fmt(h, label="Noticia"):
        title = h.get("title", "").strip()
        summary = h.get("summary", "")[:500].strip()
        source = h.get("source", "").strip()
        return f"{label}:\nTítulo: {title}\nResumen: {summary}\nFuente: {source}"

    if tipo == "WIRE":
        h = headlines[0]
        return (
            f"{fmt(h)}\n\nTipo: WIRE\n"
            "Genera un post urgente y factual. Dato + impacto. Máx 2 líneas. "
            "Sin hashtags. Solo el texto final.",
            False,
        )

    elif tipo == "DEBATE":
        h = headlines[0]
        return (
            f"{fmt(h)}\n\nTipo: DEBATE\n"
            "Take provocador con sustancia. Di algo que obligue a responder. "
            "3 líneas. Sin hashtags. Solo el texto final.",
            False,
        )

    elif tipo == "ANALISIS":
        day = datetime.now().weekday()
        is_thread = day in THREAD_DAYS
        h = random.choice(headlines[:3])
        thread_note = (
            "Genera un HILO de 4-5 posts separados por ---. "
            "Post 1: hook. Posts 2-4: datos/ángulos. Post 5: resumen + 🔁"
            if is_thread else
            "Genera UN post de análisis. 3-5 líneas. Conecta puntos que otros no ven."
        )
        return (f"{fmt(h)}\n\nTipo: ANALISIS\n{thread_note}\nSin hashtags. Solo el texto.", is_thread)

    elif tipo == "CONEXION":
        selected = random.sample(headlines[:min(len(headlines), 5)], min(2, len(headlines)))
        news_block = "\n\n".join(fmt(h, label=f"Noticia {i+1}") for i, h in enumerate(selected))
        return (
            f"{news_block}\n\nTipo: CONEXION\n"
            "Conecta estas dos noticias como un detective. "
            "Mezcla asombro con preocupación. 3-4 líneas. Sin hashtags. Solo el texto.",
            False,
        )

    # Fallback
    h = headlines[0]
    return (f"{fmt(h)}\n\nGenera un post analítico. Solo el texto.", False)


# ------------------------------------------------------------------
# Content generation — FIXED: always passes system=SYSTEM_PROMPT
# ------------------------------------------------------------------

def generate_content(tipo: str, headlines: list[dict]) -> str:
    """Generate content using Claude API with full SYSTEM_PROMPT."""
    if not ANTHROPIC_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")
    if not headlines:
        raise ValueError("No headlines available")

    prompt, _ = _build_prompt(tipo, headlines)
    model = get_model(tipo)

    # Inject memory continuity
    memory = get_memory()
    continuity = memory.build_continuity_prompt()
    system = SYSTEM_PROMPT + ("\n\n" + continuity if continuity else "")

    client, is_or = _get_client()
    return _call_api(client, model, system, prompt, 900, is_or)


def parse_content(raw: str, is_thread: bool) -> list[str]:
    if not is_thread:
        post = raw.replace("---", "").strip()
        return [post[:500]] if post else [""]

    parts = [p.strip() for p in raw.split("---") if p.strip()]
    posts = []
    for part in parts:
        clean = part.strip()
        # Strip leading "1/" "2/" markers if present
        for prefix in [f"{n}/" for n in range(1, 10)]:
            if clean.startswith(prefix):
                clean = clean[len(prefix):].strip()
                break
        posts.append(clean[:500])
    return posts if posts else [raw[:500]]


# ------------------------------------------------------------------
# Telegram delivery
# ------------------------------------------------------------------

def send_to_telegram(tipo: str, day_name: str, content_list: list[str]) -> bool:
    if len(content_list) == 1:
        content_block = content_list[0]
    else:
        content_block = "\n\n".join(
            f"({i+1}/{len(content_list)}) {t}" for i, t in enumerate(content_list)
        )

    text = (
        f"📅 CALENDARIO — {day_name}\n"
        f"Tipo: {tipo}\n\n"
        f"{content_block}\n\n"
        f'Responde "publica" para publicar.'
    )

    try:
        send_message(text)
        logger.info(f"[calendar] Sent to Telegram: {tipo}")
        return True
    except Exception as e:
        logger.error(f"[calendar] Telegram send failed: {e}")
        return False


# ------------------------------------------------------------------
# Fetch helpers
# ------------------------------------------------------------------

def fetch_headlines(count: int = 5) -> list[dict]:
    try:
        from fetcher import get_latest_headlines
        headlines = get_latest_headlines()
        return headlines[:count] if headlines else []
    except Exception as e:
        logger.error(f"[calendar] fetch error: {e}")
        return []


# ------------------------------------------------------------------
# Main entry
# ------------------------------------------------------------------

def get_daily_content(headlines: list[dict] = None) -> tuple[str, list[str]]:
    today = datetime.now().weekday()
    day_name = DAY_NAMES_ES[today]

    if headlines is None:
        headlines = fetch_headlines(count=5)

    if not headlines:
        logger.warning("[calendar] No headlines, skipping")
        return ("", [])

    # Pick the dominant headline to drive type selection
    tipo = get_tweet_type(headlines[0])
    logger.info(f"[calendar] {day_name} → {tipo}")

    _, is_thread = _build_prompt(tipo, headlines)
    raw = generate_content(tipo, headlines)

    content_list = parse_content(raw, is_thread)

    # Save to memory
    memory = get_memory()
    topic = _detect_topic(headlines[0])
    for post in content_list[:1]:  # only save first post of thread
        memory.add_tweet(post, tipo, topic, "threads")

    return (tipo, content_list)


def run():
    today = datetime.now().weekday()
    day_name = DAY_NAMES_ES[today]
    tipo, content_list = get_daily_content()

    if not content_list:
        logger.info("[calendar] Nothing to publish today")
        return

    send_to_telegram(tipo, day_name, content_list)


if __name__ == "__main__":
    run()
