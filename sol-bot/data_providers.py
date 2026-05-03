"""
data_providers.py — Data layer for Sol Bot Dashboard.
All I/O goes through here. Cached with TTL. UI never calls subprocess directly.
"""
import json
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import streamlit as st
import settings as cfg


# ══════════════════════════════════════════════════════════════════════
# TTL Cache (in-process, per Streamlit session)
# ══════════════════════════════════════════════════════════════════════

class _TTLCache:
    """Lightweight in-memory TTL cache stored in st.session_state."""

    def __init__(self, ttl_seconds: int = 15):
        self.ttl = ttl_seconds
        if "_dp_cache" not in st.session_state:
            st.session_state._dp_cache = {}

    def get(self, key: str) -> tuple[bool, Any]:
        entry = st.session_state._dp_cache.get(key)
        if entry is None:
            return False, None
        value, ts = entry
        if time.monotonic() - ts > self.ttl:
            del st.session_state._dp_cache[key]
            return False, None
        return True, value

    def set(self, key: str, value: Any) -> None:
        st.session_state._dp_cache[key] = (value, time.monotonic())

    def invalidate(self, key: str) -> None:
        st.session_state._dp_cache.pop(key, None)


_cache = _TTLCache(ttl_seconds=15)


# ══════════════════════════════════════════════════════════════════════
# Data Providers (all with graceful degradation)
# ══════════════════════════════════════════════════════════════════════

def get_context_entries() -> list:
    """Load tweets from context.json. Returns [] on any failure."""
    hit, val = _cache.get("context")
    if hit:
        return val
    try:
        with open(cfg.CONTEXT_FILE) as f:
            data = json.load(f)
        _cache.set("context", data)
        return data
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []
    except Exception:
        return []


def get_service_status(name: str) -> dict:
    """
    Returns dict with keys: name, state, color, healthy.
    Never raises — returns degraded state on failure.
    """
    cache_key = f"svc_{name}"
    hit, val = _cache.get(cache_key)
    if hit:
        return val

    result = {"name": name, "state": "unknown", "color": "#888", "healthy": False}
    try:
        r = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True, timeout=3
        )
        state = r.stdout.strip()
        result["state"] = state
        if state == "active":
            result["color"] = "#2ecc71"
            result["healthy"] = True
        elif state in ("inactive", "failed"):
            result["color"] = "#e63946"
        else:
            result["color"] = "#f39c12"
    except subprocess.TimeoutExpired:
        result["state"] = "timeout"
        result["color"] = "#f39c12"
    except Exception:
        result["state"] = "error"

    _cache.set(cache_key, result)
    return result


def get_all_service_statuses() -> list[dict]:
    return [get_service_status(svc) for svc in cfg.MONITORED_SERVICES]


def get_log_tail(path: Path, lines: int = 50) -> dict:
    """Returns dict with content, line_count, error_count, size_kb."""
    cache_key = f"log_{path.name}_{lines}"
    hit, val = _cache.get(cache_key)
    if hit:
        return val

    result = {
        "content": "",
        "line_count": 0,
        "error_count": 0,
        "size_kb": 0.0,
        "available": False,
        "path": str(path),
    }
    try:
        if path.exists():
            result["size_kb"] = round(path.stat().st_size / 1024, 1)
            r = subprocess.run(
                ["tail", f"-{lines}", str(path)],
                capture_output=True, text=True, timeout=3
            )
            content = r.stdout or "(sin entradas)"
            result["content"] = content
            result["line_count"] = content.count("\n")
            result["error_count"] = sum(
                1 for line in content.splitlines()
                if any(w in line.lower() for w in ("error", "exception", "traceback", "critical"))
            )
            result["available"] = True
        else:
            result["content"] = f"(archivo no encontrado: {path.name})"
    except Exception as e:
        result["content"] = f"(error leyendo log: {e})"

    _cache.set(cache_key, result)
    return result


def get_journalctl(service: str, lines: int = 40) -> dict:
    """Returns journalctl output dict with content and error_count."""
    cache_key = f"journal_{service}_{lines}"
    hit, val = _cache.get(cache_key)
    if hit:
        return val

    result = {"content": "", "error_count": 0, "available": False}
    try:
        r = subprocess.run(
            ["journalctl", "-u", service, "--no-pager",
             f"-n{lines}", "--output=short"],
            capture_output=True, text=True, timeout=5
        )
        content = r.stdout or "(sin logs)"
        result["content"] = content
        result["error_count"] = sum(
            1 for line in content.splitlines()
            if any(w in line.lower() for w in ("error", "exception", "failed", "critical"))
        )
        result["available"] = True
    except subprocess.TimeoutExpired:
        result["content"] = "(journalctl timeout — servicio puede estar lento)"
    except Exception as e:
        result["content"] = f"(error: {e})"

    _cache.set(cache_key, result)
    return result


def get_tweet_kpis(entries: list) -> dict:
    """Compute KPIs from context entries."""
    now = datetime.utcnow()
    kpis = {
        "total": len(entries),
        "last_tweet_ts": None,
        "minutes_since_last": None,
        "tweets_last_24h": 0,
        "tweets_last_1h": 0,
        "type_dist": {k: 0 for k in cfg.MODEL_MAP},
        "platform_dist": {},
        "topic_dist": {},
    }

    for e in entries:
        try:
            ts = datetime.fromisoformat(e["timestamp"])
            age_min = (now - ts).total_seconds() / 60
            if age_min <= 60:
                kpis["tweets_last_1h"] += 1
            if age_min <= 1440:
                kpis["tweets_last_24h"] += 1
            if kpis["last_tweet_ts"] is None or ts > kpis["last_tweet_ts"]:
                kpis["last_tweet_ts"] = ts
                kpis["minutes_since_last"] = int(age_min)
        except Exception:
            pass

        ttype = e.get("tweet_type", "").upper()
        if ttype in kpis["type_dist"]:
            kpis["type_dist"][ttype] += 1

        plat = e.get("platform", "unknown")
        kpis["platform_dist"][plat] = kpis["platform_dist"].get(plat, 0) + 1

        topic = e.get("topic_tag", "general")
        kpis["topic_dist"][topic] = kpis["topic_dist"].get(topic, 0) + 1

    return kpis


def get_next_run_cst() -> tuple[str, str]:
    now_cst = datetime.utcnow() - timedelta(hours=6)
    candidates = []
    for h, m, label in cfg.CRON_TIMES_CST:
        t = now_cst.replace(hour=h, minute=m, second=0, microsecond=0)
        if t <= now_cst:
            t += timedelta(days=1)
        candidates.append((t, label))
    candidates.sort(key=lambda x: x[0])
    nxt, lbl = candidates[0]
    mins = int((nxt - now_cst).total_seconds() / 60)
    h, m = divmod(mins, 60)
    return f"{nxt.strftime('%H:%M')} CST ({lbl})", f"+{h}h {m}m (+ 5-45 min delay)"
