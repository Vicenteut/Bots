# Sol Bot — Folder Structure Audit
_Generated: 2026-04-09 | Auditor: engineering-advanced-skills_

---

## Current Structure (Flat — Everything at Root)

```
sol-bot/                        (56 items at root level)
├── analytics_insights.py       36KB  — analytics queries, X API, insights
├── analytics_tracker.py         9KB  — tweet performance tracker
├── backup_bot.py                7KB  — backup utility
├── brain.py                     8KB  — intent classifier (LLM router)
├── brain_history.json                — runtime state (conversation history)
├── config.py                    2KB  — legacy config loader
├── content_calendar.py          9KB  — content scheduling helpers
├── content_utils.py             1KB  — text formatting utilities
├── context.json              → symlink to /root/x-bot/context.json
├── controls.py                  6KB  — audit logging, kill switches
├── cookie_monitor.py            2KB  — cookie health checker
├── dashboard.py                22KB  — DEAD CODE (old Streamlit dashboard)
├── data_providers.py            8KB  — yfinance, GDELT, Polymarket fetchers
├── .env                      → symlink to /root/x-bot/.env
├── .env.example                 1KB  — env template
├── fetcher.py                   1KB  — RSS/news fetcher
├── filter.py                    2KB  — content filter/dedup
├── friction_audit.md                 — design document (not code)
├── generator.py                21KB  — AI tweet/reply generator
├── .gitignore                   1KB
├── http_utils.py                4KB  — shared HTTP helpers
├── image_fetcher.py             4KB  — image download from Pexels/Unsplash
├── image_manager.py            13KB  — image selection, caching, media upload
├── main.py                      1KB  — entry point stub (unused in prod)
├── media/                            — downloaded images/videos (runtime)
├── memory.py                    6KB  — bot memory/context persistence
├── monitor.py                   9KB  — Telethon Telegram monitor
├── monitor_pending.json              — runtime state
├── monitor.pid                       — runtime PID file
├── monitor_queue.json                — runtime state
├── monitor_session.session      → symlink (Telethon session)
├── nohup.out                  471KB  — growing log (should be managed)
├── options_scored.md                 — design document
├── pending_tweet.json                — runtime state
├── post_thread.js                    — Node.js Threads publisher (legacy)
├── promptfoo_reply_gen.yaml          — test config
├── publish_dual.py              5KB  — dual X+Threads publish wrapper
├── reply_generator_prompt.txt        — prompt file
├── reply_gen_prompt.json             — prompt file
├── reply_gen_user_msg.txt            — prompt file
├── reply_scanner.py             3KB  — scan X replies
├── requirements.txt             1KB
├── scheduler.py                 4KB  — news → tweet scheduler
├── settings.py                  4KB  — config/validation
├── sol_commands.pid                  — runtime PID file
├── sol_commands.py             56KB  — Telegram command handler (main bot)
├── sol_dashboard_api.py        56KB  — FastAPI dashboard
├── sol_dashboard_mockup.html   36KB  — design artifact
├── sol_dashboard_proposal.md   15KB  — design document
├── telegram_client.py           6KB  — shared Telegram client
├── templates/
│   └── dashboard.html          86KB  — Jinja2 dashboard template
├── tests/
│   └── brain_test.yaml               — promptfoo test suite
├── threads_publisher.py        23KB  — Instagram Threads API publisher
├── trending_scanner.py         14KB  — trending topic scanner
└── x_publisher.py              14KB  — X/Twitter API publisher
```

**Problem:** 50+ items at root level with no grouping by concern. New contributors can't tell at a glance what's a core bot file vs. runtime state vs. dead code vs. design doc.

---

## Proposed Structure

