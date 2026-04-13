# Sol Bot — Friction Audit

> Generated: 2026-04-08  
> Source: Full codebase audit of `/root/x-bot/sol-bot/`

---

## 1. COMMAND MAP

### 1.1 Slash Commands

| Command | Handler | JSON Read | JSON Write | Notes |
|---------|---------|-----------|-----------|-------|
| `/status` | `cmd_status()` L304 | `pending_tweet.json` | — | Shows pending tweet + timestamp |
| `/noticia <text>` | `cmd_generate()` L707 | — | `pending_news_text.txt` | Saves news, sends generation keyboard |
| `/publica` | `cmd_publish("")` L1122 | `pending_tweet.json`, `pending_combo.json` | — | Publishes X + Threads |
| `/publica x` | `cmd_publish("x")` L1122 | `pending_tweet.json` | — | X only |
| `/publica threads` | `cmd_publish("threads")` L1122 | `pending_tweet.json` | — | Threads only |
| `/publica <N>` | `cmd_publish_from_sched()` L796 | `pending_sched_N.json` | `pending_tweet.json` | Load scheduler tweet, publish both |
| `/wire`, `/urgente`, `/breaking` | `cmd_regen("WIRE")` L1166 | `pending_tweet.json` | `pending_tweet.json` | Regen as breaking news |
| `/analisis`, `/análisis` | `cmd_regen("ANALISIS")` L1166 | `pending_tweet.json` | `pending_tweet.json` | Regen as deep analysis |
| `/debate` | `cmd_regen("DEBATE")` L1166 | `pending_tweet.json` | `pending_tweet.json` | Regen as debate/opinion |
| `/conexion`, `/conexión` | `cmd_regen("CONEXION")` L1166 | `pending_tweet.json` | `pending_tweet.json` | Regen as macro angle |
| `/regenera`, `/regenerar` | `cmd_regen("RANDOM")` L1166 | `pending_tweet.json` | `pending_tweet.json` | Random format regen |
| `/mixed [x\|threads]` | `cmd_mixed()` L1152 | multiple | `pending_combo.json` | Generates WIRE + ANALISIS combo |
| `/original`, `/reenviar`, `/asis` | `cmd_publish_original()` L1140 | `monitor_pending.json` | — | Publishes monitor headline as-is |
| `/original x`, `/xo` | `cmd_publish_original(target="x")` L1143 | `monitor_pending.json` | — | Monitor original, X only |
| `/original threads`, `/to` | `cmd_publish_original(target="threads")` L1146 | `monitor_pending.json` | — | Monitor original, Threads only |
| `/traduce`, `/translate` | `cmd_publish_translated()` L1149 | `monitor_pending.json` | — | Translate to Spanish + publish both |
| `/reset`, `/limpiar`, `/clear` | `cmd_reset()` L1137 | all pending files | deletes all | Clears all pending state |
| `/ayuda`, `/help`, `/commands` | `cmd_ayuda()` L1135 | — | — | Shows help text |

### 1.2 Inline Keyboard Buttons

**Generation Keyboard** — shown after user sends news headline

| Button | Callback | Action | State |
|--------|----------|--------|-------|
| 🧩 Mixed | `gen_mixed` | `cmd_mixed(news_text)` | Writes `pending_combo.json` |
| 📰 Original | `gen_original` | `cmd_publish_original()` | Direct publish (no preview) |
| ⚡ Generate | `gen_sol` | `_do_generate(news_text)` | Writes `pending_tweet.json` |

**Publish Keyboard** — shown after generation completes

| Button | Callback | Action | State |
|--------|----------|--------|-------|
| ✅ Publicar ambos | `pub_both` | `cmd_publish("")` | Clears `pending_tweet.json` |
| 𝕏 Solo X | `pub_x` | `cmd_publish("x")` | Clears `pending_tweet.json` |
| 🧵 Solo Threads | `pub_threads` | `cmd_publish("threads")` | Clears `pending_tweet.json` |
| 🔄 Regenerar | `btn_regen` | `cmd_regen("RANDOM")` | Updates `pending_tweet.json` |
| ❌ Cancelar | `btn_cancel` | `cmd_reset()` | Deletes all pending files |

