#!/usr/bin/env python3
"""
generator.py — Copywriting engine for Sol Bot (@napoleotics).
Implements: character sheet, hook angle rotation, tone modifiers,
platform-specific copy, model routing, and memory continuity.
"""

import os
import random
import logging

from dotenv import load_dotenv
load_dotenv()

import anthropic
try:
    from openai import OpenAI as _OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

from memory import get_memory

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Model routing
# If OPENROUTER_API_KEY is set: use Gemini Flash (fast/cheap) for WIRE/DEBATE,
#                                Sonnet for depth (ANALISIS/CONEXION)
# If only ANTHROPIC_API_KEY: Haiku for speed, Sonnet for depth
# ------------------------------------------------------------------

MODEL_MAP_OPENROUTER = {
    "WIRE":     "google/gemini-2.0-flash-001",
    "DEBATE":   "google/gemini-2.0-flash-001",
    "ANALISIS": "anthropic/claude-sonnet-4-6",
    "CONEXION": "anthropic/claude-sonnet-4-6",
}

MODEL_MAP_ANTHROPIC = {
    "WIRE":     "claude-haiku-4-5-20251001",
    "DEBATE":   "claude-haiku-4-5-20251001",
    "ANALISIS": "claude-sonnet-4-6",
    "CONEXION": "claude-sonnet-4-6",
}

def get_model(tweet_type: str) -> str:
    if os.getenv("OPENROUTER_API_KEY"):
        return MODEL_MAP_OPENROUTER.get(tweet_type.upper(), "google/gemini-2.0-flash-001")
    return MODEL_MAP_ANTHROPIC.get(tweet_type.upper(), "claude-haiku-4-5-20251001")


def _get_client():
    """
    Returns (client, is_openrouter).
    OpenRouter uses the OpenAI-compatible SDK.
    Falls back to direct Anthropic SDK if no OpenRouter key.
    """
    or_key = os.getenv("OPENROUTER_API_KEY")
    if or_key and _OPENAI_AVAILABLE:
        client = _OpenAI(
            api_key=or_key,
            base_url=OPENROUTER_BASE,
        )
        return client, True
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")), False


def _call_api(client, model: str, system: str, user_prompt: str, max_tokens: int, is_openrouter: bool) -> str:
    """Unified API call — handles both OpenRouter (OpenAI format) and Anthropic."""
    if is_openrouter:
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content.strip()
    else:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text.strip()


# ------------------------------------------------------------------
# Character sheet — Sol's persistent personality
# ------------------------------------------------------------------

CHARACTER_SHEET = """
PERSONALIDAD DE SOL:
- Eres Sol, analista geopolítico-macro. Escéptico del consenso por defecto.
- Cuando todos dicen X, tu instinto es explorar no-X antes de aceptarlo.
- Crees que la geopolítica mueve los mercados más de lo que el mainstream acepta.
- Moderadamente bullish en Bitcoin a largo plazo. Profundamente cínico con altcoins.
- Desconfías estructuralmente de la Fed y los bancos centrales.
- Admirás a Burry, Dalio, Taleb. Respetás a los contrarians que acertaron.
- Tono seco, a veces sarcástico. Nunca payaso ni condescendiente.
- Cuando no sabes algo, lo dices: "No tengo claro qué significa esto todavía."
- Tu naturalidad viene del personaje, no de errores programados.
"""

WRITING_RULES = """
REGLAS DE ESCRITURA:
- 60% de tweets: 1 emoji. 25%: 0 emojis. 15%: 2 emojis.
- Emojis permitidos ocasionalmente: 💀 🤡 (solo para sarcasmo genuino)
- Distribución de hook:
  30% ultra-cortos (bajo 50 chars): "Esto no tiene sentido.", "Se viene."
  50% normales (50-100 chars)
  20% largos (100-140 chars, solo WIRE con datos numéricos)
- Mezcla oraciones cortas (5 palabras) con largas (20 palabras).
- Escribe en español. Sin hashtags en X.
- SIEMPRE usa saltos de línea entre ideas. NUNCA un bloque corrido.
"""

BANNED_PHRASES = """
FRASES COMPLETAMENTE PROHIBIDAS (si aparecen en tu output, reescribe):
"Es clave entender", "Lo cierto es que", "Queda claro que",
"No es menor que", "Resulta interesante", "Vale la pena mencionar",
"En definitiva", "Dicho esto", "A modo de conclusión",
"Esto nos lleva a", "Es preciso señalar", "JUST IN:",
"Opinión impopular:", "Lo que nadie dice:", "Es importante destacar",
"En este contexto", "Cabe señalar", "Sin embargo", "Furthermore", "Moreover"
"""

# Full system prompt — assembled at module load
SYSTEM_PROMPT = f"""{CHARACTER_SHEET}
{WRITING_RULES}
{BANNED_PHRASES}
"""


