# Sol Bot Dashboard — Executive Proposal

> Generated: 2026-04-08  
> Stack: FastAPI + htmx · uvicorn · nginx · systemd  
> See also: `friction_audit.md`, `options_scored.md`

---

## 1. DIAGNOSIS

Six specific breakdowns in the current Telegram-only workflow:

**1. No publish history exists.**  
`x_publisher.py` and `threads_publisher.py` print tweet IDs to stdout and return — they write nothing persistent. `context.json` holds the last 15 tweet texts but no platform success/failure, no tweet IDs, no timestamps queryable without SSH. Every published post effectively vanishes from the operator's view.

**2. Silent failures are endemic.**  
`monitor.py` filters videos >60s and messages <5 chars to stdout only — no Telegram alert. `scheduler.py` activates silent days (3.3% probability) and skips all-sensitive headline batches, both logged only. `threads_publisher.py` uses a text-only fallback when media upload fails but sends "Publicado en Threads" to Telegram regardless. The operator has no reliable signal when something goes wrong.

**3. The subprocess publish race condition is unresolved.**  
`_publish_x()` has a 180-second timeout (L911 `sol_commands.py`). When the timeout fires, the bot sends "Timeout publicando en X" to Telegram — but the subprocess continues running and frequently succeeds. `pending_tweet.json` is already deleted at this point. The operator sees a failure notification for a post that actually published.

**4. Regeneration format selection requires slash commands.**  
The inline publish keyboard's 🔄 Regenerar button calls `cmd_regen("RANDOM")` — format is random. To regenerate as a specific format (WIRE, ANALISIS, DEBATE, CONEXION), the operator must type `/wire`, `/analisis`, etc. There's no format picker on the keyboard itself.

**5. Brain circuit breaker is invisible.**  
When brain.py hits 3 consecutive API failures, `_brain_disabled` flips to `True` and keyword fallback activates silently. The operator continues typing natural language expecting brain classification, getting keyword matching instead. No Telegram notification is sent on disable or re-enable. This is the most dangerous silent failure mode — it changes the bot's behavior with no indication.

**6. Process status requires SSH.**  
`sol_commands.py` and `monitor.py` both write `.pid` files. To check if they're actually alive requires `kill -0 <pid>`, `journalctl`, or `systemctl status` — none accessible from Telegram. Currently `sol_commands.service` is in a systemd restart loop (verified 2026-04-08), which is invisible without `journalctl -u sol-commands`.

---

## 2. VALUE PROPOSITION

**Time saved per publishing session:**  
Current standard flow: 4 Telegram messages + ~60-120s generation wait + manual format selection via slash command if needed = ~3-5 minutes of active attention per post.  
Dashboard flow: paste headline → pick format → click generate → edit if needed → click publish = under 60 seconds, no format hunting, no round trips.

**Errors eliminated:**
- Wrong platform publish (X when you meant Threads only): platform selector always visible
- Silent Threads media failure: dashboard shows platform-by-platform result
- Timeout false negative: dashboard polls actual subprocess exit code, not just 180s wall clock
- Brain circuit breaker surprise: health monitor shows `BRAIN: DISABLED` in amber

**Control gained (impossible from Telegram):**
- Edit pending tweet text before publishing (not just regenerate)
- View all pending state in one screen (pending tweet + combo + monitor alert + scheduled posts)
- Read log files without SSH
- Review and cancel individual scheduled posts
- See publish history (once `publish_log.json` is added to bot)

---

## 3. THREE IMPLEMENTATION TIERS

### TIER 1 — Operational MVP (1-2 days)

**Scope:** Read-only + basic control. Eliminates the SSH-for-status problem entirely.

**What's built:**
1. FastAPI app (`sol_dashboard_api.py`) on port 8502 with nginx proxy + HTTP Basic auth
2. **Health panel** — `sol_commands.pid` + `monitor.pid` liveness check via `os.kill(pid, 0)`; brain enabled/disabled status read from `brain_history.json` last entry; systemd service status via `subprocess.run(["systemctl", "is-active", ...])`
3. **Pending post viewer** — reads `pending_tweet.json`, `pending_combo.json`, `monitor_pending.json`, all `pending_sched_*.json`; displays tweet text + format + char count + age
4. **Publish buttons** — POST `/api/publish` invokes `publish_dual.py` via subprocess; returns per-platform result; no timeout false negative (waits for actual exit code)
5. **Live log stream** — SSE endpoint tailing `sol_commands.log`; last 8 lines in browser, auto-scroll, pause on hover
6. systemd unit for dashboard process

