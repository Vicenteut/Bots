#!/usr/bin/env python3
"""
dashboard.py — Armandito Personal Assistant Monitor
Streamlit dashboard for Armandito Bot
"""

import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
import streamlit as st
import os

# ── Auth ─────────────────────────────────────────────────────────────
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if st.session_state.authenticated:
        return True
    st.markdown("# 🤖 Armandito Dashboard")
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        pwd = st.text_input("Contrasena", type="password", placeholder="Ingresa la contrasena...")
        if st.button("Entrar", use_container_width=True):
            if pwd == "armandito2026":
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Contrasena incorrecta")
    return False

if not check_password():
    st.stop()

# ── Config ────────────────────────────────────────────────────────────
DB_PATH = "/root/armandito/armandito.db"
FILES_DIR = Path("/root/armandito/files")
REFRESH_INTERVAL = 60
ACCENT = "#1e90ff"

# ── Page setup ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Armandito Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(f"""
<style>
    .stApp {{ background-color: #0a0a0a; color: #f5f5f5; }}
    .block-container {{ padding-top: 1.5rem; padding-bottom: 1rem; }}
    h1, h2, h3 {{ color: {ACCENT} !important; }}
    .metric-box {{
        background: #111;
        border: 1px solid #222;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 8px;
    }}
    .folder-card {{
        background: #111;
        border-left: 4px solid {ACCENT};
        border-radius: 4px;
        padding: 12px;
        margin-bottom: 8px;
    }}
    .item-card {{
        background: #0d0d0d;
        border-left: 2px solid #333;
        border-radius: 4px;
        padding: 10px;
        margin: 6px 0;
        font-size: 13px;
    }}
    .badge {{
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: bold;
        margin-right: 4px;
    }}
    .status-pending {{ color: #f4a261; }}
    .status-done {{ color: #2ecc71; }}
    .priority-alta {{ color: #e63946; }}
    .priority-media {{ color: #f4a261; }}
    .priority-baja {{ color: #aaa; }}
</style>
""", unsafe_allow_html=True)


# ── DB helper ─────────────────────────────────────────────────────────
def query_db(sql, params=()):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        return []


# ── HEADER ────────────────────────────────────────────────────────────
st.markdown("# 🤖 Armandito — Dashboard Personal")
st.caption(f"Asistente personal via Telegram  ·  Actualiza cada {REFRESH_INTERVAL}s  ·  {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

# ── METRICS ROW ───────────────────────────────────────────────────────
tasks = query_db("SELECT * FROM tasks ORDER BY created_at DESC")
pending_tasks = [t for t in tasks if t.get("status") != "done"]
reminders = query_db("SELECT * FROM reminders WHERE status='pending' ORDER BY remind_at ASC")
notes = query_db("SELECT * FROM notes ORDER BY created_at DESC")
folders = query_db("SELECT * FROM folders ORDER BY name ASC")

col1, col2, col3, col4, col5 = st.columns(5)

metrics = [
    (col1, "TAREAS TOTAL", len(tasks), ACCENT),
    (col2, "PENDIENTES", len(pending_tasks), "#f4a261"),
    (col3, "RECORDATORIOS", len(reminders), "#9b59b6"),
    (col4, "NOTAS", len(notes), "#2ecc71"),
    (col5, "CARPETAS", len(folders), "#1e90ff"),
]
for col, label, value, color in metrics:
    with col:
        st.markdown(f"""<div class="metric-box">
            <div style="color:#888;font-size:11px;margin-bottom:4px">{label}</div>
            <div style="color:{color};font-size:28px;font-weight:bold">{value}</div>
        </div>""", unsafe_allow_html=True)

st.markdown("---")

# ── FOLDERS ───────────────────────────────────────────────────────────
st.markdown("### 📁 Carpetas")

if not folders:
    st.info("No hay carpetas creadas aun. Envia 'guardar en [carpeta]: contenido' a Armandito via Telegram.")
else:
    cols = st.columns(min(len(folders), 3))
    for i, folder in enumerate(folders):
        with cols[i % 3]:
            items = query_db(
                "SELECT * FROM folder_items WHERE folder_id=? ORDER BY created_at DESC LIMIT 20",
                (folder["folder_id"],)
            )
            with st.expander(f"📂 {folder['name']}  ({len(items)} items)"):
                if not items:
                    st.caption("Carpeta vacia")
                else:
                    for item in items:
                        title = item.get("title") or "(sin titulo)"
                        content = item.get("content", "")[:200]
                        ts = item.get("created_at", "")[:16] if item.get("created_at") else ""
                        st.markdown(f"""<div class="item-card">
                            <div style="color:{ACCENT};font-weight:bold;margin-bottom:4px">{title}</div>
                            <div style="color:#ccc">{content}{"..." if len(item.get("content","")) > 200 else ""}</div>
                            <div style="color:#555;font-size:11px;margin-top:4px">{ts}</div>
                        </div>""", unsafe_allow_html=True)

st.markdown("---")

# ── TASKS + REMINDERS ─────────────────────────────────────────────────
col_tasks, col_reminders = st.columns(2)

with col_tasks:
    st.markdown("### ✅ Tareas")
    if not tasks:
        st.info("No hay tareas. Dile a Armandito: 'tarea: [descripcion]'")
    else:
        for task in tasks[:10]:
            status = task.get("status", "pending")
            priority = task.get("priority", "media")
            title = task.get("title", "")
            due = task.get("due_date", "")[:10] if task.get("due_date") else ""

            status_color = "#2ecc71" if status == "done" else "#f4a261"
            status_icon = "✅" if status == "done" else "⏳"
            priority_color = {"alta": "#e63946", "media": "#f4a261", "baja": "#888"}.get(priority, "#888")

            st.markdown(f"""<div style="background:#111;border-radius:6px;padding:10px;margin-bottom:6px;
                        border-left:3px solid {status_color}">
                <div style="display:flex;justify-content:space-between">
                    <span style="color:#f5f5f5;font-size:14px">{status_icon} {title}</span>
                    <span style="color:{priority_color};font-size:11px">{priority.upper()}</span>
                </div>
                {f'<div style="color:#555;font-size:11px;margin-top:4px">Vence: {due}</div>' if due else ''}
            </div>""", unsafe_allow_html=True)

with col_reminders:
    st.markdown("### ⏰ Recordatorios")
    if not reminders:
        st.info("No hay recordatorios. Dile: 'recordame [algo] el [dia] a las [hora]'")
    else:
        for rem in reminders[:10]:
            msg = rem.get("message", "")
            remind_at = rem.get("remind_at", "")[:16] if rem.get("remind_at") else ""
            repeat = rem.get("repeat_type", "none")
            repeat_badge = f"🔁 {repeat}" if repeat and repeat != "none" else ""

            st.markdown(f"""<div style="background:#111;border-radius:6px;padding:10px;margin-bottom:6px;
                        border-left:3px solid #9b59b6">
                <div style="color:#f5f5f5;font-size:14px">⏰ {msg[:80]}{"..." if len(msg) > 80 else ""}</div>
                <div style="display:flex;gap:8px;margin-top:4px">
                    <span style="color:#9b59b6;font-size:11px">{remind_at}</span>
                    {f'<span style="color:#555;font-size:11px">{repeat_badge}</span>' if repeat_badge else ''}
                </div>
            </div>""", unsafe_allow_html=True)

st.markdown("---")

# ── NOTES ─────────────────────────────────────────────────────────────
st.markdown("### 📝 Notas Recientes")

if not notes:
    st.info("No hay notas. Dile a Armandito: 'nota: [contenido]'")
else:
    cols_notes = st.columns(2)
    for i, note in enumerate(notes[:10]):
        with cols_notes[i % 2]:
            title = note.get("title") or "(sin titulo)"
            content = note.get("content", "")
            tags = note.get("tags", "")
            ts = note.get("created_at", "")[:16] if note.get("created_at") else ""
            st.markdown(f"""<div style="background:#111;border-radius:6px;padding:12px;margin-bottom:8px;
                        border-top:2px solid #2ecc71">
                <div style="color:#2ecc71;font-weight:bold;margin-bottom:6px">{title}</div>
                <div style="color:#ccc;font-size:13px;line-height:1.5">{content[:200]}{"..." if len(content) > 200 else ""}</div>
                <div style="display:flex;justify-content:space-between;margin-top:6px">
                    <span style="color:#555;font-size:11px">{tags}</span>
                    <span style="color:#444;font-size:11px">{ts}</span>
                </div>
            </div>""", unsafe_allow_html=True)

st.markdown("---")

# ── FILE BROWSER ──────────────────────────────────────────────────────
st.markdown("### 🗂 Archivos Guardados")

if not FILES_DIR.exists() or not list(FILES_DIR.iterdir()):
    st.info("No hay archivos guardados aun.")
else:
    try:
        all_files = []
        for subdir in sorted(FILES_DIR.iterdir()):
            if subdir.is_dir():
                for f in subdir.iterdir():
                    if f.is_file():
                        size = f.stat().st_size
                        size_str = f"{size/1024:.1f} KB" if size > 1024 else f"{size} B"
                        all_files.append({
                            "nombre": f.name,
                            "carpeta_id": subdir.name,
                            "tamano": size_str,
                            "modificado": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
                        })

        if all_files:
            st.dataframe(
                all_files,
                column_config={
                    "nombre": "Archivo",
                    "carpeta_id": "ID Carpeta",
                    "tamano": "Tamano",
                    "modificado": "Modificado"
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No hay archivos en el directorio.")
    except Exception as e:
        st.error(f"Error leyendo archivos: {e}")

# ── Armandito service status ───────────────────────────────────────────
st.markdown("---")
try:
    result = subprocess.run(
        ["systemctl", "is-active", "armandito"],
        capture_output=True, text=True, timeout=3
    )
    status = result.stdout.strip()
    color = "#2ecc71" if status == "active" else "#e63946"
    st.markdown(f"""<div style="background:#111;border-radius:6px;padding:10px;display:inline-block">
        <span style="color:#888;font-size:12px">Servicio Armandito: </span>
        <span style="color:{color};font-weight:bold">{status.upper()}</span>
    </div>""", unsafe_allow_html=True)
except Exception:
    pass

st.caption(f"Proxima actualizacion en {REFRESH_INTERVAL} segundos")

import time
time.sleep(REFRESH_INTERVAL)
st.rerun()