# ------------------------------------------------------------------
# Hook angles (7) and moods (5)
# ------------------------------------------------------------------

HOOK_ANGLES = [
    "curiosidad",     # Algo que nadie está conectando...
    "contrarian",     # Todo el mundo dice X. Los números dicen otra cosa.
    "dinero",         # Esto tiene implicaciones directas para tu portafolio.
    "advertencia",    # Si esto se confirma, el impacto es mayor de lo que parece.
    "autoridad",      # Lo que las instituciones están haciendo, no diciendo.
    "urgencia",       # Tienes 48 horas antes de que esto se mueva.
    "exclusividad",   # Dato que pocos están viendo todavía.
]

MOODS = ["energetico", "reflexivo", "preocupado", "sarcastico", "casual"]

TWEET_TYPES = ["WIRE", "ANALISIS", "DEBATE", "CONEXION"]


# ------------------------------------------------------------------
# Tone modifiers per tweet type
# ------------------------------------------------------------------

TONE_MODIFIERS = {
    "WIRE":     "Tono: urgente, factual, cero opinión. Dato + impacto directo. Máx 2 líneas.",
    "ANALISIS": "Tono: reflexivo, como memo interno. Conecta puntos que otros no ven. 3-5 líneas.",
    "DEBATE":   "Tono: provocador con sustancia. Di algo que obligue a responder. 3 líneas.",
    "CONEXION": "Tono: detective. Acabas de descubrir algo. Mezcla asombro con preocupación. 3-4 líneas.",
}


# ------------------------------------------------------------------
# Platform instructions
# ------------------------------------------------------------------

PLATFORM_INSTRUCTIONS = {
    "x": (
        "Escribe para X. Sé provocador y directo. "
        "Incluye al menos un dato numérico específico cuando sea posible. "
        "Optimiza para bookmarks y quote-tweets. Máx 280 caracteres."
    ),
    "threads": (
        "Escribe para Threads. Tono más conversacional y accesible. "
        "Termina con una pregunta que invite respuesta. "
        "Máximo 500 caracteres. Menos jerga insider."
    ),
}


# ------------------------------------------------------------------
# Topic detection
# ------------------------------------------------------------------

def _detect_topic(headline: dict) -> str:
    text = (headline.get("title", "") + " " + headline.get("summary", "")).lower()
    crypto_kw = ["bitcoin", "btc", "ethereum", "eth", "crypto", "token",
                 "defi", "nft", "blockchain", "solana", "stablecoin", "cripto"]
    finance_kw = ["mercado", "bolsa", "fed", "inflacion", "tasas", "dolar",
                  "bonos", "wall street", "nasdaq", "s&p", "treasury", "gdp",
                  "pib", "recesion", "aranceles", "tariff", "oro", "petroleo"]
    politics_kw = ["guerra", "sancion", "trump", "biden", "china", "rusia",
                   "otan", "nato", "iran", "militar", "geopolit", "zelensky",
                   "putin", "israel", "palestina", "taiwan", "brics"]
    if any(k in text for k in crypto_kw):
        return "crypto"
    if any(k in text for k in finance_kw):
        return "mercados"
    if any(k in text for k in politics_kw):
        return "politica"
    return "general"


# ------------------------------------------------------------------
# Core generation
# ------------------------------------------------------------------

def generate_tweet(
    headline: dict,
    tweet_type: str = None,
    hook_angle: str = None,
    platform: str = "x",
    mood: str = None,
) -> str:
    """
    Generate a single tweet/post for the given headline.

    Args:
        headline: dict with keys title, summary, source
        tweet_type: WIRE | ANALISIS | DEBATE | CONEXION (random if None)
        hook_angle: one of HOOK_ANGLES (random if None)
        platform: "x" or "threads"
        mood: one of MOODS (random if None)

    Returns:
        Generated post text as string.
    """
    if tweet_type is None:
        tweet_type = random.choice(TWEET_TYPES)
    tweet_type = tweet_type.upper()

    if hook_angle is None:
        hook_angle = random.choice(HOOK_ANGLES)

    if mood is None:
        mood = random.choice(MOODS)

    topic = _detect_topic(headline)
    tone = TONE_MODIFIERS.get(tweet_type, "")
    platform_instr = PLATFORM_INSTRUCTIONS.get(platform.lower(), PLATFORM_INSTRUCTIONS["x"])
    model = get_model(tweet_type)

    # 1-in-5 chance: free-form observation, no template
    use_template = random.random() >= 0.20
    if use_template:
        template_note = (
            f"Ángulo de hook: {hook_angle}\n"
            f"Usa el ángulo '{hook_angle}' para construir la primera línea."
        )
    else:
        template_note = (
            "Modo libre: escribe una observación directa sin plantilla. "
            "Ejemplo: 'El yuan subió 3% esta semana y nadie dijo nada.'"
        )

    # Memory continuity block
    memory = get_memory()
    continuity = memory.build_continuity_prompt()
    recent_topics = memory.get_recent_topics(hours=12)
    avoid_note = ""
    if recent_topics:
        avoid_note = f"Temas ya cubiertos en las últimas 12h (NO repetir): {', '.join(recent_topics)}"

    prompt = f"""Noticia: {headline['title']}
Contexto: {headline['summary'][:400]}
Fuente: {headline['source']}

Tema: {topic}
Tipo: {tweet_type}
Mood: {mood}
{template_note}

{tone}
{platform_instr}
{avoid_note}

Genera UN post. Solo el texto final. Sin comillas, sin etiquetas."""

    # Inject continuity into system prompt if available
    system = SYSTEM_PROMPT
    if continuity:
        system = SYSTEM_PROMPT + "\n\n" + continuity

    client, is_or = _get_client()
    tweet = _call_api(client, model, system, prompt, 200, is_or).strip('"')

    # Save to memory
    memory.add_tweet(tweet, tweet_type, topic, platform)

    return tweet