```
sol-bot/
├── core/                       — bot brain & generation logic
│   ├── generator.py
│   ├── brain.py
│   ├── memory.py
│   ├── content_utils.py
│   └── content_calendar.py
│
├── publishers/                 — output channels
│   ├── x_publisher.py
│   ├── threads_publisher.py
│   ├── publish_dual.py
│   └── post_thread.js          (legacy, mark deprecated)
│
├── monitor/                    — input channels & signal detection
│   ├── monitor.py
│   ├── trending_scanner.py
│   ├── fetcher.py
│   ├── filter.py
│   └── reply_scanner.py
│
├── dashboard/                  — web dashboard
│   ├── sol_dashboard_api.py
│   ├── data_providers.py
│   ├── analytics_insights.py
│   ├── analytics_tracker.py
│   └── templates/
│       └── dashboard.html
│
├── scheduler/                  — automated scheduling
│   └── scheduler.py
│
├── commands/                   — manual Telegram command handler
│   ├── sol_commands.py
│   └── controls.py
│
├── infra/                      — shared infrastructure utilities
│   ├── settings.py
│   ├── config.py
│   ├── http_utils.py
│   ├── telegram_client.py
│   ├── image_fetcher.py
│   ├── image_manager.py
│   ├── cookie_monitor.py
│   └── backup_bot.py
│
├── prompts/                    — LLM prompt files
│   ├── reply_generator_prompt.txt
│   ├── reply_gen_prompt.json
│   └── reply_gen_user_msg.txt
│
├── state/                      — runtime state files (gitignored)
│   ├── monitor_pending.json
│   ├── monitor_queue.json
│   ├── pending_tweet.json
│   ├── brain_history.json
│   ├── monitor.pid
│   └── sol_commands.pid
│
├── tests/                      — test suites
│   ├── brain_test.yaml
│   └── promptfoo_reply_gen.yaml
│
├── docs/                       — design artifacts (not code)
│   ├── friction_audit.md
│   ├── options_scored.md
│   ├── sol_dashboard_proposal.md
│   └── sol_dashboard_mockup.html
│
├── media/                      — downloaded media (gitignored, runtime)
├── .env → /root/x-bot/.env     — symlink (keep)
├── .env.example
├── .gitignore
└── requirements.txt
```

---

## Migration Safety Assessment

### Files Safe to Move (No Import Path Changes Needed)

These files use only `Path(__file__).parent` for relative paths and have no cross-module imports that would break:

| File | Move To | Why Safe |
|------|---------|----------|
| `fetcher.py` | `monitor/` | No imports from other bot files |
| `filter.py` | `monitor/` | No imports from other bot files |
| `content_utils.py` | `core/` | No imports from other bot files |
| `reply_generator_prompt.txt` | `prompts/` | Not a Python module |
| `reply_gen_prompt.json` | `prompts/` | Not a Python module |
| `reply_gen_user_msg.txt` | `prompts/` | Not a Python module |
| `sol_dashboard_proposal.md` | `docs/` | Not code |
| `sol_dashboard_mockup.html` | `docs/` | Not code |
| `friction_audit.md` | `docs/` | Not code |
| `options_scored.md` | `docs/` | Not code |
| `promptfoo_reply_gen.yaml` | `tests/` | Not imported by Python |
| State JSON files | `state/` | Paths defined as constants — update constants |

---

### Files Requiring Import Path Updates

These files import from sibling files that would move, or are imported by other files. Moving them requires updating import statements and/or `Path` constant definitions.

