"""
settings.py — Centralized config for Sol Bot Dashboard.
All values read from environment variables with safe defaults.
"""
import os
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────
_DEFAULT_BASE = "/root/x-bot/sol-bot"
_DEFAULT_LOGS = "/root/x-bot/logs"

BASE_DIR     = Path(os.getenv("SOL_BASE_DIR", _DEFAULT_BASE))
LOG_DIR      = Path(os.getenv("SOL_LOG_DIR",  _DEFAULT_LOGS))
CONTEXT_FILE = BASE_DIR / "context.json"

# ── Auth ──────────────────────────────────────────────────────────────
# Store a SHA-256 hash of the password in the env var, not the plaintext.
# Generate: python3 -c "import hashlib; print(hashlib.sha256(b'yourpass').hexdigest())"
PASSWORD_HASH = os.getenv("DASHBOARD_PASSWORD_HASH", "")

# Session TTL in minutes (0 = never expire)
SESSION_TTL_MIN = int(os.getenv("DASHBOARD_SESSION_TTL_MIN", "60"))

# Max failed auth attempts before lockout (per session)
MAX_AUTH_ATTEMPTS = int(os.getenv("DASHBOARD_MAX_AUTH_ATTEMPTS", "5"))

# ── Refresh ───────────────────────────────────────────────────────────
REFRESH_INTERVAL = int(os.getenv("SOL_REFRESH_INTERVAL", "30"))

# ── Services to monitor ───────────────────────────────────────────────
MONITORED_SERVICES = os.getenv(
    "SOL_MONITORED_SERVICES", "xbot-monitor,sol-commands,sol-dashboard,cloudflared,sol-threads-analytics.timer,sol-rss-fetcher.timer"
).split(",")

# ── Cron schedule (CST = UTC-6, with 5-45 min random delay) ──────────
CRON_TIMES_CST = [
    (7,  30, "scheduler"),
    (11,  0, "scheduler"),
    (17,  0, "scheduler"),
]

# ── Log files ─────────────────────────────────────────────────────────
LOG_FILES = {
    "Scheduler":      LOG_DIR / "scheduler.log",
    "Calendar":       LOG_DIR / "calendar.log",
    "Analytics":      LOG_DIR / "analytics.log",
    "Trending":       LOG_DIR / "trending.log",
    "Cookie Monitor": LOG_DIR / "cookie.log",
}

# ── Model routing (display only) ─────────────────────────────────────
MODEL_MAP = {
    "WIRE":     "gemini-2.0-flash-001",
    "DEBATE":   "gemini-2.0-flash-001",
    "ANALISIS": "claude-sonnet-4-6",
    "CONEXION": "claude-sonnet-4-6",
}
TYPE_COLOR = {
    "WIRE":     "#e63946",
    "DEBATE":   "#f4a261",
    "ANALISIS": "#2a9d8f",
    "CONEXION": "#457b9d",
}
TYPE_EMOJI = {
    "WIRE":     "⚡",
    "DEBATE":   "🗣",
    "ANALISIS": "🔍",
    "CONEXION": "🔗",
}

# ── Startup validation ────────────────────────────────────────────────
def validate() -> list[str]:
    """Returns a list of warning strings. Empty = all good."""
    warnings = []
    if not BASE_DIR.exists():
        warnings.append(f"BASE_DIR not found: {BASE_DIR}")
    if not CONTEXT_FILE.exists():
        warnings.append(f"context.json not found: {CONTEXT_FILE}")
    if not LOG_DIR.exists():
        warnings.append(f"LOG_DIR not found: {LOG_DIR}")
    if not PASSWORD_HASH:
        warnings.append("DASHBOARD_PASSWORD_HASH is not set")
    return warnings
