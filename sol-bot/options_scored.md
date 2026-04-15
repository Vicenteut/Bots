# Sol Bot Dashboard — Framework Options & Integration Scoring

> Generated: 2026-04-08  
> Context: Single-operator VPS (Ubuntu 22.04, Hetzner), Python bot stack, Telegram as primary control surface
> Status: historical scoring note. Production Sol now uses a private FastAPI dashboard and Threads-only publishing.

---

## 1. FRAMEWORK COMPARISON

Scoring: 1 = poor, 5 = excellent. Higher = better across all criteria.

| Framework | Setup Complexity | Real-time Capability | Control Surface | Maintenance Burden | **Total** |
|-----------|:----------------:|:--------------------:|:---------------:|:-----------------:|:---------:|
| Streamlit | 3 | 2 | 2 | 3 | **10** |
| **FastAPI + htmx** | **3** | **5** | **5** | **4** | **17** |
| FastAPI + React SPA | 2 | 5 | 5 | 2 | 14 |
| Gradio | 4 | 2 | 2 | 3 | 11 |
| Panel / Dash (Plotly) | 2 | 3 | 3 | 2 | 10 |

---

### A. Streamlit — Score: 10/20

**What it is:** Python-first data app framework, reactive re-run model.

**Already running:** `sol-dashboard.service` on port 8501 (Streamlit, ~57.8 MB RAM).

| Criterion | Score | Notes |
|-----------|-------|-------|
| Setup complexity | 3/5 | Already installed and running — zero setup needed |
| Real-time capability | 2/5 | `st.empty()` + manual polling possible but awkward; `st.rerun()` blocks; no native SSE; WebSocket support is internal-only |
| Control surface | 2/5 | Side effects in callbacks work but re-run model causes race conditions with file mutations; subprocess calls require workarounds |
| Maintenance burden | 3/5 | Low: pure Python, no frontend build pipeline; but version drift breaks apps silently |

**Verdict:** Fine for read-only dashboards. Breaks down for bot control actions. The existing dashboard demonstrates this limitation — it's monitoring-only, not control.

**When to use:** Upgrade path if the team is Python-only and the scope stays read-only analytics.

---

### B. FastAPI + htmx — Score: 17/20 ★ RECOMMENDED

**What it is:** FastAPI serves HTML fragments via Jinja2 templates; htmx replaces targeted DOM elements via AJAX without a JS framework.

| Criterion | Score | Notes |
|-----------|-------|-------|
| Setup complexity | 3/5 | `pip install fastapi uvicorn jinja2`; htmx via CDN (no build step); ~1-2 hours to scaffold |
| Real-time capability | 5/5 | SSE (`EventSourceResponse`) for live log streaming; native in FastAPI; tested pattern |
| Control surface | 5/5 | HTTP POST endpoints are natural; can call `subprocess.run()`, mutate JSON files, send Telegram messages via `requests` |
| Maintenance burden | 4/5 | No JS build pipeline; htmx via CDN; Python-only backend; Jinja2 templates are readable |

**Key advantages for Sol bot:**
- `POST /api/publish` directly calls `_publish_both()` or invokes `python3 x_publisher.py` subprocess
- `GET /api/logs/stream` SSE endpoint: `yield f"data: {line}\n\n"` in a generator = live log tail in browser
- `POST /api/generate` calls `generate_tweet()` inline — no IPC overhead
- Auth: `HTTPBasic` middleware in FastAPI (5 lines) or nginx `auth_basic` directive
- Port 8502 — runs alongside existing Streamlit (8501) during transition

**Boilerplate estimate:** ~300 LOC for a functional MVP with all 5 panels (health, post manager, chat, mixed builder, log stream).

---

### C. FastAPI + React SPA — Score: 14/20

