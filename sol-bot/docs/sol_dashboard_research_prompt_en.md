# RESEARCH MISSION: Sol Bot — Dashboard & UI Integration Proposal

## System Context

Sol bot is a production automated news publishing system for X (@inequaliti) and Threads.
Single operator, controlled entirely via Telegram. Running on Hetzner VPS Ubuntu 22.04.

**Location:** `/root/x-bot/sol-bot/`
**Processes:** `monitor.py` and `sol_commands.py` as separate `nohup` processes with PID locks

### Current file map

| File | Purpose |
|------|---------|
| `generator.py` | Core generation engine — 4 formats: WIRE, ANALISIS, DEBATE, CONEXION |
| `sol_commands.py` | Telegram polling loop (~803 lines) — main control interface |
| `brain.py` | Intent classifier (Haiku via OpenRouter) — routes natural language to actions |
| `x_publisher.py` | Tweepy v2 — single tweets, threads, images, video |
| `threads_publisher.py` | Meta Threads API official |
| `publish_dual.py` | Orchestrates both publishers |
| `monitor.py` | Telethon — monitors BRICSNews, WatcherGuru Telegram channels |
| `memory.py` | Character/persona continuity |
| `fetcher.py` | RSS/API scraping |
| `filter.py` | Headline sensitivity filter |
| `trending_scanner.py` | Trending topic scanner |

### State persistence (JSON files)
- `pending_tweet.json` — post awaiting approval
- `monitor_pending.json` — alert from monitor awaiting action
- `pending_sched_N.json` — scheduled posts
- `brain_history.json` — last 5 conversation turns for brain context

### Model routing (via OpenRouter, fallback to Anthropic direct)
- WIRE format → Gemini Flash Lite
- DEBATE format → claude-haiku-4-5
- ANALISIS / CONEXION formats → claude-sonnet-4-6
- Manual override → Sonnet or Opus

### Current control interface (Telegram)
- **brain.py** intercepts all free-text messages, classifies intent into:
  `generate_sol`, `generate_mixed`, `generate_original`, `publish`, `publish_x_only`,
  `publish_threads_only`, `regenerate`, `regenerate_with_instruction`, `cancel`, `unknown`
- **Inline keyboard buttons:** 5-button publish selector, 3-button generation type, 4-button monitor alert
- **`/mixed` command:** combines raw headlines + Sol analysis in one post
- **Media support:** photos and video on both X and Threads (catbox.moe as Threads media host)
- **Circuit breaker:** keyword fallback when brain fails

### Sol's persona constraints
- Named rhetorical moves: Cold Fact Drop, Buried Lede, Nobody Noticed, History Rhyme, Math Check
- Format: line 1 = raw headline · blank line · 2-3 lines of analysis
- Tone: dry, contrarian, no moralizing, no AI-isms, max 280 chars
- Previous X account suspended for Puppeteer automation — now on official API only

---

## MISSION BRIEF

Design a **dashboard/UI proposal** for Sol bot that is:
1. **Realistic** — runs on current VPS stack, no new cloud dependencies
2. **Interactive** — real bot control, not just monitoring
3. **Productive** — eliminates actual friction from the current Telegram-only workflow

---

## EXECUTION INSTRUCTIONS FOR CLAUDE CODE

Run the following phases in sequence using the appropriate agents and skills.

---

### PHASE 1 — System Audit

**Agent: `engineering-skills` (code audit)**

```
Read all files in /root/x-bot/sol-bot/ and produce:

1. COMMAND MAP — every Telegram command and button action available, what it does,
   and whether it could be replicated or enhanced in a web UI

2. DATA INVENTORY — every piece of data the bot already generates, logs, or persists:
   - JSON state files and their schema
   - Log output format and location
   - Metrics available (post count, publish timestamps, model used, errors)
   - What is NOT currently logged but would be easy to add

3. FRICTION AUDIT — specific moments in the current workflow that require:
   - SSH access (things you can't do from Telegram)
   - Multiple Telegram commands to accomplish one goal
   - Manual state inspection (reading JSON files)
   - No visibility (fire-and-forget with no confirmation)

4. API SURFACE — what endpoints exist or could be trivially added to expose
   bot state and control to a web frontend

Expected output: friction_audit.md with structured findings
```

---

### PHASE 2 — Options Research

