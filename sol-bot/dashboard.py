#!/usr/bin/env python3
"""
dashboard.py — Sol Bot Live Monitor
Streamlit dashboard for @napoleotics / @napoleotiks
"""

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
import streamlit as st

# ── Auth ─────────────────────────────────────────────────────────────
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if st.session_state.authenticated:
        return True
    st.markdown("# ⚡ Sol Bot Monitor")
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        pwd = st.text_input("Contrasena", type="password", placeholder="Ingresa la contrasena...")
        if st.button("Entrar", use_container_width=True):
            if pwd == "sol2026":
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Contrasena incorrecta")
    return False

if not check_password():
    st.stop()

# ── Config ──────────────────────────────────────────────────────────
BASE_DIR = Path("/root/x-bot/sol-bot")
CONTEXT_FILE = BASE_DIR / "context.json"
LOG_DIR = Path("/root/x-bot/logs")
REFRESH_INTERVAL = 30

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
    "WIRE": "⚡",
    "DEBATE": "🗣",
    "ANALISIS": "🔍",
    "CONEXION": "🔗",
}

# Cron schedule (CST = UTC-6) with 5-45 min random delay
CRON_TIMES_CST = [
    (7, 30, "scheduler"),
    (11, 0, "scheduler"),
    (17, 0, "scheduler"),
]