| Criterion | Score | Notes |
|-----------|-------|-------|
| Setup complexity | 2/5 | Node.js + npm + Vite/CRA build pipeline; `npm run build` to serve static files; ~half day of scaffolding |
| Real-time capability | 5/5 | WebSocket or SSE + React state; full flexibility |
| Control surface | 5/5 | Same FastAPI backend as option B |
| Maintenance burden | 2/5 | `node_modules`, build step, React version drift, TypeScript if you want type safety |

**Verdict:** The FastAPI backend is identical to option B. React adds complexity for zero functional gain for a single-operator tool. The build pipeline is the biggest liability on a VPS — a failed `npm install` during a deploy blocks the dashboard.

**When it makes sense:** If a second operator (non-technical) needs a polished UI, or if the dashboard grows into a multi-user product.

---

### D. Gradio — Score: 11/20

| Criterion | Score | Notes |
|-----------|-------|-------|
| Setup complexity | 4/5 | `pip install gradio`; ~30 min to prototype |
| Real-time capability | 2/5 | Streaming text output supported; no general SSE; no DOM control |
| Control surface | 2/5 | Designed for ML input/output; button callbacks limited to Python functions returning display values; no HTTP POST surface |
| Maintenance burden | 3/5 | Pure Python; but Gradio's opinionated layout fights anything non-standard |

**Verdict:** Excellent for the Sol chat panel in isolation. Useless for a full control dashboard. Don't mix.

---

### E. Panel / Dash (Plotly) — Score: 10/20

| Criterion | Score | Notes |
|-----------|-------|-------|
| Setup complexity | 2/5 | Both require learning their widget model; Dash adds React internally; Panel adds param/reactive model |
| Real-time capability | 3/5 | Periodic callbacks in Dash; WebSocket in Panel; neither is as clean as FastAPI SSE |
| Control surface | 3/5 | Python callbacks work but state management is complex for stateful bot operations |
| Maintenance burden | 2/5 | Heavy dependencies; Plotly Dash in particular has breaking changes between versions |

**Verdict:** Best fit for analytics-heavy dashboards (charts, time series). Overkill here — Sol bot doesn't have rich time-series data yet. Reconsider if analytics.db grows significantly.

---

## 2. INTEGRATION SCORING

Scoring: **Impact** = value to operator workflow (1-5), **Complexity** = implementation effort (1-5, lower = simpler). **ROI = Impact / Complexity**.

| # | Integration | Impact | Complexity | ROI | Notes |
|---|------------|:------:|:----------:|:---:|-------|
| 1 | Health monitor | 5 | 1 | **5.0** | Read 2 PID files + check `/proc/{pid}`; zero new code in bot |
| 2 | Post manager | 5 | 2 | **2.5** | Read `pending_tweet.json`; POST to `/api/publish`; char counter in JS |
| 3 | Live log stream | 4 | 1 | **4.0** | SSE endpoint tailing `sol_commands.log`; 20 LOC in FastAPI |
| 4 | Sol chat interface | 5 | 3 | **1.7** | Call `generate_tweet()` inline; format picker; char counter; no new bot logic |
| 5 | /mixed builder | 4 | 2 | **2.0** | Call `generate_combinada_tweet()`; textarea + preview + publish button |
| 6 | Scheduler view | 3 | 1 | **3.0** | Glob `pending_sched_*.json`; display + delete button; zero new bot logic |
| 7 | Tone validator | 3 | 3 | **1.0** | Character count (trivial) + AI-ism regex (medium) + rhetorical move detection (hard) |
| 8 | System prompt editor | 3 | 4 | **0.75** | Read/write `generator.py` constants + hot-reload signal; risky without tests |
| 9 | Model routing override | 2 | 2 | **1.0** | Add `model_override` param to `generate_tweet()`; UI dropdown |
| 10 | Post feed (publish history) | 4 | 2 | **2.0** | Requires adding `publish_log.json` to bot first (~30 LOC); then trivial to display |

### Top 5 by ROI