**Monitor Keyboard** — shown when monitor.py detects new headline

| Button | Callback | Action | State |
|--------|----------|--------|-------|
| ⚡ Generate | `mon_generate` | `cmd_generate_from_monitor()` | Writes `pending_tweet.json`, deletes `monitor_pending.json` |
| 🧩 Mixed | `mon_mixed` | `cmd_mixed(title)` | Writes `pending_combo.json`, deletes `monitor_pending.json` |
| 📰 Original | `mon_original` | `cmd_publish_original()` | Direct publish, deletes `monitor_pending.json` |
| 🚫 Ignorar | `mon_ignore` | deletes `monitor_pending.json` | Silent drop |

### 1.3 Brain Intents (Free-text Classification via `brain.py`)

| User Input Pattern | Brain Action | Handler Path |
|-------------------|-------------|-------------|
| News headline (title, data, event) | `generate_sol` | `cmd_generate()` |
| "publícalo", "dale", "va", "súbelo" | `publish` | `cmd_publish("")` |
| "solo en X", "only X" | `publish_x_only` | `cmd_publish("x")` |
| "solo en threads" | `publish_threads_only` | `cmd_publish("threads")` |
| "de nuevo", "otra vez", "regenera" | `regenerate` | `cmd_regen("RANDOM")` |
| "de nuevo pero [condition]" | `regenerate_with_instruction` | `cmd_regen(..., instruction=...)` |
| "cancela", "olvídalo" | `cancel` | `cmd_reset()` |
| "genera el mixed", "combinada" | `generate_mixed` | `cmd_mixed()` |
| "wire en inglés", "solo el wire" | `generate_original` | `cmd_publish_original()` |
| Anything else (circuit breaker fires) | `unknown` | `keyword_fallback()` |

**Brain model:** `claude-haiku-4-5-20251001` via Anthropic direct (or OpenRouter)  
**Timeout:** 3 seconds  
**Circuit breaker:** disables after 3 consecutive failures → silent keyword fallback  
**History:** last 10 turns in `brain_history.json`

---

## 2. DATA INVENTORY

### 2.1 Active State Files

| File | Schema | Written By | Read By | Persistence |
|------|--------|-----------|---------|-------------|
| `pending_tweet.json` | `{tweet, headline, generated_at, tweet_type, media_path, media_paths}` | `_do_generate()`, `cmd_regen()`, `cmd_publish_from_sched()` | `cmd_publish()`, `cmd_status()`, `cmd_regen()` | Until publish or reset |
| `pending_combo.json` | same as above | `cmd_mixed()` | `_publish_combo()`, `cmd_publish()` | Until publish or reset |
| `monitor_pending.json` | `{headline: {title, summary, source, url}, received_at, media_paths, media_path, media_type}` | `monitor.py` | `cmd_generate_from_monitor()`, `cmd_mixed()`, `cmd_publish_original()` | Until action taken |
| `pending_media.json` | `{media_path, media_type, tg_media_url}` | `handle_media_message()` | `cmd_publish()`, `_do_generate()` | Until publish or reset |
| `pending_news_text.txt` | raw headline string | `cmd_generate()` | generation keyboard handlers | Until keyboard button pressed |
| `pending_sched_N.json` | `{tweet, headline, generated_at, tweet_type, media_path, media_paths, media_type}` | `scheduler.py` (cron) | `cmd_publish_from_sched()` | Persistent until `/publica N` |
| `brain_history.json` | `[{role, content}]` last 10 turns | `call_brain()` | `call_brain()` | Rolling (10 turn max) |
| `context.json` | `[{timestamp, topic_tag, tweet_text, tweet_type, platform}]` last 15 | `memory.add_tweet()` | generator continuity prompt | Rolling (15 entry max) |

### 2.2 Log Files