| File | Move To | Breaking Imports | Files That Must Be Updated |
|------|---------|-----------------|---------------------------|
| `generator.py` | `core/` | imports `memory`, `image_manager`, `settings`, `filter` | `sol_commands.py`, `scheduler.py` |
| `brain.py` | `core/` | imports `settings` | `sol_commands.py`, `monitor.py` |
| `memory.py` | `core/` | imports `settings` | `generator.py`, `sol_commands.py` |
| `settings.py` | `infra/` | imported by almost everything | ALL files |
| `image_manager.py` | `infra/` | imports `image_fetcher`, `settings` | `generator.py`, `sol_commands.py` |
| `image_fetcher.py` | `infra/` | imports `settings` | `image_manager.py` |
| `http_utils.py` | `infra/` | standalone | `analytics_insights.py`, `trending_scanner.py` |
| `telegram_client.py` | `infra/` | imports `settings` | `monitor.py`, `sol_commands.py` |
| `controls.py` | `commands/` | imports `settings` | `sol_commands.py` |
| `monitor.py` | `monitor/` | imports `brain`, `settings`, `telegram_client` | systemd service path |
| `sol_commands.py` | `commands/` | imports many modules | systemd service path |
| `sol_dashboard_api.py` | `dashboard/` | imports many modules | systemd service path |
| `analytics_insights.py` | `dashboard/` | imports `settings`, `http_utils` | `sol_dashboard_api.py` |
| `data_providers.py` | `dashboard/` | imports `settings` | `sol_dashboard_api.py` |
| `threads_publisher.py` | `publishers/` | imports `settings`, `image_manager` | `publish_dual.py` |
| `x_publisher.py` | `publishers/` | imports `settings` | `publish_dual.py`, `sol_commands.py` |
| `publish_dual.py` | `publishers/` | imports `x_publisher`, `threads_publisher` | `sol_commands.py`, `sol_dashboard_api.py` |
| `scheduler.py` | `scheduler/` | imports `generator`, `fetcher`, `filter`, `settings` | systemd service path |
| `trending_scanner.py` | `monitor/` | imports `http_utils`, `settings` | `sol_commands.py`, `scheduler.py` |
| `content_calendar.py` | `core/` | imports `settings` | `sol_commands.py` |
| `backup_bot.py` | `infra/` | imports `settings` | standalone script |

---

### Systemd Service Paths That Must Be Updated

```
sol_commands.service     → ExecStart path: /root/x-bot/sol-bot/sol_commands.py
                           → New path: /root/x-bot/sol-bot/commands/sol_commands.py

monitor.service          → ExecStart path: /root/x-bot/sol-bot/monitor.py
                           → New path: /root/x-bot/sol-bot/monitor/monitor.py

sol-dashboard.service    → ExecStart path: /root/x-bot/sol-bot/sol_dashboard_api.py
                           → New path: /root/x-bot/sol-bot/dashboard/sol_dashboard_api.py
```

---

### State File Path Constants That Must Be Updated

All JSON state files are referenced via `Path` constants in multiple files. If moved to `state/`, update these constants:

| Constant | Defined In | New Path |
|----------|-----------|----------|
| `MONITOR_PENDING_FILE` | `monitor.py` | `../state/monitor_pending.json` |
| `MONITOR_QUEUE_FILE` | `monitor.py` | `../state/monitor_queue.json` |
| `PENDING_TWEET_FILE` | `sol_commands.py` | `../state/pending_tweet.json` |
| `BRAIN_HISTORY_FILE` | `brain.py` | `../state/brain_history.json` |
| `PID_FILE` | `sol_commands.py` | `../state/sol_commands.pid` |
| `MONITOR_PID_FILE` | `monitor.py` | `../state/monitor.pid` |

---

## Migration Recommendation

**Do NOT do a big-bang migration.** The flat structure works fine for a solo project. If restructuring, do it incrementally:

### Phase 1 — Zero-risk moves (no Python imports affected)
1. Move design docs to `docs/`
2. Move prompt text files to `prompts/`
3. Move test configs to `tests/`
4. Delete or archive `dashboard.py` (dead code)
5. Delete `main.py` if unused

### Phase 2 — Create `state/` directory
1. Create `state/` dir
2. Update all `Path` constants to point there
3. Move existing JSON files (requires restart of running processes)

### Phase 3 — Restructure Python modules
1. Add `sys.path` manipulation or install as package (`pyproject.toml`)
2. Move files one directory at a time, updating imports
3. Update systemd service files
4. Test each service after each move

### Alternative: Keep Flat, Just Clean Up
If the restructuring cost isn't worth it, the minimum viable cleanup is:
1. Delete `dashboard.py` (dead code, 22KB)
2. Move docs to `docs/`
3. Move prompts to `prompts/`
4. Add `state/` for JSON state files

This reduces root clutter by ~15 items with zero import changes.
