# Sol Bot — Top 10 Improvements by ROI
_Generated: 2026-04-09 | Auditor: engineering-advanced-skills + performance-profiler + tech-debt-tracker_

---

## Ranking Criteria

**ROI = (Impact × Urgency) / Effort**

- **Impact**: How much does this improve reliability, security, or developer experience?
- **Urgency**: Is something currently broken or actively dangerous?
- **Effort**: How long does the fix take to implement and test?

---

## #1 — Fix .env Permissions (644 → 600)
**Category:** Security  
**Effort:** 30 seconds  
**Impact:** CRITICAL — prevents any local process from reading all API keys

The `.env` file containing every credential is world-readable. One compromised process or user on this server has instant access to X, Anthropic, Telegram, Threads, Pexels, and OpenRouter APIs.

```bash
chmod 600 /root/x-bot/.env
```

**Why this is #1:** Zero effort, eliminates the highest-impact attack vector. Should be done before reading the rest of this document.

---

## #2 — Standardize All JSON Writes to Atomic Pattern
**Category:** Reliability  
**Effort:** 2–3 hours (20 call sites)  
**Impact:** HIGH — prevents state corruption on process crash

~20 state files (`pending_tweet.json`, `monitor_queue.json`, `brain_history.json`, etc.) are written with `path.write_text(json.dumps(...))`. A crash or OOM kill during the write leaves a truncated file. The next startup raises `json.JSONDecodeError` and the bot fails to recover its state.

**Fix:** Add one shared utility function, replace all call sites:
```python
def write_json_atomic(path: Path, data) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(path))
    except Exception:
        os.unlink(tmp)
        raise
```

**Why #2:** State corruption is the most common silent failure mode for this type of bot. One bad deploy or OOM event could lose the entire pending tweet queue.

---

## #3 — Fix Path Traversal in `/media/{filename}`
**Category:** Security  
**Effort:** 10 minutes  
**Impact:** HIGH — prevents file system escape from the dashboard

A single line fix blocks the entire class of path traversal attacks. Currently `GET /media/../../../etc/passwd.jpg` would serve the file if it exists.

```python
# sol_dashboard_api.py — in serve_media()
path = (MEDIA_DIR / filename).resolve()
if not path.is_relative_to(MEDIA_DIR.resolve()):
    raise HTTPException(status_code=403, detail="Access denied")
```

**Why #3:** Trivial to fix, exploitable today.

---

## #4 — Replace Base64 Session Token with Random Token
**Category:** Security  
**Effort:** 30 minutes  
**Impact:** HIGH — current token IS the password, just encoded

The dashboard session cookie is `base64("sol:solpass123")`. Anyone who captures the cookie can instantly decode the credentials and use them elsewhere. Replace with an opaque random token:

```python
# sol_dashboard_api.py
import secrets
SESSION_TOKEN = secrets.token_hex(32)   # random at startup, not derived from password
DASHBOARD_PASS = os.environ["DASHBOARD_PASS"]  # fail if unset
```

Also: remove the `"solpass123"` default from source code entirely.

**Why #4:** The current scheme provides the illusion of auth, not real auth. A captured cookie reveals the password for reuse.

---

## #5 — Fix Non-Atomic .env Rewrite in threads_publisher.py
**Category:** Reliability + Security  
**Effort:** 30 minutes  
**Impact:** HIGH — a crash during token refresh corrupts all credentials

When the Threads access token is refreshed, the code truncates `.env` then rewrites it line by line. A SIGKILL between those two steps leaves `.env` empty — all services fail to start.

```python
# threads_publisher.py — token refresh
fd, tmp = tempfile.mkstemp(dir=str(ENV_PATH.parent), suffix=".tmp")
with os.fdopen(fd, "w") as f:
    for line in lines:
        if line.strip().startswith("THREADS_ACCESS_TOKEN="):
            f.write(f"THREADS_ACCESS_TOKEN={new_token}\n")
        else:
            f.write(line)
os.replace(tmp, str(ENV_PATH))   # atomic swap
```

**Why #5:** Token refresh runs automatically. If it ever fails mid-write during peak activity (rate limit, OOM), recovery requires manual intervention.

---

## #6 — Move Hardcoded Bearer Token Out of Source
**Category:** Security  
**Effort:** 5 minutes  
**Impact:** HIGH — token is now in git history permanently

`analytics_insights.py:35` has a hardcoded X bearer token. Even if rotated, the old token remains in git history.

```python
# analytics_insights.py:35 — change to:
BEARER = f"Bearer {os.environ['X_BEARER_TOKEN']}"
```

Then rotate the token in the X Developer Portal.

**Why #6:** Trivial change, token is permanently in git history until history is rewritten.

---