| File | Location | Content | Size |
|------|----------|---------|------|
| `sol_commands.log` | `/root/x-bot/logs/` | Telegram bot interactions, generation/publish flow | 285 KB |
| `scheduler.log` | `/root/x-bot/logs/` | Cron runs, headline fetch, generation decisions | 14 KB |
| `analytics.log` | `/root/x-bot/logs/` | X API v1.1 and GraphQL calls | 17 KB |
| `analytics_insights.log` | `/root/x-bot/logs/` | SQLite `analytics.db` operations | 66 KB |
| `threads.log` | `/root/x-bot/logs/` | Threads API container creation, publishing | 216 B |
| `monitor.log` | `/root/x-bot/logs/` | Telegram monitor event handler | — |
| `trending.log` | `/root/x-bot/logs/` | Trending topic scanner | 16 KB |
| `nohup.out` | `/root/x-bot/sol-bot/` | stdout from both processes (mixed) | 461 KB (6279 lines) |

**Log line format (sol_commands.log):**
```
2026-04-08 06:32:43,598 INFO [memory] Saved tweet [ANALISIS/politica]
2026-04-08 07:01:19,821 WARNING answerCallbackQuery error: HTTP Error 400: Bad Request
2026-04-08 07:25:41,410 WARNING [MONITOR_PENDING_FILE] Deleting in cmd_generate_from_monitor()
```

**nohup.out mixed format (print statements from monitor.py):**
```
Photo saved: /root/x-bot/sol-bot/media/monitor_1712581277_0.jpg
[FILTRADO] -1002006131201: 'US President Trump...'
Enviada: Bitcoin sube 3% mientras el mercado...
```

### 2.3 Database

- `analytics.db` (SQLite) — tweet performance data, topic categorization, engagement metrics
- No query interface exposed; only accessible via SQL or `analytics_insights.py`

### 2.4 What Is NOT Currently Logged (Easy Wins)

| Missing Metric | Impact | Implementation Effort |
|---------------|--------|----------------------|
| **Publish log** — tweet ID, platform, timestamp, success/failure per publish | Critical — can't show publish history | Append to `publish_log.json` in `_publish_x()` / `_publish_threads()` |
| **Model routing decisions** — which model was selected, manual vs auto, why | High — can't audit model usage patterns | Log in `get_model()` → `model_log.json` |
| **Error categorization** — API failures by type, component, resolution | High — current logs are free text | Structured `error_log.json` |
| **Regeneration reasons** — which format user chose, how many regens before publish | Medium — helps understand persona drift | Add `regen_count` field to `pending_tweet.json` |
| **Brain circuit breaker events** — when disabled, when re-enabled, failure reasons | Medium — critical for diagnosing brain outages | Log state changes in `brain_history.json` |
| **Media processing** — source (Telegram CDN / catbox / local), size, upload time | Medium — helps diagnose media failures | Append to `media_log.json` in publishers |
| **Scheduler decisions** — silent day activated, sensitive headlines filtered count | Medium — explains why no posts some days | Already logged but not persisted to JSON |
| **Topic distribution over time** — rolling coverage by topic and hour | Low — nice-to-have analytics | Compute from `context.json` hourly rollup |

---

## 3. WORKFLOW SEQUENCES

### 3.1 Standard Generate → Publish (3 Telegram round trips)

```
MSG 1 (owner → bot): "Venezuela retira embajador de Washington"
  ↓ brain: generate_sol
  ↓ cmd_generate() → saves pending_news_text.txt → sends generation keyboard

MSG 2 (owner → bot): clicks ⚡ Generate
  ↓ _do_generate() → calls generator → saves pending_tweet.json → sends publish keyboard

MSG 3 (bot → owner): "Tweet listo: Venezuela cierra su embajada..."
  [✅ Publicar ambos | 𝕏 Solo X | 🧵 Solo Threads | 🔄 Regenerar | ❌ Cancelar]

MSG 4 (owner → bot): clicks ✅ Publicar ambos
  ↓ cmd_publish("") → subprocess x_publisher.py (180s timeout) + threads_publisher.py (120s)
  ↓ sends "Publicacion dual:\n- X: Publicado\n- Threads: Publicado"
```

