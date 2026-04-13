# Sol Bot — Code Quality Audit
_Generated: 2026-04-09 | Auditor: engineering-advanced-skills + tech-debt-tracker_

---

## Executive Summary

**9,375 lines** across ~37 Python files. The codebase is functional and well-structured overall, but has a recurring split personality: some files use best practices (atomic writes, proper error handling, async patterns) while others ignore them. The two largest files (`sol_commands.py` at 56KB, `sol_dashboard_api.py` at 56KB) are monoliths that handle too many concerns. One file (`dashboard.py`) appears to be dead code from a prior Streamlit era.

| Category | Findings |
|----------|----------|
| Dead code | 1 file, multiple functions |
| Inconsistent patterns | 20+ non-atomic writes vs 3 atomic |
| Error handling gaps | 2 bare `except: pass`, several silent failures |
| Blocking calls in async | 3 confirmed |
| Functions >100 lines | ~8 estimated |
| Missing input validation | 4 endpoints |

---

## 1. Dead Code

### CQ-01 — `dashboard.py` Is a Streamlit Remnant (459 lines, never called)
**File:** `dashboard.py` (22,007 bytes)

This file is the original Streamlit dashboard, fully superseded by `sol_dashboard_api.py` (FastAPI). It is not imported by any other file. It runs as a standalone Streamlit app that was replaced. Keeping it causes confusion about which dashboard is authoritative.

**Evidence:** No other Python file imports from `dashboard.py`. The systemd service runs `sol_dashboard_api.py`, not `dashboard.py`.

**Recommendation:** Archive or delete. If kept for reference, add a comment at the top: `# DEPRECATED — replaced by sol_dashboard_api.py`.

---

### CQ-02 — `main.py` Is a Near-Empty Stub (608 bytes)
**File:** `main.py`

Contains only a stub entry point. All actual orchestration is done by the individual scripts (run as systemd services or nohup). If `main.py` is not used in production, it should be removed to reduce confusion.

---

### CQ-03 — `sol_dashboard_mockup.html` and `sol_dashboard_proposal.md` Are Design Artifacts
**Files:** `sol_dashboard_mockup.html` (36KB), `sol_dashboard_proposal.md` (15KB)

These are planning/design artifacts that belong in a `/docs` or `/design` folder, not the root of the bot directory. They are not served by any endpoint.

---

## 2. Inconsistent JSON Write Patterns

### CQ-04 — 20 Non-Atomic Writes vs 3 Atomic Writes (Inconsistency)

The codebase has two patterns for writing JSON state files. The safe pattern (atomic) is used in only 3 places; the unsafe pattern (direct `write_text`) is used in ~20 places.

**Safe pattern (atomic) — only used in:**
- `sol_dashboard_api.py:280-284` — publish_log.json
- `sol_commands.py:928-938` — publish_log.json
- `backup_bot.py:96-100` — backup files

**Unsafe pattern (direct write) — used in:**
| File | Lines | File Written |
|------|-------|-------------|
| `sol_commands.py` | 222, 403, 483, 668, 720, 774, 785, 812 | pending_tweet.json, pending_combo.json, etc. |
| `monitor.py` | 125, 140 | monitor_pending.json, monitor_queue.json |
| `scheduler.py` | 125 | pending_sched_N.json |
| `brain.py` | 77-79 | brain_history.json |
| `image_manager.py` | 118-120 | media manifests |

**Risk:** A process crash or power loss during a non-atomic `write_text()` call leaves a truncated or empty JSON file. The bot will fail to parse it on next startup with `json.JSONDecodeError`, losing queued tweets or pending state.

**Recommended fix — create a shared utility:**
```python
# in a new file: utils/atomic_write.py (or add to existing utils)
import os, tempfile, json
from pathlib import Path

def write_json_atomic(path: Path, data) -> None:
    """Write JSON to path atomically using tempfile + os.replace."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(path))
    except Exception:
        os.unlink(tmp)
        raise
```

