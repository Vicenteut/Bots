"""
controls.py — Safe operational controls for Sol Bot Dashboard.
Phase 4: Every action requires confirmation + is written to audit.log.
"""
import os
import subprocess
import json
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st
import settings as cfg

AUDIT_LOG = cfg.LOG_DIR / "dashboard_audit.log"
AUDIT_LOG_LOCK = cfg.LOG_DIR / "dashboard_audit.lock"

try:
    from filelock import FileLock as _FileLock
    _HAS_FILELOCK = True
except ImportError:
    _HAS_FILELOCK = False


# ── Audit trail ───────────────────────────────────────────────────────
def _audit(action: str, result: str, detail: str = "") -> None:
    """Append one JSON line to the audit log atomically."""
    entry = {
        "ts":     datetime.utcnow().isoformat(),
        "action": action,
        "result": result,
        "detail": detail,
    }
    line = json.dumps(entry) + "\n"
    try:
        if _HAS_FILELOCK:
            with _FileLock(str(AUDIT_LOG_LOCK), timeout=5):
                with open(AUDIT_LOG, "a", encoding="utf-8") as f:
                    f.write(line)
        else:
            with open(AUDIT_LOG, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception as e:
        st.warning(f"Audit log write failed: {e}")


def _run_safe(cmd: list, timeout: int = 10) -> tuple[bool, str]:
    """Run a system command safely. Returns (success, output)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        ok = r.returncode == 0
        out = (r.stdout + r.stderr).strip()
        return ok, out
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


# ── Controls UI ───────────────────────────────────────────────────────
def render_controls() -> None:
    """Render the operational controls panel."""
    st.markdown("### ⚙️ Controles Operacionales")
    st.caption("Todas las acciones requieren confirmacion y quedan en el audit log.")

    # ── Service controls ─────────────────────────────────────────────
    with st.expander("🔧 Servicios", expanded=False):
        for svc in cfg.MONITORED_SERVICES:
            st.markdown(f"**{svc}**")
            c1, c2, c3 = st.columns(3)

            key_restart = f"confirm_restart_{svc}"
            key_stop    = f"confirm_stop_{svc}"

            with c1:
                if st.button(f"↺ Reiniciar", key=f"btn_restart_{svc}"):
                    st.session_state[key_restart] = True

            with c2:
                if st.button(f"■ Detener", key=f"btn_stop_{svc}",
                             disabled=svc == "sol-dashboard"):
                    st.session_state[key_stop] = True

            with c3:
                if st.button(f"▶ Iniciar", key=f"btn_start_{svc}"):
                    ok, out = _run_safe(["systemctl", "start", svc])
                    _audit("start_service", "ok" if ok else "error", f"{svc}: {out[:200]}")
                    st.success(f"Iniciado: {svc}") if ok else st.error(f"Error: {out[:200]}")

            # Confirmation dialogs
            if st.session_state.get(key_restart):
                st.warning(f"¿Confirmas reiniciar **{svc}**? Esto interrumpira sesiones activas.")
                ya, no = st.columns(2)
                with ya:
                    if st.button("Si, reiniciar", key=f"yes_restart_{svc}"):
                        ok, out = _run_safe(["systemctl", "restart", svc])
                        _audit("restart_service", "ok" if ok else "error", f"{svc}: {out[:200]}")
                        st.session_state[key_restart] = False
                        st.success(f"Reiniciado: {svc}") if ok else st.error(out[:200])
                with no:
                    if st.button("Cancelar", key=f"no_restart_{svc}"):
                        st.session_state[key_restart] = False
                        st.rerun()

            if st.session_state.get(key_stop):
                st.error(f"¿Confirmas **DETENER** {svc}? El monitor dejara de publicar.")
                ya, no = st.columns(2)
                with ya:
                    if st.button("Si, detener", key=f"yes_stop_{svc}"):
                        ok, out = _run_safe(["systemctl", "stop", svc])
                        _audit("stop_service", "ok" if ok else "error", f"{svc}: {out[:200]}")
                        st.session_state[key_stop] = False
                        st.success(f"Detenido: {svc}") if ok else st.error(out[:200])
                with no:
                    if st.button("Cancelar", key=f"no_stop_{svc}"):
                        st.session_state[key_stop] = False
                        st.rerun()

    # ── Audit log viewer ─────────────────────────────────────────────
    with st.expander("📋 Audit Log", expanded=False):
        if AUDIT_LOG.exists():
            lines = AUDIT_LOG.read_text().strip().split("\n")[-20:]
            for line in reversed(lines):
                try:
                    e = json.loads(line)
                    color = "#2ecc71" if e["result"] == "ok" else "#e63946"
                    ts    = e["ts"][:19].replace("T", " ")
                    st.markdown(
                        f'<div style="font-family:monospace;font-size:12px;padding:3px 0;'
                        f'border-bottom:1px solid #222;color:#aaa">'
                        f'<span style="color:#555">{ts}</span>  '
                        f'<span style="color:{color};font-weight:bold">[{e["result"].upper()}]</span>  '
                        f'<span style="color:#f5f5f5">{e["action"]}</span>  '
                        f'<span style="color:#666">{e.get("detail","")[:80]}</span></div>',
                        unsafe_allow_html=True
                    )
                except Exception:
                    st.text(line[:120])
        else:
            st.info("No hay acciones registradas aun.")