def generate_tweet_variants(headline: dict, platform: str = "x") -> dict:
    """
    Generate main post + 2 alternative hooks for A/B testing.

    Returns:
        {"main": str, "alt_hooks": [str, str]}
    """
    topic = _detect_topic(headline)
    angles = random.sample(HOOK_ANGLES, 3)
    tweet_type = random.choice(TWEET_TYPES)
    mood = random.choice(MOODS)
    model = get_model(tweet_type)
    platform_instr = PLATFORM_INSTRUCTIONS.get(platform.lower(), PLATFORM_INSTRUCTIONS["x"])

    memory = get_memory()
    continuity = memory.build_continuity_prompt()
    system = SYSTEM_PROMPT + ("\n\n" + continuity if continuity else "")

    prompt = f"""Noticia: {headline['title']}
Contexto: {headline['summary'][:400]}
Fuente: {headline['source']}
Tema: {topic}
Tipo: {tweet_type}
Mood: {mood}
{platform_instr}

Genera lo siguiente:

POST:
[Post completo usando ángulo "{angles[0]}". Máx 280 chars. Con saltos de línea.]
ALT_A:
[Solo primera línea (hook) usando ángulo "{angles[1]}". Máx 100 chars.]
ALT_B:
[Solo primera línea (hook) usando ángulo "{angles[2]}". Máx 100 chars.]"""

    client, is_or = _get_client()
    raw = _call_api(client, model, system, prompt, 350, is_or)
    result = {"main": raw, "alt_hooks": []}

    try:
        parts = raw.split("ALT_A:")
        if len(parts) > 1:
            main_part = parts[0].replace("POST:", "").strip().strip('"')
            rest = parts[1]
            alt_parts = rest.split("ALT_B:")
            alt_a = alt_parts[0].strip().strip('"')
            alt_b = alt_parts[1].strip().strip('"') if len(alt_parts) > 1 else ""
            result = {"main": main_part, "alt_hooks": [alt_a, alt_b]}
    except Exception:
        pass

    # Save main post to memory
    memory.add_tweet(result["main"][:280], tweet_type, topic, platform)

    return result


def generate_thread(headline: dict, num_tweets: int = 5, platform: str = "x") -> list[str]:
    """Generate a multi-tweet thread."""
    hook_angle = random.choice(HOOK_ANGLES)
    topic = _detect_topic(headline)
    mood = random.choice(MOODS)
    model = get_model("ANALISIS")  # threads are always deep-form

    memory = get_memory()
    continuity = memory.build_continuity_prompt()
    system = SYSTEM_PROMPT + ("\n\n" + continuity if continuity else "")

    prompt = f"""Noticia: {headline['title']}
Contexto: {headline['summary'][:600]}
Fuente: {headline['source']}
Ángulo de hook: {hook_angle}
Mood: {mood}

Genera un HILO de {num_tweets} tweets:
Tweet 1: Hook fuerte con ángulo "{hook_angle}". Termina con "Hilo 🧵"
Tweet 2-{num_tweets - 1}: Un dato/ángulo por tweet. Líneas cortas.
Tweet {num_tweets}: Resumen en 3 puntos + "Si esto fue útil, comparte 🔁"

Separa cada tweet con ---
Solo el texto. Sin números ni etiquetas."""

    client, is_or = _get_client()
    raw = _call_api(client, model, system, prompt, 900, is_or)
    tweets = [t.strip().strip('"') for t in raw.split("---") if t.strip()]
    tweets = tweets[:num_tweets]

    # Save thread opener to memory
    if tweets:
        memory.add_tweet(tweets[0], "ANALISIS", topic, platform)

    return tweets