1. **Health monitor** (ROI 5.0) — 1 hour to build, eliminates SSH for process checks entirely
2. **Live log stream** (ROI 4.0) — 20 LOC backend, eliminates SSH for debugging, massive daily value
3. **Scheduler view** (ROI 3.0) — glob + JSON read, eliminates SSH for reviewing pending scheduled posts
4. **Post manager** (ROI 2.5) — direct control of most frequent workflow, replaces 2 Telegram round trips
5. **/mixed builder** (ROI 2.0) or **Post feed** (ROI 2.0) — tied; post feed requires a small bot change first

### Integration Detail Notes

**1. Health Monitor**
```python
# Trivial implementation
import os, psutil, json
from pathlib import Path

def get_process_status(pid_file: str) -> dict:
    try:
        pid = int(Path(pid_file).read_text().strip())
        p = psutil.Process(pid)
        return {"alive": True, "pid": pid, "uptime_s": time.time() - p.create_time()}
    except (FileNotFoundError, psutil.NoSuchProcess):
        return {"alive": False, "pid": None, "uptime_s": 0}
```

**3. Live Log Stream**
```python
# FastAPI SSE endpoint
from sse_starlette.sse import EventSourceResponse
import asyncio, aiofiles

@app.get("/api/logs/stream")
async def stream_logs():
    async def generator():
        async with aiofiles.open(LOG_PATH, 'r') as f:
            await f.seek(0, 2)  # seek to end
            while True:
                line = await f.readline()
                if line:
                    yield {"data": line.rstrip()}
                else:
                    await asyncio.sleep(0.5)
    return EventSourceResponse(generator())
```

**8. System Prompt Editor — Why Complexity 4:**
- `generator.py` embeds persona as Python string constants (not config file)
- Hot-reload requires either: (a) file watch + importlib.reload() [fragile], (b) move persona to `sol_persona.json` + load at generation time [safe but requires refactor], or (c) restart process on save [simplest but 5-10s downtime]
- Recommended approach if building: extract to `sol_persona.json` first (1-2 hours refactor), then editor is trivial

---

## 3. DEPLOYMENT RECOMMENDATION

### Stack
- **Runtime:** `uvicorn sol_dashboard_api:app --port 8502 --host 127.0.0.1`
- **Process manager:** systemd unit (`sol-dashboard-api.service`) with `Restart=always`
- **Reverse proxy:** nginx (already on VPS) — `proxy_pass http://127.0.0.1:8502`
- **Auth:** nginx `auth_basic` directive (single `.htpasswd` file — 2 lines of config)
- **TLS:** Caddy or existing nginx + Let's Encrypt (Caddy is simpler if adding fresh)

### Port Assignment
```
8501 — Existing Streamlit dashboard (keep until replaced)
8502 — New FastAPI + htmx dashboard
443  — nginx HTTPS → proxies to 8502 (after transition)
```

### systemd Unit (example)
```ini
[Unit]
Description=Sol Dashboard API
After=network.target

[Service]
User=root
WorkingDirectory=/root/x-bot/sol-bot
ExecStart=/usr/local/bin/uvicorn sol_dashboard_api:app --host 127.0.0.1 --port 8502
Restart=always
RestartSec=5
Environment="PYTHONPATH=/root/x-bot/sol-bot"

[Install]
WantedBy=multi-user.target
```

### nginx Config (snippet)
```nginx
server {
    listen 443 ssl;
    server_name sol.yourdomain.com;

    auth_basic "Sol Dashboard";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:8502;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location /api/logs/stream {
        proxy_pass http://127.0.0.1:8502;
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding on;
    }
}
```

### Python Dependencies to Add
```
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
jinja2>=3.1.0
sse-starlette>=1.8.0
aiofiles>=23.0.0
psutil>=5.9.0
```

### Migration Path from Streamlit
1. Deploy FastAPI + htmx on port 8502 (additive, no change to existing stack)
2. Test for 1 week alongside Streamlit
3. Update nginx to route HTTPS → 8502
4. Disable Streamlit: `systemctl stop sol-dashboard && systemctl disable sol-dashboard`
5. Reclaim ~58 MB RAM from Streamlit process