Then replace all `path.write_text(json.dumps(...))` with `write_json_atomic(path, data)`.

---

## 3. Error Handling Gaps

### CQ-05 — Bare `except: pass` Clauses (Silent Failures)
**File:** `sol_commands.py:978`
```python
except:
    pass
```

**File:** `sol_commands.py:1015`
```python
except:
    pass
```

Bare `except` catches `SystemExit`, `KeyboardInterrupt`, and `GeneratorExit` in addition to regular exceptions. Silently swallowing errors makes debugging impossible — a publish failure would not appear in logs.

**Fix:**
```python
except Exception as e:
    logger.error(f"Publish failed: {e}", exc_info=True)
```

---

### CQ-06 — Silent JSON Parse Failures May Lose State
**File:** `monitor.py:130-133`
```python
try:
    queue = json.loads(MONITOR_QUEUE_FILE.read_text()) if MONITOR_QUEUE_FILE.exists() else []
except (json.JSONDecodeError, OSError):
    queue = []
```

On a corrupted `monitor_queue.json`, this silently resets the queue to empty, losing all pending items. The `except` is correct (better than a crash) but should log a warning so the operator knows state was lost.

**Fix:**
```python
except (json.JSONDecodeError, OSError) as e:
    logger.warning(f"[monitor] Corrupt queue file, resetting: {e}")
    queue = []
```

---

### CQ-07 — analytics_insights.py Uses `time.sleep()` in Retry Logic
**File:** `analytics_insights.py:104, 111, 115`
```python
time.sleep(wait)          # wait = exponential backoff
time.sleep(5 * (attempt + 1))
```

If this module is ever called from an async context (e.g., a FastAPI background task), these blocking sleeps will freeze the event loop for the entire duration. Currently called via subprocess or threading, so it's not broken — but it's fragile architecture.

**Recommendation:** Replace with `asyncio.sleep` if used in async context, or document clearly that this module is synchronous-only.

---

## 4. Blocking Calls in Async Context

### CQ-08 — `time.sleep(1)` in sol_commands.py Async Handler
**File:** `sol_commands.py:1382`
```python
time.sleep(1)
```

Inside an `async def` function that is awaited by the Telethon event loop. This blocks the entire event loop for 1 second — during this time, no Telegram messages can be processed.

**Fix:**
```python
await asyncio.sleep(1)
```

---

### CQ-09 — yfinance and Requests Calls Block the Event Loop
**Files:** `data_providers.py`, `analytics_insights.py`

HTTP calls using `requests` (synchronous) made from within async handlers block the asyncio event loop. The dashboard's SSE endpoint and signal-fetching endpoints appear to call these synchronously.

**Fix:** Wrap in `asyncio.get_event_loop().run_in_executor(None, sync_function)`:
```python
import asyncio
result = await asyncio.get_event_loop().run_in_executor(None, fetch_yfinance_data)
```
Or switch to `httpx` with async support.

---

## 5. Monolithic Files

### CQ-10 — `sol_commands.py` Is 1,388 Lines / 56KB
**File:** `sol_commands.py`

Handles: Telegram bot setup, command routing, tweet generation, image processing, scheduling, publishing to X, publishing to Threads, queue management, PID file management, help text rendering. This is 8+ distinct concerns in one file.

**Proposed split:**
| Module | Contents |
|--------|----------|
| `commands/bot_setup.py` | Telegram client init, event handlers |
| `commands/publish_handler.py` | Manual publish logic |
| `commands/queue_manager.py` | Pending tweet queue read/write |
| `commands/scheduler_cmds.py` | Schedule-related commands |
| `core/pid_manager.py` | PID file utilities (shared) |

---

### CQ-11 — `sol_dashboard_api.py` Is 1,440 Lines / 56KB
**File:** `sol_dashboard_api.py`

Handles: Auth middleware, 30+ API endpoints, SSE log streaming, SQLite analytics, yfinance data, GDELT signals, Polymarket data, media serving, publish history, tweet generation, reply management.

