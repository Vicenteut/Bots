# Sol Bot — Security Audit
_Generated: 2026-04-09 | Auditor: engineering-advanced-skills + dependency-auditor_

---

## Executive Summary

**15 findings** across 5 severity levels. Two items require immediate action before next deployment: world-readable `.env` file and hardcoded default dashboard credentials. The codebase is a personal/small-team bot, so the attack surface is limited, but several issues would be catastrophic if the dashboard were ever exposed beyond localhost.

| Severity | Count |
|----------|-------|
| CRITICAL | 3 |
| HIGH     | 5 |
| MEDIUM   | 5 |
| LOW      | 2 |

---

## CRITICAL

### SEC-01 — .env File World-Readable (644 permissions)
**File:** `/root/x-bot/.env`
**Permissions:** `-rw-r--r--` (644) — readable by ALL users on the system

The `.env` file containing every API key (X/Twitter, Anthropic, OpenRouter, Telegram, Threads, Pexels, Unsplash) is readable by any process or user on this server.

**Impact:** Any process running as any user (web server, cronjob, compromised dependency) can `cat /root/x-bot/.env` and extract all credentials.

**Fix:**
```bash
chmod 600 /root/x-bot/.env
```

**Verify:**
```bash
ls -la /root/x-bot/.env
# Expected: -rw------- 1 root root ...
```

---

### SEC-02 — Hardcoded Default Dashboard Password in Source Code
**File:** `sol_dashboard_api.py:92`
```python
DASHBOARD_USER = os.getenv("DASHBOARD_USER", "sol")
DASHBOARD_PASS = os.getenv("DASHBOARD_PASS", "solpass123")   # ← hardcoded fallback
SESSION_TOKEN  = base64.b64encode(f"{DASHBOARD_USER}:{DASHBOARD_PASS}".encode()).decode()
```

**Impact:** If `DASHBOARD_PASS` is absent from `.env`, the dashboard defaults to `solpass123`. Anyone who reads the source (or this repo) knows the password. The SESSION_TOKEN is just `base64("sol:solpass123")` — trivially decoded with `base64 -d`.

**Fix:**
1. Remove the default: `DASHBOARD_PASS = os.getenv("DASHBOARD_PASS")` — fail at startup if unset.
2. Replace base64 session token with a signed JWT or `secrets.token_hex(32)`.
3. Add startup validation: `if not DASHBOARD_PASS: raise RuntimeError("DASHBOARD_PASS not set")`

---

### SEC-03 — Hardcoded X/Twitter Bearer Token in Source
**File:** `analytics_insights.py:35`
```python
BEARER = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D..."
```

This token is committed to source code. Even if it is a public/app-level bearer token (not user-specific), it should live in `.env` as `X_BEARER_TOKEN`. The token is now permanently in git history.

**Fix:**
```python
BEARER = f"Bearer {os.environ['X_BEARER_TOKEN']}"
```
Then rotate the token in the X Developer Portal.

---

## HIGH

### SEC-04 — Path Traversal in `/media/{filename}` Endpoint
**File:** `sol_dashboard_api.py:846-853`
```python
@app.get("/media/{filename}")
async def serve_media(filename: str):
    if Path(filename).suffix.lower() not in ALLOWED_MEDIA_EXT:
        raise HTTPException(status_code=403, ...)
    path = MEDIA_DIR / filename          # ← constructed BEFORE sanitization
    if not path.exists():
        raise HTTPException(status_code=404, ...)
    return FileResponse(path)
```

**Attack:** `GET /media/../../../../etc/passwd.jpg` — the extension check passes (`.jpg`), `MEDIA_DIR / "../../../../etc/passwd.jpg"` resolves outside the media dir.

**Fix:**
```python
path = (MEDIA_DIR / filename).resolve()
if not path.is_relative_to(MEDIA_DIR.resolve()):
    raise HTTPException(status_code=403, detail="Access denied")
```

---