**Total:** 4 Telegram messages, ~30-120 seconds elapsed

### 3.2 Monitor → Generate → Publish (4 Telegram round trips)

```
(automatic) monitor.py detects headline → saves monitor_pending.json

MSG 1 (bot → owner): "📡 @BRICSNews: [headline text]"
  [⚡ Generate | 🧩 Mixed | 📰 Original | 🚫 Ignorar]

MSG 2 (owner → bot): clicks ⚡ Generate
  ↓ cmd_generate_from_monitor() → generates tweet → saves pending_tweet.json → sends publish keyboard

MSG 3 (bot → owner): "Tweet listo: [generated tweet]"
  [✅ Publicar ambos | 𝕏 Solo X | 🧵 Solo Threads | 🔄 Regenerar | ❌ Cancelar]

MSG 4 (owner → bot): clicks ✅ Publicar ambos
  ↓ cmd_publish("") → subprocess calls → sends publish confirmation
```

**Total:** 4 Telegram messages (2 user actions)

### 3.3 Scheduler → Publish (2 Telegram round trips)

```
(automatic, cron 7:30/11:00/17:00 CST + 5-45min jitter) scheduler.py runs
  → fetches headlines → generates tweets → saves pending_sched_1.json, pending_sched_2.json
  → sends Telegram preview of scheduled tweets

MSG 1 (bot → owner): "Scheduled tweets ready:\n1. [tweet preview]\n2. [tweet preview]"

MSG 2 (owner → bot): "/publica 1"
  ↓ cmd_publish_from_sched() → loads pending_sched_1.json → publishes → deletes file
```

**Total:** 2 Telegram messages (no preview/edit step for scheduler tweets)

### 3.4 Regenerate → Publish (adds 1 round trip per regen)

```
After publish keyboard shown, user clicks 🔄 Regenerar or sends /wire
  ↓ cmd_regen("RANDOM") → random format → updates pending_tweet.json → resends publish keyboard

Each regen = 1 additional round trip before publishing
No format selector on keyboard — must use slash command (/wire, /debate, etc.) to pick format
```

---

## 4. FRICTION MATRIX

### 4.1 Requires SSH Access

| Task | Why SSH Required | Frequency |
|------|-----------------|-----------|
| View recent publish history | No persistent publish log; context.json readable only via file | Daily |
| Check if process is running | journalctl / systemctl status not accessible from Telegram | Multiple times/day |
| Inspect orphaned state files | Stale `pending_sched_N.json` accumulate; no cleanup command | Weekly |
| Clear stale PID files | When process crashes, `.pid` file remains; next start warns | Rare but blocking |
| Read error stack traces | Log files not accessible from Telegram | On failures |
| Manually edit pending tweet | No text edit capability from Telegram keyboard | Occasionally |
| View analytics.db data | No query interface exposed | Rarely |
| Change system prompt / persona | `generator.py` constants not hot-reloadable | Rarely but high-friction |

### 4.2 No Feedback / Silent Failures

| Event | Location | Missing Feedback |
|-------|----------|-----------------|
| Brain circuit breaker disables | `brain.py` L169-180 | Keyword fallback activates silently; user doesn't know |
| Video too long (>60s) filtered | `monitor.py` | Printed to stdout only; no Telegram notification |
| Short message (<5 chars) filtered | `monitor.py` | Printed to stdout: `[FILTRADO]`; no Telegram notification |
| Silent day activated by scheduler | `scheduler.py` (3.3% chance) | Logged only; no Telegram notification |
| All headlines filtered as sensitive | `scheduler.py` | Logged only; no Telegram notification |
| Threads media upload fails → text-only fallback | `threads_publisher.py` | Bot reports "Publicado en Threads" regardless |
| X subprocess succeeds AFTER 180s timeout | `cmd_publish()` L911 | Bot reports timeout; post actually published; no reconciliation |
| Generator error on specific headline | `scheduler.py` | Logged only; `pending_sched_N.json` not created for that N |
| Media auto-recovered from monitor source | `_do_generate()` L750-762 | No notification that media came from monitor (not owner) |
| `answerCallbackQuery` fails | `sol_commands.py` | User sees spinner; bot logs warning; no visible error |

