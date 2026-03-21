#!/usr/bin/env python3
"""
Content Calendar for @napoleotics X/Twitter bot.
Generates daily content based on tweet type schedule.
Can be imported by scheduler.py or run standalone.
"""

import os
import sys
import json
import random
import urllib.request
import urllib.parse
from datetime import datetime

sys.path.insert(0, "/root/x-bot")
from dotenv import load_dotenv

load_dotenv("/root/x-bot/.env")

BOT_TOKEN = "8603788822:AAHkhXtvyFBqYSA-hglE0aXr_0rAZhFaWxM"
CHAT_ID = 6054558214
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = "claude-haiku-4-5-20251001"

# Day schedule: 0=Monday ... 6=Sunday
SCHEDULE = {
    0: {
        "tipo": "ANALISIS",
        "emoji": "🔬",
        "description": "Analisis profundo",
        "prompt": (
            "Analiza esta noticia en profundidad. Genera un hilo de 3-5 tweets "
            "en español. Cada tweet max 280 chars. Separar con ---. Incluir datos "
            "concretos, causa-efecto, y qué significa para inversores."
        ),
        "headlines_needed": 1,
        "is_thread": True,
    },
    1: {
        "tipo": "DEBATE",
        "emoji": "🔥",
        "description": "Take controversial",
        "prompt": (
            "Genera un tweet controversial pero fundamentado sobre esta noticia. "
            "Debe provocar respuestas. Max 280 chars. En español. Una opinión "
            "fuerte con un dato que la respalde."
        ),
        "headlines_needed": 1,
        "is_thread": False,
    },
    2: {
        "tipo": "HILO EDUCATIVO",
        "emoji": "📚",
        "description": "Hilo educativo",
        "prompt": (
            "Explica el concepto detrás de esta noticia como si fuera un "
            "mini-curso. 5-7 tweets, separados con ---. Cada uno max 280 chars. "
            "En español. Usa analogías simples."
        ),
        "headlines_needed": 1,
        "is_thread": True,
    },
    3: {
        "tipo": "CONEXION",
        "emoji": "🔗",
        "description": "Conexion inesperada",
        "prompt": (
            "Conecta estas dos noticias aparentemente no relacionadas. Un tweet, "
            "max 280 chars. En español. El formato es: dato1 + dato2 = "
            "conclusión sorprendente."
        ),
        "headlines_needed": 2,
        "is_thread": False,
    },
    4: {
        "tipo": "PREDICCION",
        "emoji": "🔮",
        "description": "Prediccion semanal",
        "prompt": (
            "Basándote en esta noticia, haz una predicción fundamentada para la "
            "próxima semana. Un tweet, max 280 chars. En español. Sé específico "
            "con números o fechas."
        ),
        "headlines_needed": 1,
        "is_thread": False,
    },
    5: {
        "tipo": "RESUMEN SEMANAL",
        "emoji": "📋",
        "description": "Resumen de la semana",
        "prompt": (
            "Resume las noticias más importantes de esta semana en 5 tweets. "
            "Separar con ---. Cada uno max 280 chars. En español. Tweet 1 = "
            "intro, tweets 2-4 = top stories, tweet 5 = qué esperar."
        ),
        "headlines_needed": 5,
        "is_thread": True,
    },
    6: {
        "tipo": "DESCANSO",
        "emoji": "😴",
        "description": "Descanso / solo si hay noticia grande",
        "prompt": (
            "Solo si esta noticia es REALMENTE importante (crisis, crash, guerra, "
            "evento historico), genera un tweet breve en español. Max 280 chars. "
            "Si no es tan importante, responde exactamente: SKIP"
        ),
        "headlines_needed": 1,
        "is_thread": False,
    },
}

DAY_NAMES_ES = [
    "Lunes", "Martes", "Miércoles", "Jueves",
    "Viernes", "Sábado", "Domingo",
]