## #7 — Add Security Headers Middleware
**Category:** Security  
**Effort:** 30 minutes  
**Impact:** MEDIUM — blocks clickjacking, MIME sniffing, basic XSS vectors

Add a single middleware to `sol_dashboard_api.py`:

```python
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update({
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com https://cdn.tailwindcss.com",
        "Referrer-Policy": "strict-origin-when-cross-origin",
    })
    return response
```

Note: the CSP needs `'unsafe-inline'` and CDN allowances because the dashboard uses inline scripts and loads HTMX from unpkg.

**Why #7:** One middleware block, no logic changes, covers a class of browser-based attacks.

---

## #8 — Fix Bare `except: pass` Clauses
**Category:** Reliability  
**Effort:** 30 minutes  
**Impact:** MEDIUM — silent publish failures are invisible in logs

Two bare `except: pass` blocks in `sol_commands.py:978` and `:1015` silently swallow publish errors. If a tweet fails to publish, the operator has no way of knowing — no log entry, no Telegram notification.

```python
# Before:
except:
    pass

# After:
except Exception as e:
    logger.error(f"[sol_commands] Publish failed: {e}", exc_info=True)
    await event.reply(f"Publish failed: {e}")
```

**Why #8:** Silent failures are the hardest bugs to diagnose. A failed publish looks identical to a successful one from the outside.

---

## #9 — Delete `dashboard.py` (22KB of Dead Code)
**Category:** Code Quality  
**Effort:** 5 minutes  
**Impact:** MEDIUM — removes confusion about which dashboard is canonical

`dashboard.py` is the original Streamlit dashboard, fully replaced by `sol_dashboard_api.py`. It's 22KB of code that creates ambiguity: is `dashboard.py` or `sol_dashboard_api.py` the real dashboard? New contributors will be confused.

```bash
git rm sol-bot/dashboard.py
git commit -m "remove: delete deprecated Streamlit dashboard (replaced by FastAPI)"
```

Also candidates for removal: `main.py` (unused entry point stub), `sol_dashboard_mockup.html` and `sol_dashboard_proposal.md` (move to `docs/`).

**Why #9:** Dead code has negative ROI — it costs maintenance attention and creates confusion for zero benefit.

---

## #10 — Set Up Log Rotation for nohup.out
**Category:** Operations  
**Effort:** 1 hour  
**Impact:** MEDIUM — prevents disk fill on long-running server

`nohup.out` is already 471KB and growing. The monitor process has been running for days. At this rate, the file could fill available disk over weeks/months, causing service failures.

**Fix option A — Switch to systemd (recommended):**
```ini
# /etc/systemd/system/sol-monitor.service
[Service]
ExecStart=/usr/bin/python3 /root/x-bot/sol-bot/monitor.py
StandardOutput=journal
StandardError=journal
Restart=on-failure
```
systemd-journald handles rotation automatically.

**Fix option B — logrotate:**
```
# /etc/logrotate.d/sol-bot
/root/x-bot/sol-bot/nohup.out {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
```

**Why #10:** Disk-full events take down all services simultaneously and are hard to diagnose under pressure.

---

## Bonus: Quick Wins Not in Top 10

These are small improvements that don't rank in the top 10 by ROI but are worth doing in a cleanup sprint:

| Item | File | Effort | Notes |
|------|------|--------|-------|
| `await asyncio.sleep(1)` instead of `time.sleep(1)` | `sol_commands.py:1382` | 2 min | Unblocks event loop |
| Pin exact dependency versions | `requirements.txt` | 30 min | `pip freeze > requirements.lock` |
| Add `Origin` header check (lightweight CSRF) | `sol_dashboard_api.py` | 30 min | Validates request source |
| Log corrupted JSON resets | `monitor.py:133` | 5 min | Add `logger.warning()` on except |
| Fix hardcoded `/root/x-bot/.env` path | `backup_bot.py:29` | 5 min | Use `Path(__file__).parent / ".env"` |

---

## Implementation Roadmap

```
Week 1 — Security Hardening
  Day 1: chmod 600 .env (#1), rotate bearer token (#6), remove hardcoded default password (#4)
  Day 2: Fix path traversal (#3), fix base64 session token (#4)
  Day 3: Fix .env atomic rewrite (#5), add security headers (#7)

Week 2 — Reliability
  Day 1–2: Implement write_json_atomic() utility, replace all 20 call sites (#2)
  Day 3: Fix bare except clauses (#8)
  Day 4: Set up log rotation / systemd for monitor (#10)

Week 3 — Code Health
  Day 1: Delete dashboard.py and other dead files (#9)
  Day 2: Move docs to docs/, prompts to prompts/ (zero-risk restructure)
  Day 3: Pin requirements to exact versions
```