### SEC-05 — Non-Atomic `.env` Rewrite (Credentials Can Be Corrupted)
**File:** `threads_publisher.py:545-557`
```python
with open(ENV_PATH, "r") as f:
    lines = f.readlines()
with open(ENV_PATH, "w") as f:       # ← file truncated here
    for line in lines:
        if line.strip().startswith("THREADS_ACCESS_TOKEN="):
            f.write(f"THREADS_ACCESS_TOKEN={new_token}\n")
        else:
            f.write(line)
```

**Impact:** If the process is killed between the `open("w")` truncation and the full write, `.env` is empty/partial. All services fail to start. No backup is made.

**Fix:** Use atomic write pattern already used in `sol_dashboard_api.py:280-284`:
```python
fd, tmp = tempfile.mkstemp(dir=str(ENV_PATH.parent), suffix=".tmp")
with os.fdopen(fd, "w") as f:
    for line in lines:
        ...
os.replace(tmp, str(ENV_PATH))
```

---

### SEC-06 — Subprocess Arguments Not Sanitized
**Files:**
- `sol_dashboard_api.py:491` — `tweet_text` from API request body passed to subprocess
- `sol_commands.py:957` — `tweet` and `media_path` from Telegram message passed to subprocess

```python
# sol_dashboard_api.py:491
cmd = ["python3", "publish_dual.py"] + media_args + [tweet_text]
result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BOT_DIR))
```

**Risk:** `shell=False` (list form) prevents shell injection, but unvalidated args can still exploit bugs in the called script (argument injection). `media_path` is user-controlled and passed as `--image <path>` — a path like `--image /etc/passwd` would be silently accepted.

**Fix:**
```python
# Validate tweet_text length and charset
if len(tweet_text) > 280:
    raise HTTPException(400, "Tweet too long")
# Validate media_path is inside MEDIA_DIR
if media_path:
    media_resolved = Path(media_path).resolve()
    if not media_resolved.is_relative_to(MEDIA_DIR.resolve()):
        raise HTTPException(400, "Invalid media path")
```

---

### SEC-07 — Missing HTTP Security Headers
**File:** `sol_dashboard_api.py` — FastAPI app has no security header middleware

Missing headers that would block common browser-based attacks:

| Header | Risk Without It |
|--------|----------------|
| `X-Content-Type-Options: nosniff` | MIME-type sniffing attacks |
| `X-Frame-Options: DENY` | Clickjacking |
| `Content-Security-Policy` | XSS, data injection |
| `X-XSS-Protection: 1; mode=block` | Reflected XSS (legacy browsers) |

**Fix:** Add Starlette middleware (2 lines):
```python
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
# Or simpler:
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response
```

---

### SEC-08 — Weak Session Token (Base64-Encoded Plaintext Credentials)
**File:** `sol_dashboard_api.py:95`
```python
SESSION_TOKEN = base64.b64encode(f"{DASHBOARD_USER}:{DASHBOARD_PASS}".encode()).decode()
```

This means the session cookie value IS the credentials, just base64-encoded. Anyone who captures the cookie can immediately decode it to get the username and password:
```bash
echo "c29sOnNvbHBhc3MxMjM=" | base64 -d
# → sol:solpass123
```

**Fix:** Use `secrets.token_hex(32)` at startup. Store the token in memory only. On login success, set the cookie to this random token, not a derivation of credentials:
```python
SESSION_TOKEN = secrets.token_hex(32)  # generated at startup, not derived from password
```

---

## MEDIUM

### SEC-09 — Weak Password Hashing (Plain SHA-256, No Salt)
**File:** `settings.py:21`
```python
_DEFAULT_HASH = hashlib.sha256(b"sol2026").hexdigest()
PASSWORD_HASH = os.getenv("DASHBOARD_PASSWORD_HASH", _DEFAULT_HASH)
```

SHA-256 without salt or iterations is trivially crackable with rainbow tables. The default hash for `"sol2026"` is published in source.

**Fix:** Use `bcrypt` or `argon2-cffi`:
```python
import bcrypt
def check_password(plain: str, hashed: bytes) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed)
```