**Proposed split:**
| Module | Contents |
|--------|----------|
| `dashboard/auth.py` | AuthMiddleware, session management |
| `dashboard/endpoints_analytics.py` | SQLite analytics queries |
| `dashboard/endpoints_signals.py` | GDELT, Polymarket, yfinance |
| `dashboard/endpoints_publish.py` | Tweet publish, history |
| `dashboard/endpoints_logs.py` | SSE log stream |
| `dashboard/media.py` | `/media/{filename}` serving |
| `dashboard/app.py` | FastAPI app init, middleware wiring |

---

## 6. Missing Input Validation

### CQ-12 — Dashboard API Endpoints Accept Unvalidated Free Text
**File:** `sol_dashboard_api.py` — multiple POST endpoints

Tweet text, hashtags, and other user input is passed directly to subprocess and AI models without length validation, character filtering, or sanitization. At minimum:

- `tweet_text`: must be ≤280 chars, no null bytes
- `model`: must be in an allowlist (not passed to subprocess but used in API calls)
- `media_filename`: must resolve within MEDIA_DIR

---

## 7. Memory Growth Risk

### CQ-13 — `nohup.out` Is 471KB and Growing
**File:** `nohup.out` (471,116 bytes)

The monitor process writes all stdout/stderr to `nohup.out` with no rotation. Over months this will grow unbounded. The file is in the bot directory where other processes read JSON files — a runaway log could fill the disk.

**Fix:** Redirect to a log file managed by logrotate, or use `--output` flag with systemd's journal:
```bash
# Instead of nohup, use systemd service with:
StandardOutput=journal
StandardError=journal
```

---

### CQ-14 — `_gdelt_cache`, `_polymarket_cache`, `_markets_cache` Could Grow
**File:** `sol_dashboard_api.py:86-88`
```python
_gdelt_cache: dict = {"data": None, "ts": 0.0}
_polymarket_cache: dict = {"data": None, "ts": 0.0}
_markets_cache: dict = {"data": None, "ts": 0.0}
```

These are TTL caches with a single entry each — that's fine and bounded. Not a memory leak, but confirm TTL eviction is working correctly (check that stale data is never served indefinitely).

---

## 8. Dependency Issues

### CQ-15 — requirements.txt Uses `>=` Pins With No Lockfile
**File:** `requirements.txt`
```
anthropic>=0.85.0
fastapi>=0.110.0
tweepy>=4.14.0
...
```

`>=` means any future major version will be installed. A `pip install` on a new server six months from now could pull in breaking changes. No `requirements.lock` or `poetry.lock` exists.

**Fix (minimal):** Generate a pinned lockfile:
```bash
pip freeze > requirements.lock
```
Or use `pip-tools`:
```bash
pip-compile requirements.in --output-file requirements.txt
```

---

## 9. Code Duplication

### CQ-16 — Publish Log Read/Write Logic Duplicated
**Files:** `sol_commands.py:920-940`, `sol_dashboard_api.py:270-295`

Both files implement the same pattern: read `publish_log.json`, append new entry, trim to last N, write atomically. This logic should live in a single shared utility.

---

### CQ-17 — PID File Check Logic Duplicated
**Files:** `sol_commands.py:1265-1276`, `monitor.py:245-254`

Both implement the same PID file existence check with stale-PID detection. Candidate for a shared `core/pid_manager.py`.

---

## Summary Debt Score

| Category | Severity | Count |
|----------|----------|-------|
| Dead code | Medium | 1 file (dashboard.py, 22KB) |
| Non-atomic writes | High | ~20 call sites |
| Bare except clauses | High | 2 |
| Blocking in async | Medium | 3 |
| Missing validation | Medium | 4 endpoints |
| Monolithic files | Medium | 2 files |
| Duplicate logic | Low | 2 patterns |
| No lockfile | Low | 1 |
| Growing log file | Low | 1 |
