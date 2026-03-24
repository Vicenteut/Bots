#!/usr/bin/env python3
"""
Content Calendar for @napoleotics X/Twitter bot.
Generates daily content based on tweet type schedule.
Can be imported by scheduler.py or run standalone.
"""

import random
from datetime import datetime

from config import load_environment, get_env, get_required_env
from telegram_client import send_message

load_environment()

get_required_env("TELEGRAM_BOT_TOKEN")
get_required_env("TELEGRAM_CHAT_ID")
ANTHROPIC_KEY = get_env("ANTHROPIC_API_KEY")
MODEL = "claude-haiku-4-5-20251001"

SCHEDULE = {
    0: {
        "tipo": "ANALISIS", "emoji": "\U0001f52c",
        "description": "Analisis profundo",
        "prompt": (
            "Analiza esta noticia en profundidad. Genera un hilo de 3-5 tweets "
            "en espanol. Cada tweet max 280 chars. Separar con ---. Incluir datos "
            "concretos, causa-efecto, y que significa para inversores."
        ),
        "headlines_needed": 1, "is_thread": True,
    },
    1: {
        "tipo": "DEBATE", "emoji": "\U0001f525",
        "description": "Take controversial",
        "prompt": (
            "Genera un tweet controversial pero fundamentado sobre esta noticia. "
            "Debe provocar respuestas. Max 280 chars. En espanol. Una opinion "
            "fuerte con un dato que la respalde."
        ),
        "headlines_needed": 1, "is_thread": False,
    },
    2: {
        "tipo": "HILO EDUCATIVO", "emoji": "\U0001f4da",
        "description": "Hilo educativo",
        "prompt": (
            "Explica el concepto detras de esta noticia como si fuera un "
            "mini-curso. 5-7 tweets, separados con ---. Cada uno max 280 chars. "
            "En espanol. Usa analogias simples."
        ),
        "headlines_needed": 1, "is_thread": True,
    },
    3: {
        "tipo": "CONEXION", "emoji": "\U0001f517",
        "description": "Conexion inesperada",
        "prompt": (
            "Conecta estas dos noticias aparentemente no relacionadas. Un tweet, "
            "max 280 chars. En espanol. El formato es: dato1 + dato2 = "
            "conclusion sorprendente."
        ),
        "headlines_needed": 2, "is_thread": False,
    },
    4: {
        "tipo": "PREDICCION", "emoji": "\U0001f52e",
        "description": "Prediccion semanal",
        "prompt": (
            "Basandote en esta noticia, haz una prediccion fundamentada para la "
            "proxima semana. Un tweet, max 280 chars. En espanol. Se especifico "
            "con numeros o fechas."
        ),
        "headlines_needed": 1, "is_thread": False,
    },
    5: {
        "tipo": "RESUMEN SEMANAL", "emoji": "\U0001f4cb",
        "description": "Resumen de la semana",
        "prompt": (
            "Resume las noticias mas importantes de esta semana en 5 tweets. "
            "Separar con ---. Cada uno max 280 chars. En espanol. Tweet 1 = "
            "intro, tweets 2-4 = top stories, tweet 5 = que esperar."
        ),
        "headlines_needed": 5, "is_thread": True,
    },
    6: {
        "tipo": "DESCANSO", "emoji": "\U0001f634",
        "description": "Descanso / solo si hay noticia grande",
        "prompt": (
            "Solo si esta noticia es REALMENTE importante (crisis, crash, guerra, "
            "evento historico), genera un tweet breve en espanol. Max 280 chars. "
            "Si no es tan importante, responde exactamente: SKIP"
        ),
        "headlines_needed": 1, "is_thread": False,
    },
}

DAY_NAMES_ES = [
    "Lunes", "Martes", "Miercoles", "Jueves",
    "Viernes", "Sabado", "Domingo",
]


def fetch_headlines(count=5):
    try:
        from fetcher import get_latest_headlines
        headlines = get_latest_headlines()
        if headlines and len(headlines) > 0:
            return headlines[:count]
    except ImportError:
        print("[calendar] Warning: fetcher module not found")
    except Exception as e:
        print(f"[calendar] Error fetching headlines: {e}")
    return []