---

### SEC-10 — Monitor Queue TOCTOU Race Condition
**File:** `monitor.py:130-140`
```python
queue = json.loads(MONITOR_QUEUE_FILE.read_text()) if MONITOR_QUEUE_FILE.exists() else []
# ... (gap here — another process could write) ...
queue.append(entry)
MONITOR_QUEUE_FILE.write_text(json.dumps(queue, ...))
```

Two rapid Telegram messages could race: both read the same queue, both append, one write wins and the other is silently lost.

**Fix:** Use `fcntl.flock` for process-level locking, or switch to SQLite (which has built-in locking).

---

### SEC-11 — Audit Log Race Condition (Concurrent Append Writes)
**File:** `controls.py:26-27`
```python
with open(AUDIT_LOG, "a") as f:
    f.write(json.dumps(entry) + "\n")
```

Multiple concurrent audit events could interleave their writes, producing malformed JSON lines.

**Fix:** Use `fcntl.flock(f, fcntl.LOCK_EX)` before writing, or use Python's `logging` module (which is thread-safe).

---

### SEC-12 — No CSRF Protection on State-Changing Endpoints
**File:** `sol_dashboard_api.py` — all POST endpoints

The dashboard has no CSRF tokens. Any website the user visits while authenticated can make cross-origin POST requests to the dashboard (if it's accessible on the network).

**Fix:** For a LAN-only dashboard, this risk is low. Mitigation: validate `Origin` header matches expected host, or add `SameSite=Strict` to the session cookie.

---

### SEC-13 — Brain History TOCTOU
**File:** `brain.py:74-89`
```python
def append_to_history(role: str, content: str):
    h = load_history()          # read
    h.append({"role": role, "content": content})
    save_history(h[-10:])       # write (non-atomic)
```

`save_history` uses `write_text()` which is not atomic. A crash mid-write corrupts `brain_history.json`, causing the next Claude call to fail on JSON parse.

**Fix:** Use `tempfile.mkstemp()` + `os.replace()` in `save_history`.

---

## LOW

### SEC-14 — .env File Is a Symlink (Double Permission Check Needed)
**File:** `/root/x-bot/sol-bot/.env -> /root/x-bot/.env`

The symlink itself has `lrwxrwxrwx` (777), but actual access is governed by the target `/root/x-bot/.env`. As noted in SEC-01, the target is 644 (world-readable). The symlink layer adds confusion — `chmod` on the symlink doesn't change target permissions.

**Fix:** Always `chmod 600 /root/x-bot/.env` (the target file).

---

### SEC-15 — Hardcoded Absolute Path in backup_bot.py
**File:** `backup_bot.py:29`
```python
load_dotenv("/root/x-bot/.env")
```

Hardcoded absolute path means this breaks if the bot is ever moved or run by a different user. It also reveals the directory structure to anyone reading the source.

**Fix:**
```python
load_dotenv(Path(__file__).parent / ".env")
```

---

## Remediation Priority

| Priority | Action | Effort |
|----------|--------|--------|
| Do now | `chmod 600 /root/x-bot/.env` | 30 sec |
| Do now | Rotate hardcoded bearer token in `analytics_insights.py:35` | 5 min |
| Do now | Add `DASHBOARD_PASS` to `.env`, remove hardcoded default | 10 min |
| This week | Fix path traversal in `/media/{filename}` (SEC-04) | 10 min |
| This week | Fix non-atomic `.env` rewrite in `threads_publisher.py` (SEC-05) | 30 min |
| This week | Replace base64 session token with `secrets.token_hex(32)` (SEC-08) | 30 min |
| This week | Add security headers middleware (SEC-07) | 30 min |
| This sprint | Add input validation for subprocess args (SEC-06) | 1h |
| This sprint | Fix TOCTOU on monitor queue and brain history (SEC-10, SEC-13) | 2h |
| Backlog | Replace SHA-256 with bcrypt (SEC-09) | 1h |
| Backlog | Add CSRF protection (SEC-12) | 2h |
