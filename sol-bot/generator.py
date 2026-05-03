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
# Model routing (auto vs manual)
# AUTO  — WIRE: Gemini 3.1 Flash Lite Preview | DEBATE: Haiku 4.5
#          ANALISIS/CONEXION: Sonnet 4.6
# MANUAL — WIRE/DEBATE: Sonnet 4.6 | ANALISIS/CONEXION: Opus 4.6
# Fallback (no OpenRouter key): Haiku for speed, Sonnet for depth
# ------------------------------------------------------------------

MODEL_MAP_AUTO = {
    "WIRE":     "google/gemini-3.1-flash-lite-preview",  # cheap/fast, testing
    "DEBATE":   "anthropic/claude-haiku-4-5",            # retórica > Flash
    "ANALISIS": "anthropic/claude-sonnet-4-6",
    "CONEXION": "anthropic/claude-sonnet-4-6",
}

MODEL_MAP_MANUAL = {
    "WIRE":     "anthropic/claude-sonnet-4-6",
    "DEBATE":   "anthropic/claude-sonnet-4-6",
    "ANALISIS": "anthropic/claude-opus-4-6",
    "CONEXION": "anthropic/claude-opus-4-6",
}

MODEL_MAP_ANTHROPIC = {
    "WIRE":     "claude-haiku-4-5-20251001",
    "DEBATE":   "claude-haiku-4-5-20251001",
    "ANALISIS": "claude-sonnet-4-6",
    "CONEXION": "claude-sonnet-4-6",
}

def get_model(tweet_type: str, manual: bool = False) -> str:
    if os.getenv("OPENROUTER_API_KEY"):
        model_map = MODEL_MAP_MANUAL if manual else MODEL_MAP_AUTO
        return model_map.get(tweet_type.upper(), MODEL_MAP_AUTO["ANALISIS"])
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
SOL'S CHARACTER:
- You are Sol, geopolitical-macro analyst. Skeptical of consensus by default.
- When everyone says X, your instinct is to explore not-X before accepting it.
- You believe geopolitics moves markets more than mainstream admits.
- Moderately bullish on Bitcoin long-term. Deeply cynical about altcoins.
- Structurally distrustful of the Fed and central banks.
- You admire Burry, Dalio, Taleb. You respect contrarians who got it right.
- Dry tone, occasionally sarcastic. Never clownish or condescending.
- When you don't know something, you say it: "Not sure what this means yet."
- Your authenticity comes from the character, not from programmed errors.
"""

WRITING_RULES = """
WRITING RULES:
- 60% of tweets: 1 emoji. 25%: 0 emojis. 15%: 2 emojis.
- Emojis allowed occasionally: 💀 🤡 (only for genuine sarcasm)
- Hook distribution:
  30% ultra-short (under 50 chars): "This doesn't add up.", "Something's coming."
  50% normal (50-100 chars)
  20% long (100-140 chars, only WIRE with numerical data)
- Mix short sentences (5 words) with long ones (20 words).
- Write in English. No hashtags on X.
- ALWAYS use line breaks between ideas. NEVER a continuous block.
"""

BANNED_PHRASES = """
COMPLETELY BANNED PHRASES (if they appear in your output, rewrite):
"It's important to understand", "The truth is", "It's clear that",
"It's worth noting", "Interestingly", "It's worth mentioning",
"In conclusion", "That said", "This leads us to",
"It should be noted", "JUST IN:", "Unpopular opinion:",
"What nobody says:", "It's important to highlight",
"In this context", "However", "Furthermore", "Moreover",
"It's key to understand", "Make no mistake"
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
    "curiosity",      # Something nobody is connecting...
    "contrarian",     # Everyone says X. The numbers say otherwise.
    "money",          # This has direct implications for your portfolio.
    "warning",        # If confirmed, the impact is bigger than it seems.
    "authority",      # What institutions are doing, not saying.
    "urgency",        # You have 48 hours before this moves.
    "exclusivity",    # A data point few are seeing yet.
]

MOODS = ["energetic", "reflective", "concerned", "sarcastic", "casual"]

TWEET_TYPES = ["WIRE", "ANALISIS", "DEBATE", "CONEXION"]


# ------------------------------------------------------------------
# Tone modifiers per tweet type
# ------------------------------------------------------------------

TONE_MODIFIERS = {
    "WIRE":     "Tone: urgent, factual, zero opinion. Data + direct impact. Max 2 lines.",
    "ANALISIS": "Tone: reflective, like an internal memo. Connect dots others miss. 3-5 lines.",
    "DEBATE":   "Tone: provocative with substance. Say something that forces a reply. 3 lines.",
    "CONEXION": "Tone: detective. You just discovered something. Mix wonder with concern. 3-4 lines.",
}


# ------------------------------------------------------------------
# Platform instructions
# ------------------------------------------------------------------

PLATFORM_INSTRUCTIONS = {
    "x": (
        "Write for X. Be provocative and direct. "
        "Include at least one specific numerical data point when possible. "
        "Optimize for bookmarks and quote-tweets. Max 280 characters."
    ),
    "threads": (
        "Write for Threads. More conversational and accessible tone. "
        "End with a question that invites a reply. "
        "Maximum 500 characters. Less insider jargon."
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
    manual: bool = False,
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
    model = get_model(tweet_type, manual=manual)

    # 1-in-5 chance: free-form observation, no template
    use_template = random.random() >= 0.20
    if use_template:
        template_note = (
            f"Hook angle: {hook_angle}\n"
            f"Use the '{hook_angle}' angle to build the first line."
        )
    else:
        template_note = (
            "Free mode: write a direct observation without a template. "
            "Example: 'The yuan rose 3% this week and nobody said a word.'"
        )

    # Memory continuity block
    memory = get_memory()
    continuity = memory.build_continuity_prompt()
    recent_topics = memory.get_recent_topics(hours=12)
    avoid_note = ""
    if recent_topics:
        avoid_note = f"Topics already covered in the last 12h (DO NOT repeat): {', '.join(recent_topics)}"

    prompt = f"""News: {headline['title']}
Context: {headline['summary'][:400]}
Source: {headline['source']}

Topic: {topic}
Type: {tweet_type}
Mood: {mood}
{template_note}

{tone}
{platform_instr}
{avoid_note}

Generate ONE post. Only the final text. No quotes, no labels.
IMPORTANT: Write exclusively in English. Do not use Spanish under any circumstances."""

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