# ── Page setup ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="Sol Bot Monitor",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    .stApp { background-color: #0a0a0a; color: #f5f5f5; }
    .block-container { padding-top: 1.5rem; padding-bottom: 1rem; }
    h1, h2, h3 { color: #e63946 !important; }
    .metric-box {
        background: #111;
        border: 1px solid #333;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 8px;
    }
    .tweet-card {
        background: #111;
        border-left: 4px solid #e63946;
        border-radius: 4px;
        padding: 12px;
        margin-bottom: 10px;
        font-size: 14px;
    }
    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: bold;
        margin-right: 4px;
    }
    .log-box {
        background: #0d0d0d;
        border: 1px solid #222;
        border-radius: 4px;
        padding: 10px;
        font-family: monospace;
        font-size: 12px;
        max-height: 300px;
        overflow-y: auto;
        white-space: pre-wrap;
        color: #aaa;
    }
    div[data-testid="stMetricValue"] { color: #e63946 !important; font-size: 1.6rem !important; }
    div[data-testid="stMetricLabel"] { color: #888 !important; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────

def load_context():
    try:
        with open(CONTEXT_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def service_status(name):
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True, timeout=3
        )
        active = result.stdout.strip()
        if active == "active":
            return "● ACTIVO", "#2ecc71"
        return f"○ {active.upper()}", "#e63946"
    except Exception:
        return "? ERROR", "#f39c12"


def read_log(path, lines=50):
    try:
        result = subprocess.run(
            ["tail", f"-{lines}", str(path)],
            capture_output=True, text=True, timeout=3
        )
        return result.stdout or "(sin entradas)"
    except Exception:
        return f"(no se pudo leer {Path(path).name})"


def next_run_cst():
    now_utc = datetime.utcnow()
    now_cst = now_utc - timedelta(hours=6)
    candidates = []
    for h, m, label in CRON_TIMES_CST:
        t = now_cst.replace(hour=h, minute=m, second=0, microsecond=0)
        if t <= now_cst:
            t += timedelta(days=1)
        candidates.append((t, label))
    candidates.sort(key=lambda x: x[0])
    next_t, next_label = candidates[0]
    delta = next_t - now_cst
    total_min = int(delta.total_seconds() / 60)
    hours, mins = divmod(total_min, 60)
    base_time = f"{next_t.strftime('%H:%M')} CST ({next_label})"
    eta = f"+{hours}h {mins}m (+ 5-45 min delay)"
    return base_time, eta


def tweet_type_dist(entries):
    counts = {"WIRE": 0, "DEBATE": 0, "ANALISIS": 0, "CONEXION": 0}
    for e in entries:
        t = e.get("tweet_type", "").upper()
        if t in counts:
            counts[t] += 1
    return counts


# ── HEADER ───────────────────────────────────────────────────────────
st.markdown("# ⚡ Sol Bot — Monitor en Vivo")
st.caption(f"@napoleotics / @napoleotiks  ·  Actualiza cada {REFRESH_INTERVAL}s  ·  {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

# ── ROW 1: Status metrics ─────────────────────────────────────────────
col1, col2, col3, col4 = st.columns([1.2, 1.5, 1.2, 1.2])

monitor_status, monitor_color = service_status("xbot-monitor")
entries = load_context()

with col1:
    st.markdown(f"""<div class="metric-box">
        <div style="color:#888;font-size:12px;margin-bottom:4px">MONITOR</div>
        <div style="color:{monitor_color};font-size:18px;font-weight:bold">{monitor_status}</div>
    </div>""", unsafe_allow_html=True)

next_run, next_eta = next_run_cst()
with col2:
    st.markdown(f"""<div class="metric-box">
        <div style="color:#888;font-size:12px;margin-bottom:4px">PROXIMA PUBLICACION</div>
        <div style="color:#f5f5f5;font-size:15px;font-weight:bold">{next_run}</div>
        <div style="color:#888;font-size:12px">{next_eta}</div>
    </div>""", unsafe_allow_html=True)

with col3:
    st.markdown(f"""<div class="metric-box">
        <div style="color:#888;font-size:12px;margin-bottom:4px">TWEETS EN MEMORIA</div>
        <div style="color:#e63946;font-size:28px;font-weight:bold">{len(entries)}</div>
    </div>""", unsafe_allow_html=True)

last_ts = "-"
if entries:
    try:
        ts = datetime.fromisoformat(entries[-1]["timestamp"])
        last_ts = ts.strftime("%d/%m %H:%M")
    except Exception:
        pass
with col4:
    st.markdown(f"""<div class="metric-box">
        <div style="color:#888;font-size:12px;margin-bottom:4px">ULTIMO TWEET</div>
        <div style="color:#f5f5f5;font-size:20px;font-weight:bold">{last_ts}</div>
    </div>""", unsafe_allow_html=True)

st.markdown("---")

# ── ROW 2: Model routing + Distribution ──────────────────────────────
col_left, col_right = st.columns([1.4, 1])

with col_left:
    st.markdown("### Modelo por Tipo de Tweet")
    for ttype, model in MODEL_MAP.items():
        color = TYPE_COLOR[ttype]
        emoji = TYPE_EMOJI[ttype]
        st.markdown(f"""<div style="display:flex;align-items:center;margin-bottom:8px;background:#111;
                    border-radius:6px;padding:10px 14px;border-left:4px solid {color}">
            <span style="font-size:18px;margin-right:10px">{emoji}</span>
            <span style="color:{color};font-weight:bold;width:90px">{ttype}</span>
            <span style="color:#aaa;font-size:13px;flex:1">{model}</span>
            <span style="color:#555;font-size:11px">via OpenRouter</span>
        </div>""", unsafe_allow_html=True)

with col_right:
    st.markdown("### Distribucion (ultimas 15)")
    dist = tweet_type_dist(entries)
    total = sum(dist.values()) or 1
    for ttype, count in dist.items():
        color = TYPE_COLOR[ttype]
        pct = count / total * 100
        st.markdown(f"""<div style="margin-bottom:8px">
            <div style="display:flex;justify-content:space-between;margin-bottom:3px">
                <span style="color:{color};font-weight:bold;font-size:13px">{TYPE_EMOJI[ttype]} {ttype}</span>
                <span style="color:#888;font-size:13px">{count}</span>
            </div>
            <div style="background:#222;border-radius:4px;height:8px;overflow:hidden">
                <div style="background:{color};width:{pct:.0f}%;height:100%;border-radius:4px"></div>
            </div>
        </div>""", unsafe_allow_html=True)

st.markdown("---")

# ── ROW 3: Recent tweets ──────────────────────────────────────────────
st.markdown("### Tweets Recientes")

if not entries:
    st.info("No hay tweets en context.json aun.")
else:
    for entry in reversed(entries[-8:]):
        ttype = entry.get("tweet_type", "WIRE").upper()
        color = TYPE_COLOR.get(ttype, "#e63946")
        emoji = TYPE_EMOJI.get(ttype, "X")
        platform = entry.get("platform", "x").upper()
        topic = entry.get("topic_tag", "general")
        text = entry.get("tweet_text", "")
        try:
            ts = datetime.fromisoformat(entry["timestamp"]).strftime("%d/%m %H:%M")
        except Exception:
            ts = "-"
        model_short = MODEL_MAP.get(ttype, "-")

        st.markdown(f"""<div class="tweet-card" style="border-left-color:{color}">
            <div style="display:flex;gap:6px;margin-bottom:6px;flex-wrap:wrap">
                <span class="badge" style="background:{color};color:#000">{emoji} {ttype}</span>
                <span class="badge" style="background:#222;color:#aaa">{platform}</span>
                <span class="badge" style="background:#1a1a1a;color:#666">#{topic}</span>
                <span class="badge" style="background:#111;color:#555">{model_short}</span>
                <span style="margin-left:auto;color:#555;font-size:11px;align-self:center">{ts}</span>
            </div>
            <div style="color:#ddd;line-height:1.5">{text[:280]}{"..." if len(text) > 280 else ""}</div>
        </div>""", unsafe_allow_html=True)

st.markdown("---")

# ── ROW 4: Logs ───────────────────────────────────────────────────────
st.markdown("### Logs")

log_tabs = st.tabs(["Scheduler", "Monitor (live)", "Calendar", "Analytics"])

with log_tabs[0]:
    content = read_log(LOG_DIR / "scheduler.log")
    st.markdown(f'<div class="log-box">{content}</div>', unsafe_allow_html=True)

with log_tabs[1]:
    try:
        result = subprocess.run(
            ["journalctl", "-u", "xbot-monitor", "--no-pager", "-n", "40", "--output=short"],
            capture_output=True, text=True, timeout=5
        )
        monitor_log = result.stdout or "(sin logs)"
    except Exception:
        monitor_log = "(error leyendo journalctl)"
    st.markdown(f'<div class="log-box">{monitor_log}</div>', unsafe_allow_html=True)

with log_tabs[2]:
    content = read_log(LOG_DIR / "calendar.log")
    st.markdown(f'<div class="log-box">{content}</div>', unsafe_allow_html=True)

with log_tabs[3]:
    content = read_log(LOG_DIR / "analytics.log")
    st.markdown(f'<div class="log-box">{content}</div>', unsafe_allow_html=True)

# ── Auto-refresh ──────────────────────────────────────────────────────
st.markdown("---")
st.caption(f"Proxima actualizacion en {REFRESH_INTERVAL} segundos")

import time
time.sleep(REFRESH_INTERVAL)
st.rerun()
