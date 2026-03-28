#!/usr/bin/env python3
"""
dashboard.py — Sol Bot Live Monitor (v4)
Phase 3: UX + Advanced Observability
- Filters: tweet type, platform
- KPI panel with time-since-last, tweets/24h, tweets/1h
- Alert panel with OK/WARN/CRITICAL severity
- Trend chart (tweet type over time)
- Hourly activity heatmap
- Topic distribution
"""

import hashlib
import time
from datetime import datetime, timedelta
from collections import defaultdict

import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

try:
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

import settings as cfg
import data_providers as dp
import controls

# ── Page config ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="Sol Bot Monitor",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0a0a0a; color: #f5f5f5; }
    .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    h1, h2, h3 { color: #e63946 !important; }
    .metric-box {
        background: #111; border: 1px solid #333;
        border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;
    }
    .tweet-card {
        background: #111; border-left: 4px solid #e63946;
        border-radius: 4px; padding: 12px; margin-bottom: 10px; font-size: 14px;
    }
    .badge {
        display: inline-block; padding: 2px 8px; border-radius: 4px;
        font-size: 12px; font-weight: bold; margin-right: 4px;
    }
    .log-box {
        background: #0d0d0d; border: 1px solid #222; border-radius: 4px;
        padding: 10px; font-family: monospace; font-size: 12px;
        max-height: 300px; overflow-y: auto; white-space: pre-wrap; color: #aaa;
    }
    .warn-box {
        background: #1a1200; border: 1px solid #f4a261; border-radius: 6px;
        padding: 10px 14px; margin-bottom: 8px; font-size: 13px; color: #f4a261;
    }
    .alert-ok       { background:#001a0a; border-left:4px solid #2ecc71; border-radius:4px; padding:10px; margin-bottom:6px; }
    .alert-warn     { background:#1a1200; border-left:4px solid #f4a261; border-radius:4px; padding:10px; margin-bottom:6px; }
    .alert-critical { background:#1a0000; border-left:4px solid #e63946; border-radius:4px; padding:10px; margin-bottom:6px; }
    .kpi-label { color:#888; font-size:12px; margin-bottom:4px; }
    .kpi-value { font-size:26px; font-weight:bold; color:#e63946; }
    .kpi-sub   { color:#888; font-size:12px; }
</style>
""", unsafe_allow_html=True)

_PLOTLY_LAYOUT = dict(
    paper_bgcolor="#0a0a0a", plot_bgcolor="#111",
    font=dict(color="#aaa", size=12),
    margin=dict(l=20, r=20, t=30, b=20),
    showlegend=True,
    legend=dict(bgcolor="#111", bordercolor="#333", borderwidth=1),
)


# ══════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════

def _hash(pwd): return hashlib.sha256(pwd.encode()).hexdigest()

def _session_expired():
    if cfg.SESSION_TTL_MIN <= 0: return False
    at = st.session_state.get("auth_time")
    if not at: return False
    return (datetime.utcnow() - at).total_seconds() / 60 > cfg.SESSION_TTL_MIN

def check_auth():
    ss = st.session_state
    if "authenticated" not in ss:
        ss.authenticated = False; ss.auth_attempts = 0; ss.auth_time = None
    if ss.authenticated and _session_expired():
        ss.authenticated = False; ss.auth_time = None
        st.warning("Sesion expirada.")
    if ss.authenticated: return True

    st.markdown("# ⚡ Sol Bot Monitor"); st.markdown("---")
    if ss.auth_attempts >= cfg.MAX_AUTH_ATTEMPTS:
        st.error("Demasiados intentos. Recarga."); st.stop()
    _, col, _ = st.columns([1, 1.4, 1])
    with col:
        with st.form("lf", clear_on_submit=True):
            pwd = st.text_input("Contrasena", type="password")
            ok  = st.form_submit_button("Entrar", use_container_width=True)
        if ok:
            if _hash(pwd) == cfg.PASSWORD_HASH:
                ss.authenticated = True; ss.auth_time = datetime.utcnow(); ss.auth_attempts = 0
                st.rerun()
            else:
                ss.auth_attempts += 1
                st.error(f"Incorrecta. Intentos restantes: {cfg.MAX_AUTH_ATTEMPTS - ss.auth_attempts}")
    return False

if not check_auth(): st.stop()


# ══════════════════════════════════════════════════════════════════════
# NON-BLOCKING REFRESH
# ══════════════════════════════════════════════════════════════════════
_rc = st_autorefresh(interval=cfg.REFRESH_INTERVAL * 1000, limit=None, key="sar")

for w in cfg.validate():
    st.markdown(f'<div class="warn-box">⚠ {w}</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# DATA FETCH
# ══════════════════════════════════════════════════════════════════════
_t0      = time.perf_counter()
entries  = dp.get_context_entries()
kpis     = dp.get_tweet_kpis(entries)
services = dp.get_all_service_statuses()
next_run, next_eta = dp.get_next_run_cst()
_fetch_ms = round((time.perf_counter() - _t0) * 1000, 1)


# ══════════════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════════════
remaining_session = ""
if cfg.SESSION_TTL_MIN > 0 and st.session_state.get("auth_time"):
    elapsed = int((datetime.utcnow() - st.session_state.auth_time).total_seconds() / 60)
    remaining_session = f" · Sesion: {cfg.SESSION_TTL_MIN - elapsed}m"

st.markdown("# ⚡ Sol Bot — Monitor en Vivo")
st.caption(
    f"@napoleotics / @napoleotiks  ·  Refresh #{_rc}  ·  "
    f"Fetch: {_fetch_ms}ms  ·  {datetime.utcnow().strftime('%H:%M:%S UTC')}{remaining_session}"
)


# ══════════════════════════════════════════════════════════════════════
# ALERT PANEL
# ══════════════════════════════════════════════════════════════════════
def _compute_alerts(kpis, services):
    alerts = []
    svc = services[0] if services else None

    # Service health
    if svc and not svc["healthy"]:
        alerts.append(("CRITICAL", f"Servicio {svc['name']} esta {svc['state'].upper()}"))
    elif svc:
        alerts.append(("OK", f"Servicio {svc['name']} activo"))

    # Time since last tweet
    m = kpis.get("minutes_since_last")
    if m is None:
        alerts.append(("WARN", "No hay tweets en memoria"))
    elif m > 720:
        alerts.append(("CRITICAL", f"Sin tweets nuevos hace {m//60}h {m%60}m (>12h)"))
    elif m > 240:
        alerts.append(("WARN", f"Sin tweets nuevos hace {m//60}h {m%60}m (>4h)"))
    else:
        alerts.append(("OK", f"Ultimo tweet hace {m}m"))

    # 24h volume
    v24 = kpis.get("tweets_last_24h", 0)
    if v24 == 0:
        alerts.append(("CRITICAL", "0 tweets en las ultimas 24h"))
    elif v24 < 3:
        alerts.append(("WARN", f"Solo {v24} tweets en las ultimas 24h (normal: 6-12)"))
    else:
        alerts.append(("OK", f"{v24} tweets en las ultimas 24h"))

    return alerts

with st.expander("🚨 Panel de Alertas", expanded=True):
    alerts = _compute_alerts(kpis, services)
    for severity, msg in alerts:
        cls = {"OK": "alert-ok", "WARN": "alert-warn", "CRITICAL": "alert-critical"}[severity]
        icon = {"OK": "✅", "WARN": "⚠️", "CRITICAL": "🔴"}[severity]
        st.markdown(f'<div class="{cls}">{icon} <strong>{severity}</strong> — {msg}</div>',
                    unsafe_allow_html=True)

st.markdown("---")


# ══════════════════════════════════════════════════════════════════════
# KPI ROW
# ══════════════════════════════════════════════════════════════════════
svc0      = services[0] if services else {"healthy": False, "state": "unknown", "color": "#888"}
svc_lbl   = "● ACTIVO" if svc0["healthy"] else f"○ {svc0['state'].upper()}"
last_str  = kpis["last_tweet_ts"].strftime("%d/%m %H:%M") if kpis["last_tweet_ts"] else "-"
m         = kpis.get("minutes_since_last") or 0
ago_str   = f"hace {m}m" if m < 60 else f"hace {m//60}h {m%60}m"

c1, c2, c3, c4, c5 = st.columns(5)
for col, label, value, sub in [
    (c1, "MONITOR",         svc_lbl,                    ""),
    (c2, "PROXIMA PUBLI.",  next_run,                   next_eta),
    (c3, "TWEETS MEMORIA",  str(kpis["total"]),         ""),
    (c4, "ULTIMO TWEET",    last_str,                   ago_str),
    (c5, "ULTIMAS 24H",     str(kpis["tweets_last_24h"]), f"{kpis['tweets_last_1h']} en 1h"),
]:
    with col:
        color = svc0["color"] if label == "MONITOR" else ("#e63946" if label in ("TWEETS MEMORIA","ULTIMAS 24H") else "#f5f5f5")
        st.markdown(f"""<div class="metric-box">
            <div class="kpi-label">{label}</div>
            <div style="color:{color};font-size:{'18px' if label=='MONITOR' else '20px'};font-weight:bold">{value}</div>
            {'<div class="kpi-sub">'+sub+'</div>' if sub else ''}
        </div>""", unsafe_allow_html=True)

st.markdown("---")


# ══════════════════════════════════════════════════════════════════════
# FILTERS
# ══════════════════════════════════════════════════════════════════════
with st.expander("🔍 Filtros", expanded=False):
    fc1, fc2 = st.columns(2)
    with fc1:
        filter_types = st.multiselect(
            "Tipo de tweet",
            options=list(cfg.MODEL_MAP.keys()),
            default=list(cfg.MODEL_MAP.keys()),
        )
    with fc2:
        filter_platform = st.multiselect(
            "Plataforma",
            options=["x", "threads"],
            default=["x", "threads"],
        )

filtered = [
    e for e in entries
    if e.get("tweet_type", "").upper() in filter_types
    and e.get("platform", "x").lower() in [p.lower() for p in filter_platform]
]


# ══════════════════════════════════════════════════════════════════════
# ANALYTICS ROW: Charts
# ══════════════════════════════════════════════════════════════════════
st.markdown("### Analisis")
ca, cb = st.columns(2)

# ── Chart A: Type distribution pie ───────────────────────────────────
with ca:
    dist   = kpis["type_dist"]
    labels = list(dist.keys())
    values = list(dist.values())
    colors = [cfg.TYPE_COLOR[t] for t in labels]

    fig_pie = go.Figure(go.Pie(
        labels=labels, values=values,
        marker=dict(colors=colors, line=dict(color="#0a0a0a", width=2)),
        textinfo="label+percent",
        textfont=dict(color="#f5f5f5"),
        hole=0.4,
    ))
    fig_pie.update_layout(title="Distribucion por Tipo", **_PLOTLY_LAYOUT)
    st.plotly_chart(fig_pie, use_container_width=True)

# ── Chart B: Hourly activity heatmap (hour buckets) ──────────────────
with cb:
    hour_counts: dict[int, int] = defaultdict(int)
    for e in entries:
        try:
            ts = datetime.fromisoformat(e["timestamp"])
            hour_counts[ts.hour] += 1
        except Exception:
            pass

    hours  = list(range(24))
    counts = [hour_counts.get(h, 0) for h in hours]

    fig_bar = go.Figure(go.Bar(
        x=hours, y=counts,
        marker_color=[cfg.TYPE_COLOR["WIRE"] if c > 0 else "#222" for c in counts],
        text=counts, textposition="outside",
    ))
    fig_bar.update_layout(
        title="Actividad por Hora (UTC)",
        xaxis=dict(title="Hora UTC", tickmode="linear", dtick=2, gridcolor="#222"),
        yaxis=dict(title="Tweets", gridcolor="#222"),
        **_PLOTLY_LAYOUT
    )
    st.plotly_chart(fig_bar, use_container_width=True)

# ── Chart C: Timeline (if enough data) ───────────────────────────────
if len(entries) >= 3:
    times  = []
    ttypes = []
    for e in entries:
        try:
            times.append(datetime.fromisoformat(e["timestamp"]))
            ttypes.append(e.get("tweet_type", "WIRE").upper())
        except Exception:
            pass

    fig_line = go.Figure()
    for ttype in cfg.MODEL_MAP:
        tpts = [t for t, tt in zip(times, ttypes) if tt == ttype]
        if tpts:
            fig_line.add_trace(go.Scatter(
                x=tpts, y=[1] * len(tpts),
                mode="markers",
                name=f"{cfg.TYPE_EMOJI[ttype]} {ttype}",
                marker=dict(color=cfg.TYPE_COLOR[ttype], size=12, symbol="circle"),
            ))
    fig_line.update_layout(
        title="Timeline de Tweets",
        xaxis=dict(title="Hora", gridcolor="#222"),
        yaxis=dict(visible=False),
        height=180,
        **_PLOTLY_LAYOUT
    )
    st.plotly_chart(fig_line, use_container_width=True)

st.markdown("---")


# ══════════════════════════════════════════════════════════════════════
# MODEL ROUTING + TOPIC DIST
# ══════════════════════════════════════════════════════════════════════
cm, ct = st.columns([1.4, 1])

with cm:
    st.markdown("### Modelo por Tipo")
    for ttype, model in cfg.MODEL_MAP.items():
        color = cfg.TYPE_COLOR[ttype]
        emoji = cfg.TYPE_EMOJI[ttype]
        st.markdown(f"""<div style="display:flex;align-items:center;margin-bottom:8px;background:#111;
                    border-radius:6px;padding:10px 14px;border-left:4px solid {color}">
            <span style="font-size:18px;margin-right:10px">{emoji}</span>
            <span style="color:{color};font-weight:bold;width:90px">{ttype}</span>
            <span style="color:#aaa;font-size:13px;flex:1">{model}</span>
            <span style="color:#555;font-size:11px">OpenRouter</span>
        </div>""", unsafe_allow_html=True)

with ct:
    st.markdown("### Temas Mas Frecuentes")
    topic_dist = dict(sorted(kpis["topic_dist"].items(), key=lambda x: -x[1]))
    total_t = sum(topic_dist.values()) or 1
    for topic, count in list(topic_dist.items())[:6]:
        pct = count / total_t * 100
        st.markdown(f"""<div style="margin-bottom:7px">
            <div style="display:flex;justify-content:space-between;margin-bottom:2px">
                <span style="color:#aaa;font-size:13px">#{topic}</span>
                <span style="color:#888;font-size:12px">{count}</span>
            </div>
            <div style="background:#222;border-radius:4px;height:6px;overflow:hidden">
                <div style="background:#457b9d;width:{pct:.0f}%;height:100%;border-radius:4px"></div>
            </div>
        </div>""", unsafe_allow_html=True)

st.markdown("---")


# ══════════════════════════════════════════════════════════════════════
# RECENT TWEETS (filtered)
# ══════════════════════════════════════════════════════════════════════
st.markdown(f"### Tweets Recientes ({len(filtered)} mostrados)")
if not filtered:
    st.info("No hay tweets que coincidan con los filtros.")
else:
    for entry in reversed(filtered[-8:]):
        ttype    = entry.get("tweet_type", "WIRE").upper()
        color    = cfg.TYPE_COLOR.get(ttype, "#e63946")
        emoji    = cfg.TYPE_EMOJI.get(ttype, "⚡")
        platform = entry.get("platform", "x").upper()
        topic    = entry.get("topic_tag", "general")
        text     = entry.get("tweet_text", "")
        model    = cfg.MODEL_MAP.get(ttype, "-")
        try:
            ts = datetime.fromisoformat(entry["timestamp"]).strftime("%d/%m %H:%M")
        except Exception:
            ts = "-"
        st.markdown(f"""<div class="tweet-card" style="border-left-color:{color}">
            <div style="display:flex;gap:6px;margin-bottom:6px;flex-wrap:wrap">
                <span class="badge" style="background:{color};color:#000">{emoji} {ttype}</span>
                <span class="badge" style="background:#222;color:#aaa">{platform}</span>
                <span class="badge" style="background:#1a1a1a;color:#666">#{topic}</span>
                <span class="badge" style="background:#111;color:#555">{model}</span>
                <span style="margin-left:auto;color:#555;font-size:11px;align-self:center">{ts}</span>
            </div>
            <div style="color:#ddd;line-height:1.5">{text[:280]}{"..." if len(text) > 280 else ""}</div>
        </div>""", unsafe_allow_html=True)

st.markdown("---")


# ══════════════════════════════════════════════════════════════════════
# LOGS
# ══════════════════════════════════════════════════════════════════════
st.markdown("### Logs")
tab_names = ["Monitor (live)"] + list(cfg.LOG_FILES.keys())
log_tabs  = st.tabs(tab_names)

with log_tabs[0]:
    for svc_name in cfg.MONITORED_SERVICES:
        jdata = dp.get_journalctl(svc_name)
        if jdata["error_count"] > 0:
            st.warning(f"{jdata['error_count']} error(s) en logs de {svc_name}")
        st.markdown(f'<div class="log-box">{jdata["content"]}</div>', unsafe_allow_html=True)

for i, (name, path) in enumerate(cfg.LOG_FILES.items(), start=1):
    with log_tabs[i]:
        ldata = dp.get_log_tail(path)
        if ldata["available"] and ldata["error_count"] > 0:
            st.warning(f"{ldata['error_count']} linea(s) con error · {ldata['size_kb']} KB")
        elif not ldata["available"]:
            st.info(f"Log no disponible aun: {path.name}")
        st.markdown(f'<div class="log-box">{ldata["content"]}</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# PHASE 4 — OPERATIONAL CONTROLS
# ══════════════════════════════════════════════════════════════════════
controls.render_controls()

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════════════
st.markdown("---")
col_f, col_l = st.columns([4, 1])
with col_f:
    st.caption(
        f"Auto-refresh cada {cfg.REFRESH_INTERVAL}s (no-blocking)  ·  "
        f"Cache TTL: 15s  ·  Fetch: {_fetch_ms}ms  ·  "
        f"Tweets filtrados: {len(filtered)}/{len(entries)}"
    )
with col_l:
    if st.button("Cerrar sesion", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.auth_time = None
        st.rerun()