**Agent: `engineering-advanced-skills` (architecture research)**

```
Research and score dashboard framework options for a Python bot on Ubuntu VPS,
single technical operator. Evaluate each option across: setup complexity (1-5),
real-time capability (1-5), control surface (1-5), maintenance burden (1-5).

FRAMEWORKS TO EVALUATE:

A) Streamlit
   - Real-time bot control suitability (not just data viz)
   - WebSocket / auto-refresh support
   - Auth options for single-user personal dashboard
   - Can it call subprocess / send Telegram messages programmatically?

B) FastAPI + htmx
   - Minimal JS, server-side rendering
   - SSE (Server-Sent Events) for live log streaming
   - How much boilerplate for a functional dashboard?

C) FastAPI + React SPA
   - Clean separation, most flexible
   - Deployment complexity vs. benefit for single user
   - Worth it over htmx for this use case?

D) Gradio
   - Beyond ML demos — viable for bot control panels?
   - Auth, customization limits

E) Panel / Dash (Plotly)
   - Overkill or right fit for analytics + control hybrid?

INTEGRATIONS TO SCORE (impact vs complexity, 1-5 each):

1. Sol chat interface — system prompt preloaded, test posts before publishing,
   preview character count and format validation
2. Post feed — chronological list of published posts with timestamp, platform,
   format used, first 100 chars
3. Pending post manager — view/edit pending_tweet.json before approving,
   inline character counter, publish/discard buttons
4. /mixed builder — paste raw headlines, trigger generation, preview result,
   one-click publish
5. Live log stream — tail -f equivalent in browser (SSE or WebSocket)
6. Health monitor — process status (monitor.py / sol_commands.py alive?),
   last post timestamp, error count last 24h
7. Tone validator — pre-publish check: does this post comply with Sol's
   constraints? (char count, no AI-isms, rhetorical move detected?)
8. System prompt editor — edit Sol's persona/character sheet without SSH,
   hot-reload without restarting process
9. Scheduler view — timeline of pending_sched_N.json entries,
   cancel or reschedule individual posts
10. Model routing override — per-post model selection from UI instead of
    format-based auto-routing

DEPLOYMENT REQUIREMENTS:
- Auth: minimal viable for personal VPS (HTTP basic auth via nginx, or token)
- HTTPS: Caddy vs nginx reverse proxy recommendation
- Process: systemd unit for dashboard vs nohup
- Port recommendation

Expected output: options_scored.md with framework recommendation + top 5 integrations ranked by ROI
```

---

### PHASE 3 — Executive Proposal

**Agent: `c-level-skills` (product strategy)**

```
Using Phase 1 and Phase 2 outputs, write an executive proposal for Sol bot's dashboard.

Structure:

## 1. DIAGNOSIS
Current workflow friction points (from Phase 1 audit). Be specific —
name the actual files, commands, and moments where the workflow breaks down.

## 2. VALUE PROPOSITION
What concretely changes with a dashboard. Frame in terms of:
- Time saved per publishing session
- Errors eliminated (wrong model, forgot to check char count, etc.)
- Control gained (what you can now do that required SSH before)

## 3. THREE IMPLEMENTATION TIERS

### TIER 1 — Operational MVP (1-2 days)
Exact scope, exact stack, immediate benefit.
This tier must be deployable in a weekend without breaking existing bot.

### TIER 2 — Full Dashboard (1 week)
What it adds over MVP. When does it make sense to build this?

### TIER 3 — Sol Command Center (2-3 weeks)
Complete vision. Advanced integrations. Honest assessment: when is this
overkill vs. when does it pay off?

## 4. RECOMMENDED STACK
One clear recommendation with brief justification. No hedging.

## 5. ASCII WIREFRAME
Text layout of the recommended dashboard — panels, sections, data shown.
Be specific enough that a developer could start building from this alone.

## 6. BUILD ORDER
Ordered list of what to build first, second, third.
Each item: what it is, why this order, estimated time.

Expected output: sol_dashboard_proposal.md — complete, actionable, no filler
```

---

### PHASE 4 — Visual Mockup

**Skill: `frontend-design`**