**What's NOT in Tier 1:** Generation (still done via Telegram), /mixed builder, analytics, tone validator.

**Deploy without breaking existing bot:** Dashboard is read-only for state files except POST /api/publish which replaces Telegram keyboard buttons. Bot continues running unchanged. Dashboard and Telegram control coexist.

**Benefit:** After Tier 1, you never need SSH just to check bot status again.

---

### TIER 2 — Full Dashboard (1 week)

**What it adds over Tier 1:**

1. **Sol chat interface** — System prompt preloaded from `generator.py` constants; textarea for headline input; format picker (WIRE/ANALISIS/DEBATE/CONEXION tabs); POST `/api/generate` calls `generate_tweet()` inline; char counter with color shift at 250/270+; "Generate + Preview" then separate "Publish" step
2. **/mixed builder** — Paste raw headlines; POST `/api/mixed` calls `generate_combinada_tweet()`; preview WIRE and ANALISIS sections separately before publishing
3. **Scheduler manager** — List all `pending_sched_*.json` with tweet preview + format + generated_at; individual cancel buttons (DELETE `/api/scheduler/{n}`); no edit (keep simple)
4. **Model routing override** — Per-generation model selector dropdown (auto / haiku / sonnet / opus); passed as `model_override` param to `generate_tweet()`
5. **`publish_log.json` addition to bot** (~30 LOC) — append to log on every successful X/Threads post with: `{published_at, platform, tweet_id, text_preview, tweet_type, model_used}`; Tier 2 dashboard reads this for a "Recent Posts" feed

**When to build Tier 2:** After Tier 1 has been running for a week without issues. The Sol chat and /mixed builder are the highest-ROI additions — they replace the most friction-heavy Telegram workflows.

---

### TIER 3 — Sol Command Center (2-3 weeks)

**What it adds over Tier 2:**

1. **Tone validator** — Pre-publish check: char count (trivial), AI-ism regex (medium: pattern list against known AI phrases), rhetorical move classifier (hard: Haiku call to detect Cold Fact Drop / Buried Lede / etc.); shown as warnings not blockers
2. **System prompt editor** — Requires refactoring persona constants from `generator.py` into `sol_persona.json`; editor with textarea + save + "Reload generator" button (sends SIGHUP or restarts subprocess); dangerous without tests
3. **Analytics panel** — Query `analytics.db` for engagement metrics; topic distribution chart; format performance (WIRE vs ANALISIS vs DEBATE by engagement); requires ~1 week of `publish_log.json` data first
4. **Brain history viewer** — Show last N brain turns with user message → detected action; highlight circuit breaker events
5. **Batch scheduler** — Generate multiple posts from a pasted list of headlines; preview all before publishing; replaces scheduler.py cron for manual batches
6. **Alert configuration** — Silence/filter specific monitor channels from dashboard without SSH

**Honest assessment: when does Tier 3 pay off?**  
Tier 3 makes sense if: (a) posting volume increases to 5+ posts/day, (b) a second operator needs access, or (c) the persona is actively being iterated. For a solo operator posting 2-3 times/day with a stable persona, Tier 2 covers 90% of the value. The tone validator and system prompt editor are the only Tier 3 items with near-term ROI.

**Overkill if:** The bot is running stably, the persona isn't changing, and the main friction is already eliminated by Tier 2.

---

## 4. RECOMMENDED STACK

**FastAPI + htmx, deployed as a systemd service behind nginx.**

FastAPI provides proper HTTP endpoints for bot control actions (publish, generate, reset) — things that Streamlit's reactive model handles poorly. htmx delivers interactive UI updates without a JavaScript build pipeline: a `POST` button submits a form, FastAPI returns an HTML fragment, htmx swaps the target element. The live log stream uses FastAPI's native SSE support (`EventSourceResponse`). Total frontend JS: under 50 lines. No `node_modules`. No build step. Deploy is `git pull && systemctl restart sol-dashboard-api`.

The existing Streamlit dashboard (`sol-dashboard.service`, port 8501) stays running during the transition. After Tier 1 ships, redirect nginx to port 8502 and disable Streamlit. Net memory reclaimed: ~58 MB.

