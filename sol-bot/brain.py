#!/usr/bin/env python3
"""
brain.py — Conversational intent classifier for Sol Bot.

Receives owner messages and returns a structured action + instruction dict.
Self-contained: no imports from generator.py or sol_commands.py.
"""

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

try:
    from openai import OpenAI as _OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

import anthropic

logger = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

BRAIN_SYSTEM_PROMPT = """You are Sol's command interpreter. Sol is a geopolitical-macro analyst bot that publishes to Threads.

Your job: read the owner's message and return a JSON object with exactly two fields:
- "action": one of [generate_sol, generate_mixed, generate_original, publish, publish_threads_only, regenerate, regenerate_with_instruction, cancel, unknown]
- "instruction": any specific correction or extra context (empty string if none)

Rules:
- Owner speaks Spanish or English — handle both
- "publícalo", "mándalo", "súbelo", "dale", "va" = publish
- "solo en threads", "only threads" = publish_threads_only
- "de nuevo", "otra vez", "regenera", "no me gustó" without extra context = regenerate
- "de nuevo pero [condition]", "hazlo más [adj]", "ponlo más [adj]", "cambia [something]" = regenerate_with_instruction, put the condition in instruction field
- "cancela", "olvídalo", "no lo publiques", "dejalo" = cancel
- If message contains actual news text (headline, data, event), action = generate_sol unless user specifies mixed or original
- "genera el mixed", "hazlo mixed", "combinada" = generate_mixed
- "wire en inglés", "solo el wire", "original" = generate_original
- Return ONLY valid JSON. No markdown fences, no explanation."""

BRAIN_HISTORY_FILE = Path(__file__).parent / "brain_history.json"
BRAIN_TIMEOUT = 3.0
BRAIN_CIRCUIT_BREAKER_THRESHOLD = 3

ALLOWED_ACTIONS = {
    "generate_sol", "generate_mixed", "generate_original",
    "publish", "publish_threads_only",
    "regenerate", "regenerate_with_instruction", "cancel", "unknown",
}

# Module-level circuit breaker state
_consecutive_failures = 0
_brain_disabled = False


def load_history() -> list:
    """Load brain conversation history. Returns empty list on any error."""
    try:
        data = json.loads(BRAIN_HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data[-10:]
        return []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_history(history: list):
    """Persist history to disk atomically. Never raises."""
    try:
        tmp = BRAIN_HISTORY_FILE.parent / f".tmp_{BRAIN_HISTORY_FILE.name}"
        tmp.write_text(
            json.dumps(history[-10:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, BRAIN_HISTORY_FILE)
    except Exception as e:
        logger.warning(f"[brain] Could not save history: {e}")


def append_to_history(role: str, content: str):
    """Append one turn to history and persist."""
    h = load_history()
    h.append({"role": role, "content": content})
    save_history(h[-10:])


def _parse_brain_response(raw: str) -> dict:
    """Strip markdown fences, parse JSON, validate action field. Never raises."""
    try:
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)
        action = parsed.get("action", "unknown")
        if action not in ALLOWED_ACTIONS:
            logger.warning(f"[brain] Unknown action '{action}' — falling back to unknown")
            return {"action": "unknown", "instruction": ""}
        return {
            "action": action,
            "instruction": str(parsed.get("instruction", "")),
        }
    except Exception as e:
        logger.warning(f"[brain] Parse error: {e} | raw={raw[:100]}")
        return {"action": "unknown", "instruction": ""}


def _get_brain_client():
    """Return (client, is_openrouter). Mirrors generator.py pattern."""
    or_key = os.getenv("OPENROUTER_API_KEY")
    if or_key and _OPENAI_AVAILABLE:
        client = _OpenAI(api_key=or_key, base_url=OPENROUTER_BASE)
        return client, True
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")), False


def call_brain(user_message: str, reply_news: str = None) -> dict:
    """
    Classify the owner's intent. Returns {"action": ..., "instruction": ...}.
    Falls back to keyword_fallback on API failure or circuit breaker.
    """
    global _consecutive_failures, _brain_disabled

    if _brain_disabled:
        logger.info("[brain] Disabled — using keyword fallback")
        return keyword_fallback(user_message)

    history = load_history()

    # Build messages from history + optional reply context + current message
    messages = list(history)
    if reply_news:
        messages.append({
            "role": "user",
            "content": f"[Context - owner is replying to this news]: {reply_news}",
        })
    messages.append({"role": "user", "content": user_message})

    client, is_or = _get_brain_client()

    try:
        if is_or:
            response = client.chat.completions.create(
                model="anthropic/claude-haiku-4-5",
                max_tokens=100,
                timeout=BRAIN_TIMEOUT,
                messages=[{"role": "system", "content": BRAIN_SYSTEM_PROMPT}] + messages,
            )
            raw = response.choices[0].message.content.strip()
        else:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system=BRAIN_SYSTEM_PROMPT,
                messages=messages,
            )
            raw = response.content[0].text.strip()

        result = _parse_brain_response(raw)

        if result["action"] != "unknown":
            _consecutive_failures = 0
            append_to_history("user", user_message)
            append_to_history("assistant", json.dumps(result))
        else:
            _consecutive_failures += 1
            if _consecutive_failures >= BRAIN_CIRCUIT_BREAKER_THRESHOLD:
                _brain_disabled = True
                logger.warning("[brain] Circuit breaker triggered — brain disabled, using keyword fallback")

        return result

    except Exception as e:
        _consecutive_failures += 1
        logger.warning(f"[brain] API error ({_consecutive_failures}/{BRAIN_CIRCUIT_BREAKER_THRESHOLD}): {e}")
        if _consecutive_failures >= BRAIN_CIRCUIT_BREAKER_THRESHOLD:
            _brain_disabled = True
            logger.warning("[brain] Circuit breaker triggered — brain disabled, using keyword fallback")
        return keyword_fallback(user_message)


def keyword_fallback(text: str) -> dict:
    """Simple keyword-based fallback when brain is unavailable."""
    lower = text.lower()
    if any(w in lower for w in ["publica", "sube", "manda", "dale", "va "]):
        if "thread" in lower:
            return {"action": "publish_threads_only", "instruction": ""}
        return {"action": "publish", "instruction": ""}
    if "nuevo" in lower or "regenera" in lower or "otra vez" in lower:
        return {"action": "regenerate", "instruction": ""}
    if "cancel" in lower or "olvida" in lower:
        return {"action": "cancel", "instruction": ""}
    return {"action": "unknown", "instruction": ""}


def log_brain_action(action: str, text: str = ""):
    """
    Log a slash command or button press to brain history so future
    call_brain() calls have context about what was just done.
    """
    append_to_history("user", text or action)
    append_to_history("assistant", json.dumps({"action": action, "instruction": ""}))