### 4.3 Multiple Commands for One Goal

| Goal | Telegram Steps | Friction |
|------|---------------|---------|
| Generate + publish | 3-4 messages + 2 button clicks | ~2 min elapsed; no draft edit between steps |
| Regenerate as specific format | 1. Click 🔄 (random) or 2. Type `/wire` then click ✅ | Random regen has no format selector on keyboard |
| Check current state | `/status` → shows one pending file; others not visible | No unified "what's pending?" view |
| Publish scheduler tweet with preview | See preview in auto-message → wait → `/publica N` | No edit/regenerate option for scheduler tweets |
| Recover after X-fails-Threads-succeeds | Manual: regenerate + publish X only | `PENDING_FILE` already deleted; must regenerate |

### 4.4 No Visibility (Fire-and-Forget)

| Operation | Location | Problem |
|-----------|----------|---------|
| Dual publish subprocess calls | `_publish_both()` L973 | Sequential subprocesses; if X succeeds and Threads fails, pending file deleted |
| `mon_ignore` button | L1265 | Message: "Noticia ignorada 🚫"; no archive, no reason logged |
| `/reset` command | `cmd_reset()` L487 | Deletes ALL pending files immediately; no undo |
| Media cleanup post-publish | `cmd_publish()` L879-896 | Deletes `media/owner_*` files silently |
| Brain history pruning | `save_history()` L74 | Truncates to 10 turns; older context discarded |
| Scheduler orphaned files | `pending_sched_N.json` | Old files remain on disk indefinitely if not published |

---

## 5. API SURFACE (Trivially Exposable Endpoints)

The following would require ~200 LOC wrapper to expose as HTTP endpoints, touching no existing logic:

```
GET  /api/status
     Returns: process PIDs alive (monitor, sol_commands), pending file states,
              last tweet from context.json, brain enabled/disabled

GET  /api/pending
     Returns: pending_tweet.json + pending_combo.json + monitor_pending.json + 
              list of pending_sched_*.json files

GET  /api/tweets/recent?limit=15
     Returns: context.json entries (timestamp, topic, tweet_text, tweet_type, platform)

GET  /api/logs/tail?file=sol_commands&lines=50
     Returns: last N lines from /root/x-bot/logs/{file}.log

GET  /api/logs/stream
     SSE stream of new log lines from sol_commands.log

POST /api/generate
     Payload: {headline, tweet_type?, manual?}
     Effect: calls generate_tweet() → saves pending_tweet.json
     Returns: {tweet, tweet_type, model_used, char_count}

POST /api/publish
     Payload: {platform: "x"|"threads"|"both", source: "pending"|"combo"}
     Effect: calls _publish_x() / _publish_threads() / _publish_both()
     Returns: {x_success, threads_success, x_tweet_id, threads_post_id}

POST /api/mixed
     Payload: {headline}
     Effect: calls generate_combinada_tweet() → saves pending_combo.json
     Returns: {tweet, char_count}

POST /api/reset
     Effect: calls cmd_reset() → deletes all pending files
     Returns: {cleared: [list of files deleted]}

GET  /api/scheduler/list
     Returns: list of pending_sched_*.json files with previews

DELETE /api/scheduler/{n}
     Effect: deletes pending_sched_N.json
     Returns: {deleted: true}
```

**What would require more work (not trivial):**
- Live X/Threads post performance data (requires X API v2 / Threads Insights API, separate OAuth)
- Real-time process restart control (requires sudo/systemd socket or wrapper script)
- System prompt hot-reload (requires file watch + signal to running process)