---

## 5. ASCII WIREFRAME

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│  STATUS BAR (full width, 48px)                                                   │
│  ● LIVE   sol_commands [●] monitor [●]   BRAIN: ENABLED   Last pub: 14m · ANALISIS  Posts today: 7  │
└──────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────┬─────────────────────────┬────────────────────────┐
│  SOL CHAT (35%)         │  POST MANAGER (35%)     │  /MIXED BUILDER (30%) │
│                         │                         │                        │
│  SOL // geopolitical    │  ─ PENDING POST ──────  │  MIXED POST BUILDER   │
│  analyst                │                         │                        │
│  ─────────────────────  │  [tweet text here]      │  ┌────────────────┐   │
│                         │  char: 241/280 ████░    │  │ paste raw      │   │
│  [Sol response text]    │                         │  │ headlines...   │   │
│  [Sol response text]    │  [X] [THREADS]          │  └────────────────┘   │
│  [Your message]         │                         │                        │
│                         │  [PUBLISH BOTH]         │  [GENERATE MIXED]     │
│  ─────────────────────  │  [X ONLY] [THRD ONLY]   │                        │
│  WIRE·ANALISIS·DEBATE   │  [DISCARD]              │  ─ PREVIEW ─────────  │
│  CONEXION               │                         │                        │
│                         │  ─ RECENT POSTS ──────  │  [generated text]     │
│  ┌────────────────────┐ │                         │                        │
│  │ Enter headline...  │ │  09:14 · X+T · WIRE     │  [PUBLISH]            │
│  └────────────────────┘ │  08:51 · X   · ANALISIS │  (disabled until gen) │
│  [GENERATE] [GEN+PUB]   │  08:22 · T   · DEBATE   │                        │
│                         │  07:44 · X+T · CONEXION │                        │
│  ⚠ 1 post pending ●     │  07:01 · X+T · WIRE     │                        │
└─────────────────────────┴─────────────────────────┴────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────────┐
│  SYSTEM LOG · LIVE  [▼ COLLAPSE]                                                 │
│  09:21:44 INFO [memory] Saved tweet [ANALISIS/politica]                          │
│  09:21:39 INFO Publishing to X... (subprocess)                                   │
│  09:21:31 INFO [brain] classify → publish (0.94)                                 │
│  09:20:58 INFO [generator] ANALISIS/sonnet → 241 chars                           │
│  09:20:55 INFO [brain] classify → generate_sol (0.97)                            │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. BUILD ORDER

**1. `publish_log.json` patch to bot** (~30 LOC, 30 min)  
Add append calls in `_publish_x()` and `_publish_threads()` in `sol_commands.py`. This must come first — every later feature depends on having a publish history. Do before writing any dashboard code.

**2. FastAPI scaffold + health monitor** (2-3 hours)  
`sol_dashboard_api.py`: app skeleton, `/` route returns Jinja2 template, `/api/status` reads PIDs + brain state. systemd unit. nginx config. This is the foundation everything else mounts on. Validates the deployment pipeline before any complex features.

**3. Pending post viewer + publish buttons** (2-3 hours)  
`/api/pending` reads all state files. POST `/api/publish` invokes subprocess. Char counter in template JS (30 lines). This is the highest-ROI control feature — replaces 2 Telegram round trips.

**4. Live log stream** (1 hour)  
SSE endpoint + htmx `hx-sse` attribute on log panel. Needs `sse-starlette` package. Smallest feature with highest daily utility.

**5. Scheduler view** (1 hour)  
Glob + JSON read. Delete button per entry. Eliminates SSH for the "what's scheduled?" question.

**6. Sol chat interface** (3-4 hours)  
Format picker tabs. POST `/api/generate` calls `generate_tweet()` inline (import, don't subprocess). Char counter. This is the most involved Tier 1→2 addition because it requires importing `generator.py` into the dashboard context cleanly.

**7. /mixed builder** (2 hours)  
Similar to chat but calls `generate_combinada_tweet()`. Separate preview for WIRE and ANALISIS sections. Publish button that posts combo.

**8. Tone validator** (3-4 hours, optional Tier 3)  
Char count display (already done). AI-ism regex list (manually curated). Rhetorical move detection via Haiku — only add if there's evidence of persona drift in published posts.