def _format_news_block(headline, *, label):
    if isinstance(headline, dict):
        title = headline.get("title", "").strip()
        summary = headline.get("summary", "").strip()
        source = headline.get("source", "").strip()
        parts = [f"{label}:"]
        if title:
            parts.append(f"Titulo: {title}")
        if summary:
            parts.append(f"Resumen: {summary[:500]}")
        if source:
            parts.append(f"Fuente: {source}")
        return "\n".join(parts)
    return f"{label}: {str(headline).strip()}"


def generate_content(schedule_entry, headlines):
    import anthropic

    if not ANTHROPIC_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set in .env")

    tipo = schedule_entry["tipo"]
    prompt_template = schedule_entry["prompt"]
    needed = schedule_entry["headlines_needed"]

    if not headlines:
        raise ValueError("No headlines available to generate content")

    if tipo == "CONEXION" and len(headlines) >= 2:
        selected = random.sample(headlines[:min(len(headlines), 5)], 2)
        news_block = "\n\n".join(
            _format_news_block(item, label=f"Noticia {index}")
            for index, item in enumerate(selected, 1)
        )
    elif tipo == "RESUMEN SEMANAL":
        selected = headlines[:min(len(headlines), needed)]
        news_block = "\n".join(
            _format_news_block(h, label=f"Noticia {i + 1}")
            for i, h in enumerate(selected)
        )
    else:
        selected = [random.choice(headlines[:min(len(headlines), 3)])]
        news_block = _format_news_block(selected[0], label="Noticia")

    user_prompt = f"{prompt_template}\n\n{news_block}"

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = message.content[0].text.strip()
    return raw


def parse_content(raw_text, is_thread):
    if not is_thread:
        tweet = raw_text.replace("---", "").strip()
        if not tweet:
            return [""]
        normalized = "\n\n".join(
            line.strip()
            for line in tweet.splitlines()
            if line.strip()
        )
        return [normalized[:280]]

    parts = [p.strip() for p in raw_text.split("---") if p.strip()]
    tweets = []
    for part in parts:
        clean = part.strip()
        for prefix in ["1/", "2/", "3/", "4/", "5/", "6/", "7/"]:
            if clean.startswith(prefix):
                clean = clean[len(prefix):].strip()
                break
        tweets.append(clean[:280])
    return tweets if tweets else [raw_text[:280]]


def send_to_telegram(tweet_type, day_name, content_list):
    emoji = SCHEDULE[list(DAY_NAMES_ES).index(day_name)]["emoji"] if day_name in DAY_NAMES_ES else "\U0001f4c5"

    if len(content_list) == 1:
        content_block = content_list[0]
    else:
        content_block = "\n\n".join(
            f"({i+1}/{len(content_list)}) {t}" for i, t in enumerate(content_list)
        )

    text = (
        f"\U0001f4c5 CALENDARIO — {day_name}\n"
        f"Tipo: {emoji} {tweet_type}\n\n"
        f"{content_block}\n\n"
        f'Responde "publica" para publicar.'
    )

    try:
        if send_message(text, parse_mode="HTML"):
            print(f"[calendar] Sent to Telegram: {tweet_type}")
            return True
        print("[calendar] Telegram API returned unsuccessful response")
        return False
    except Exception as e:
        print(f"[calendar] Failed to send to Telegram: {e}")
        return False


def get_daily_content(headlines=None):
    today = datetime.now().weekday()
    day_name = DAY_NAMES_ES[today]
    entry = SCHEDULE[today]
    tipo = entry["tipo"]

    print(f"[calendar] {day_name} -> {tipo}")

    if headlines is None:
        headlines = fetch_headlines(count=max(entry["headlines_needed"], 5))

    if not headlines:
        print("[calendar] No headlines available, skipping")
        return (tipo, [])

    raw = generate_content(entry, headlines)

    if tipo == "DESCANSO" and "SKIP" in raw.upper():
        print("[calendar] Sunday: no major news, skipping")
        return (tipo, [])

    content_list = parse_content(raw, entry["is_thread"])
    return (tipo, content_list)


def run():
    today = datetime.now().weekday()
    day_name = DAY_NAMES_ES[today]

    tipo, content_list = get_daily_content()

    if not content_list:
        print("[calendar] Nothing to publish today")
        return

    send_to_telegram(tipo, day_name, content_list)


if __name__ == "__main__":
    run()
