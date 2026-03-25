#!/usr/bin/env python3
"""
filter.py — Sentiment filter for Sol Bot.
Prevents cold analytical posts during tragedies or high-sensitivity events.
"""

import logging

logger = logging.getLogger(__name__)

SENSITIVITY_KEYWORDS = [
    # Deaths / tragedies
    "muertos", "victimas", "víctimas", "masacre", "atentado",
    "terremoto", "tsunami", "explosion", "explosión", "tiroteo",
    "accidente aéreo", "accidente aereo", "derrumbe", "inundacion",
    "inundación", "incendio forestal", "huracán", "huracan",
    "ciclón", "ciclon", "catástrofe", "catastrofe",
    # Mass casualty
    "muertos en", "fallecidos", "heridos graves", "víctimas mortales",
    "victimas mortales", "cuerpos", "cadaveres", "cadáveres",
    # High political sensitivity
    "genocidio", "guerra nuclear", "ataque nuclear", "bomba nuclear",
    "arma biologica", "arma química", "arma quimica",
    # Terror
    "ataque terrorista", "terrorismo masivo", "bomba suicida",
    "rehenes", "secuestro masivo",
]

# Keywords that override sensitivity check (still newsworthy as WIRE)
OVERRIDE_KEYWORDS = [
    "mercado", "bolsa", "fed", "bitcoin", "crypto", "acuerdo",
    "sancion", "sanción", "arancel", "eleccion", "elección",
]


def is_sensitive(headline: str, summary: str = "") -> bool:
    """
    Returns True if the headline/summary contains high-sensitivity content
    that should be skipped for analytical posts.
    """
    text = (headline + " " + summary).lower()

    # Check overrides first — if clearly financial/political news, allow it
    if any(kw in text for kw in OVERRIDE_KEYWORDS):
        return False

    hit = next((kw for kw in SENSITIVITY_KEYWORDS if kw in text), None)
    if hit:
        logger.warning(f"[filter] Sensitive keyword '{hit}' in: {headline[:80]}")
        return True

    return False