```
Build a high-fidelity HTML mockup of the Sol bot dashboard.

AESTHETIC DIRECTION:
Sol is a dry, contrarian geopolitical analyst. The dashboard should feel like
a war room crossed with a Bloomberg terminal — dense, intentional, zero decoration
for decoration's sake. NOT a SaaS product dashboard. NOT generic dark mode.

Think: signals intelligence center. Every pixel earns its place.

COLOR SYSTEM:
- Background: #080808 (near black, not pure black)
- Primary surface: #111111
- Secondary surface: #1a1a1a
- Accent: #f59e0b (amber — used sparingly, only for live/active states)
- Cold accent: #22d3ee (cyan — for data, timestamps, model indicators)
- Text primary: #e5e5e5
- Text muted: #6b7280
- Danger: #ef4444
- Success: #22c55e (only for published confirmation)

TYPOGRAPHY:
- Data / timestamps / post text: monospace (IBM Plex Mono or similar)
- UI labels: tight, condensed sans (not Inter — try Barlow Condensed, Oswald, or similar)
- NO decorative fonts, NO rounded typefaces

LAYOUT — Five panels (desktop-first, compact):

1. STATUS BAR (top, full width, ~48px height)
   - Bot status: [● LIVE] or [✕ DOWN] with amber pulse animation if live
   - Last published: "14m ago · X + Threads · ANALISIS"
   - Posts today: "7 published"
   - Model load: "haiku · sonnet · flash" with last-used highlighted
   - Process health: sol_commands [●] monitor [●]

2. SOL CHAT (left column, ~35% width)
   - Sol's character header: "SOL // geopolitical analyst"
   - Message thread: user input + Sol responses, monospace, dense
   - Input: textarea + [GENERATE] [GENERATE + PUBLISH] buttons
   - Format selector: WIRE · ANALISIS · DEBATE · CONEXION (tab style, not dropdown)
   - Pending indicator: "1 post pending approval" with amber dot

3. POST MANAGER (center column, ~35% width)
   - Top section: PENDING POST
     - Full text of pending_tweet.json
     - Character counter: "241/280" with color shift near limit
     - Platform badges: [X] [THREADS]
     - Actions: [PUBLISH BOTH] [X ONLY] [THREADS ONLY] [DISCARD]
   - Bottom section: RECENT POSTS (last 5)
     - Each row: timestamp · platform icons · format · first 80 chars
     - Monospace, tight line height

4. /MIXED BUILDER (right column, ~30% width)
   - Label: "MIXED POST BUILDER"
   - Textarea: "paste raw headlines..."
   - [GENERATE MIXED] button
   - Preview output area
   - [PUBLISH] button (disabled until generated)

5. LIVE FEED (bottom strip, collapsible, ~120px)
   - Log stream: last 8 lines of bot output
   - Monospace, smaller font, muted color
   - Auto-scroll with pause on hover
   - Label: "SYSTEM LOG · LIVE"

INTERACTIONS (simulate with JS):
- Status bar amber pulse animation on LIVE state
- Character counter color: gray → yellow at 250 → red at 270+
- Pending post section has subtle amber left border
- Hover states on post rows (slight background lift)
- Button press states (brief press animation, not bouncy)
- Log lines fade in from bottom

FAKE DATA (use realistic Sol-style content):
- Pending post: something about BRICS or Fed that sounds like Sol wrote it
- Recent posts: 5 entries with varying formats and timestamps
- Log lines: realistic bot output (publishing confirmations, model calls, etc.)

OUTPUT: Single self-contained HTML file. No external dependencies except
Google Fonts (for monospace). Production-quality. Captures Sol's intelligence
without looking like a generic dark dashboard.
```

---

## EXPECTED OUTPUTS

| File | Phase | Content |
|------|-------|---------|
| `friction_audit.md` | 1 | System audit — commands, data, friction points |
| `options_scored.md` | 2 | Framework comparison + integration scoring |
| `sol_dashboard_proposal.md` | 3 | Executive proposal with 3 tiers + wireframe |
| `sol_dashboard_mockup.html` | 4 | High-fidelity visual mockup |

---

## EXECUTION NOTES

- VPS: `89.167.109.62`, SSH port 443
- For Phase 1 and 2: connect via bash and read files directly from `/root/x-bot/sol-bot/`
- For Phase 4: no VPS connection needed — use simulated data faithful to Sol's tone
- If any integration is technically infeasible with current stack, say so explicitly with why
- Priority: actionable > comprehensive. Cut anything theoretical.
- Do not restart or modify any running process during the audit