def fetch_headlines(count=5):
    """Fetch headlines using the existing fetcher module."""
    try:
        from fetcher import get_latest_headlines
        headlines = get_latest_headlines()
        if headlines and len(headlines) > 0:
            return headlines[:count]
    except ImportError:
        print("[calendar] Warning: fetcher module not found, using fallback")
    except Exception as e:
        print(f"[calendar] Error fetching headlines: {e}")
    return []


def generate_content(schedule_entry, headlines):
    """Call Claude Haiku to generate content based on day type and headlines."""
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
        news_block = f"Noticia 1: {selected[0]}\nNoticia 2: {selected[1]}"
    elif tipo == "RESUMEN SEMANAL":
        selected = headlines[:min(len(headlines), needed)]
        news_block = "\n".join(
            f"Noticia {i+1}: {h}" for i, h in enumerate(selected)
        )
    else:
        selected = [random.choice(headlines[:min(len(headlines), 3)])]
        news_block = f"Noticia: {selected[0]}"

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
    """Parse raw Claude output into a list of tweets."""
    if not is_thread:
        # Single tweet — take first 280 chars as safety
        tweet = raw_text.replace("---", "").strip()
        lines = [l.strip() for l in tweet.split("\n") if l.strip()]
        return [lines[0][:280]] if lines else [tweet[:280]]

    # Thread: split by ---
    parts = [p.strip() for p in raw_text.split("---") if p.strip()]
    tweets = []
    for part in parts:
        # Remove numbering like "1/5", "Tweet 1:", etc.
        clean = part.strip()
        for prefix in ["1/", "2/", "3/", "4/", "5/", "6/", "7/"]:
            if clean.startswith(prefix):
                clean = clean[len(prefix):].strip()
                break
        tweets.append(clean[:280])
    return tweets if tweets else [raw_text[:280]]


def send_to_telegram(tweet_type, day_name, content_list):
    """Send generated content to Telegram for approval."""
    emoji = SCHEDULE[list(DAY_NAMES_ES).index(day_name)]["emoji"] if day_name in DAY_NAMES_ES else "📅"

    if len(content_list) == 1:
        content_block = content_list[0]
    else:
        content_block = "\n\n".join(
            f"({i+1}/{len(content_list)}) {t}" for i, t in enumerate(content_list)
        )

    text = (
        f"📅 CALENDARIO — {day_name}\n"
        f"Tipo: {emoji} {tweet_type}\n\n"
        f"{content_block}\n\n"
        f'Responde "publica" para publicar.'
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data)

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("ok"):
                print(f"[calendar] Sent to Telegram: {tweet_type}")
                return True
            else:
                print(f"[calendar] Telegram error: {result}")
                return False
    except Exception as e:
        print(f"[calendar] Failed to send to Telegram: {e}")
        return False


def get_daily_content(headlines=None):
    """
    Main function. Determines today's content type, generates content.
    Returns (tweet_type: str, content_list: list[str]).
    Can be called by scheduler.py or standalone.
    """
    today = datetime.now().weekday()  # 0=Monday
    day_name = DAY_NAMES_ES[today]
    entry = SCHEDULE[today]
    tipo = entry["tipo"]

    print(f"[calendar] {day_name} -> {tipo}")

    # Fetch headlines if not provided
    if headlines is None:
        headlines = fetch_headlines(count=max(entry["headlines_needed"], 5))

    if not headlines:
        print("[calendar] No headlines available, skipping")
        return (tipo, [])

    # Generate content
    raw = generate_content(entry, headlines)

    # Sunday skip check
    if tipo == "DESCANSO" and "SKIP" in raw.upper():
        print("[calendar] Sunday: no major news, skipping")
        return (tipo, [])

    content_list = parse_content(raw, entry["is_thread"])
    return (tipo, content_list)


def run():
    """Full pipeline: generate content and send to Telegram for approval."""
    today = datetime.now().weekday()
    day_name = DAY_NAMES_ES[today]

    tipo, content_list = get_daily_content()

    if not content_list:
        print("[calendar] Nothing to publish today")
        return

    send_to_telegram(tipo, day_name, content_list)


if __name__ == "__main__":
    run()
