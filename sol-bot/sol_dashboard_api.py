"""
Sol Dashboard API — Tier 1
FastAPI + htmx operational dashboard, port 8502
"""
import asyncio
import base64
import glob
import json
import os
import re
import secrets
import subprocess
import urllib.parse
from filelock import FileLock
try:
    from openai import OpenAI as _OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psutil
from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from starlette.middleware.base import BaseHTTPMiddleware

try:
    from gdeltdoc import GdeltDoc, Filters as GdeltFilters
    _GDELT_AVAILABLE = True
except ImportError:
    _GDELT_AVAILABLE = False

try:
    import requests as _requests
except ImportError:
    _requests = None

try:
    import yfinance as _yfinance
    _YFINANCE_AVAILABLE = True
except ImportError:
    _yfinance = None
    _YFINANCE_AVAILABLE = False

# ─── PATHS ───────────────────────────────────────────────────────────────────
BOT_DIR = Path("/root/x-bot/sol-bot")
LOGS_DIR = Path("/root/x-bot/logs")

PID_FILES = {
    "sol_commands": BOT_DIR / "sol_commands.pid",
    "monitor":      BOT_DIR / "monitor.pid",
}

BRAIN_HISTORY   = BOT_DIR / "brain_history.json"
PUBLISH_LOG     = LOGS_DIR / "publish_log.json"
PENDING_TWEET   = BOT_DIR / "pending_tweet.json"
PENDING_COMBO   = BOT_DIR / "pending_combo.json"
MONITOR_PENDING = BOT_DIR / "monitor_pending.json"
MONITOR_QUEUE      = BOT_DIR / "monitor_queue.json"
MONITOR_QUEUE_LOCK = BOT_DIR / "monitor_queue.lock"
MEDIA_DIR          = BOT_DIR / "media"
CONTEXT_JSON    = BOT_DIR / "context.json"
REPLY_PROMPT    = BOT_DIR / "reply_generator_prompt.txt"
REPLY_USER_TMPL = BOT_DIR / "reply_gen_user_msg.txt"

OPENROUTER_BASE   = "https://openrouter.ai/api/v1"
REPLY_MODEL_MAP   = {
    "haiku":  "anthropic/claude-haiku-4-5",
    "sonnet": "anthropic/claude-sonnet-4-6",
    "opus":   "anthropic/claude-sonnet-4-6",
}
REPLY_DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

LOG_ALLOWLIST = {"sol_commands", "monitor", "scheduler", "analytics", "trending", "replies"}

# ─── SIGNALS CACHE ───────────────────────────────────────────────────────────
_gdelt_cache: dict = {"data": None, "ts": 0.0}
_polymarket_cache: dict = {"data": None, "ts": 0.0}
_markets_cache: dict = {"data": None, "ts": 0.0}

# ─── AUTH ────────────────────────────────────────────────────────────────────
DASHBOARD_USER = os.getenv("DASHBOARD_USER", "sol")
DASHBOARD_PASS = os.getenv("DASHBOARD_PASS") or "solpass123"
SESSION_COOKIE = "sol_session"
# Cryptographically random session token — generated at startup, never derived from credentials
SESSION_TOKEN  = secrets.token_hex(32)
# CSRF token — separate random value, sent to browser and echoed back on state-changing requests
CSRF_TOKEN     = secrets.token_hex(32)


def _check_credentials(user: str, pwd: str) -> bool:
    return secrets.compare_digest(user, DASHBOARD_USER) and secrets.compare_digest(pwd, DASHBOARD_PASS)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 0. Allow login POST, manifest, and static assets through unauthenticated
        path = request.url.path
        if (path == "/login" and request.method == "POST") or \
           path == "/manifest.json" or path.startswith("/static/") or \
           path.startswith("/media/"):
            return await call_next(request)

        # 1. Valid session cookie → pass through
        if request.cookies.get(SESSION_COOKIE) == SESSION_TOKEN:
            return await call_next(request)

        # 2. Valid Basic auth → pass through and set cookie
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                pad = auth[6:] + "=" * (4 - len(auth[6:]) % 4) if len(auth[6:]) % 4 else auth[6:]
                decoded = base64.b64decode(pad).decode("utf-8")
                user, _, pwd = decoded.partition(":")
                if _check_credentials(user, pwd):
                    response = await call_next(request)
                    response.set_cookie(
                        SESSION_COOKIE, SESSION_TOKEN,
                        httponly=True, samesite="lax", max_age=86400 * 7,
                    )
                    return response
            except Exception:
                pass

        # 3. No valid auth → show login page (not raw 401) for browser, 401 for API
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return _login_page_response()

        return Response(
            content="Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Sol Dashboard"'},
        )


def _login_page_response() -> Response:
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SOL // LOGIN</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Barlow+Condensed:wght@600;700&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0;}
  body{background:#080808;color:#e5e5e5;font-family:'Barlow Condensed',sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;}
  .box{background:#111;border:1px solid #2a2a2a;border-radius:6px;padding:36px 40px;width:340px;}
  h1{font-size:18px;letter-spacing:.12em;color:#e5e5e5;margin-bottom:4px;}
  h1 span{color:#f59e0b;}
  .sub{font-family:'IBM Plex Mono',monospace;font-size:11px;color:#4b5563;margin-bottom:28px;}
  label{display:block;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#6b7280;margin-bottom:5px;}
  input{width:100%;background:#1a1a1a;border:1px solid #333;border-radius:3px;color:#e5e5e5;font-family:'IBM Plex Mono',monospace;font-size:13px;padding:9px 11px;outline:none;margin-bottom:14px;}
  input:focus{border-color:#0e7490;}
  button{width:100%;background:#f59e0b;color:#000;border:none;border-radius:3px;font-family:'Barlow Condensed',sans-serif;font-size:13px;font-weight:700;letter-spacing:.06em;padding:10px;cursor:pointer;margin-top:4px;}
  button:hover{filter:brightness(1.1);}
  .err{font-family:'IBM Plex Mono',monospace;font-size:11px;color:#ef4444;margin-bottom:12px;display:none;}
  .err.show{display:block;}
</style>
</head>
<body>
<div class="box">
  <h1>SOL <span>//</span> COMMAND CENTER</h1>
  <div class="sub">dashboard · tier 1</div>
  <div class="err" id="err">Invalid credentials</div>
  <form method="post" action="/login">
    <label>Username</label>
    <input type="text" name="username" autocomplete="username" autofocus>
    <label>Password</label>
    <input type="password" name="password" autocomplete="current-password">
    <button type="submit">ENTER</button>
  </form>
</div>
<script>
if (location.search.includes('error=1')) {
  document.getElementById('err').classList.add('show');
}
</script>
</body>
</html>"""
    return Response(content=html, media_type="text/html", status_code=200)


# ─── APP ─────────────────────────────────────────────────────────────────────
app = FastAPI(title="Sol Dashboard API")
app.mount("/static", StaticFiles(directory=str(BOT_DIR / "static")), name="static")
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")
app.add_middleware(AuthMiddleware)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security headers on every response."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://fonts.gstatic.com; "
            "font-src https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self'"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)

TEMPLATE_PATH = BOT_DIR / "templates" / "dashboard.html"

# ─── GENERATOR (lazy import — avoids blocking startup) ───────────────────────
import sys as _sys
if str(BOT_DIR) not in _sys.path:
    _sys.path.insert(0, str(BOT_DIR))

try:
    from generator import generate_tweet as _generate_tweet, get_model as _get_model
    from generator import generate_combinada_tweet as _generate_combinada_tweet
    _GENERATOR_AVAILABLE = True
    _GENERATOR_ERROR = None
except Exception as _e:
    _GENERATOR_AVAILABLE = False
    _GENERATOR_ERROR = str(_e)


# ─── HELPERS ─────────────────────────────────────────────────────────────────
def _read_pid(name: str) -> dict:
    pid_file = PID_FILES[name]
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # check liveness
        uptime = time.time() - psutil.Process(pid).create_time()
        return {"alive": True, "pid": pid, "uptime_s": round(uptime, 1)}
    except (FileNotFoundError, ValueError):
        return {"alive": False, "pid": None, "uptime_s": 0.0}
    except ProcessLookupError:
        return {"alive": False, "pid": None, "uptime_s": 0.0}
    except Exception:
        return {"alive": False, "pid": None, "uptime_s": 0.0}


def _brain_enabled() -> bool:
    try:
        data = json.loads(BRAIN_HISTORY.read_text())
        if not data:
            return True
        last = data[-1]
        content = last.get("content", "")
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
                return "_brain_disabled" not in parsed
            except (json.JSONDecodeError, TypeError):
                return True
        if isinstance(content, dict):
            return "_brain_disabled" not in content
        return True
    except Exception:
        return True


def _read_json_safe(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _attach_media_to_pending(data: dict) -> dict:
    """Inject media fields from monitor_pending.json or pending_media.json into data dict.
    Mirrors the media-attachment logic in sol_commands.py:_do_generate()."""
    PENDING_MEDIA = BOT_DIR / "pending_media.json"

    # 1. Check monitor_pending.json for media
    if MONITOR_PENDING.exists():
        try:
            mp_data = json.loads(MONITOR_PENDING.read_text())
            paths = mp_data.get("media_paths") or (
                [mp_data["media_path"]] if mp_data.get("media_path") else []
            )
            paths = [p for p in paths if Path(p).exists()]
            if paths:
                data["media_paths"] = paths
                data["media_path"] = paths[0]
                data["media_type"] = mp_data.get("media_type", "photo")
                print(f"[generate] attached {len(paths)} media file(s) from monitor_pending", flush=True)
        except Exception as e:
            print(f"[generate] monitor_pending media read error: {e}", flush=True)

    # 2. If no monitor media, check pending_media.json (owner-sent via Telegram)
    if not data.get("media_paths") and PENDING_MEDIA.exists():
        try:
            pm = json.loads(PENDING_MEDIA.read_text())
            local_path = pm.get("local_path", "")
            if local_path and Path(local_path).exists():
                data["media_paths"] = [local_path]
                data["media_path"] = local_path
                data["media_type"] = pm.get("media_type", "photo")
                data["tg_media_url"] = pm.get("tg_file_url", "")
                PENDING_MEDIA.unlink(missing_ok=True)
                print(f"[generate] attached owner media from pending_media.json: {local_path}", flush=True)
        except Exception as e:
            print(f"[generate] pending_media.json read error: {e}", flush=True)

    return data


def _append_publish_log(platform: str, success: bool, tweet: str,
                        tweet_id: str = None, tweet_type: str = None,
                        has_media: bool = False, media_type: str = "") -> None:
    """Append a publish event to logs/publish_log.json (same format as sol_commands.py)."""
    try:
        entry = {
            "published_at": datetime.now().isoformat(),
            "platform": platform,
            "success": success,
            "tweet_id": tweet_id,
            "text_preview": (tweet or "")[:80],
            "tweet_type": tweet_type,
            "char_count": len(tweet) if tweet else 0,
            "has_media": has_media,
            "media_type": media_type,
        }
        if PUBLISH_LOG.exists():
            try:
                history = json.loads(PUBLISH_LOG.read_text())
                if not isinstance(history, list):
                    history = []
            except Exception:
                history = []
        else:
            PUBLISH_LOG.parent.mkdir(parents=True, exist_ok=True)
            history = []
        history.append(entry)
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=str(PUBLISH_LOG.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(history, ensure_ascii=False, indent=2))
            os.replace(tmp, str(PUBLISH_LOG))
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
    except Exception as e:
        logger.warning(f"[publish_log] Failed to append: {e}")


def _tail_file(path: Path, n: int) -> list[str]:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            buf = bytearray()
            pos = size
            lines_found = 0
            block = 4096
            while pos > 0 and lines_found <= n:
                read_size = min(block, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                buf = bytearray(chunk) + buf
                lines_found = buf.count(b"\n")
            text = buf.decode("utf-8", errors="replace")
            all_lines = text.splitlines()
            return all_lines[-n:] if len(all_lines) >= n else all_lines
    except Exception:
        return []


# ─── ROUTES ──────────────────────────────────────────────────────────────────
@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if username == DASHBOARD_USER and password == DASHBOARD_PASS:
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE, SESSION_TOKEN,
            httponly=True, samesite="lax", max_age=86400 * 7,
        )
        return response
    return RedirectResponse(url="/?error=1", status_code=303)


@app.get("/manifest.json")
async def manifest():
    return FileResponse(str(BOT_DIR / "static" / "manifest.json"), media_type="application/manifest+json")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return HTMLResponse(content=TEMPLATE_PATH.read_text(encoding="utf-8"))


@app.get("/api/csrf-token")
async def api_csrf_token():
    """Return the CSRF token for this session. Dashboard JS fetches this on load."""
    return JSONResponse({"csrf_token": CSRF_TOKEN})


def _require_csrf(request: Request) -> None:
    """Raise 403 if the X-CSRF-Token header is missing or invalid.
    Skips check for requests from localhost (e.g. nginx proxy, curl tests)."""
    client_host = request.client.host if request.client else ""
    if client_host in ("127.0.0.1", "::1", "localhost"):
        return
    token = request.headers.get("X-CSRF-Token", "")
    if not secrets.compare_digest(token, CSRF_TOKEN):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


@app.get("/api/status")
async def api_status():
    sol_state = _read_pid("sol_commands")
    mon_state = _read_pid("monitor")

    # brain
    brain_on = _brain_enabled()

    # publish log
    last_publish = None
    posts_today = 0
    log_data = _read_json_safe(PUBLISH_LOG)
    if isinstance(log_data, list) and log_data:
        last_publish = log_data[-1]
        today = datetime.now(timezone.utc).date()
        for entry in log_data:
            try:
                pub_date = datetime.fromisoformat(entry["published_at"]).date()
                if pub_date == today:
                    posts_today += 1
            except Exception:
                pass

    # recent posts (last 10)
    recent_posts = []
    if isinstance(log_data, list):
        recent_posts = log_data[-10:][::-1]  # newest first

    return {
        "sol_commands": sol_state,
        "monitor": mon_state,
        "brain_enabled": brain_on,
        "last_publish": last_publish,
        "posts_today": posts_today,
        "recent_posts": recent_posts,
        "generator_available": _GENERATOR_AVAILABLE,
    }


@app.get("/api/pending")
async def api_pending():
    tweet   = _read_json_safe(PENDING_TWEET)
    combo   = _read_json_safe(PENDING_COMBO)
    monitor = _read_json_safe(MONITOR_PENDING)

    # scheduled: pending_sched_N.json
    scheduled = []
    for path in sorted(BOT_DIR.glob("pending_sched_*.json")):
        m = re.search(r"pending_sched_(\d+)\.json$", path.name)
        if m:
            content = _read_json_safe(path)
            if content is not None:
                scheduled.append({"n": int(m.group(1)), "content": content})

    return {
        "tweet": tweet,
        "combo": combo,
        "monitor": monitor,
        "scheduled": scheduled,
    }


class PublishPayload(BaseModel):
    platform: str  # "both" | "x" | "threads"
    source: str    # "pending" | "combo"


class GeneratePayload(BaseModel):
    headline: str
    tweet_type: str = "RANDOM"   # WIRE|ANALISIS|DEBATE|CONEXION|RANDOM
    manual: bool = True
    model_override: Optional[str] = None  # null|"auto"|"haiku"|"sonnet"


class MixedPayload(BaseModel):
    headline: str


class RegeneratePayload(BaseModel):
    instruction: Optional[str] = None
    tweet_type: Optional[str] = None


class MonitorActionPayload(BaseModel):
    action: str                   # "generate" | "mixed" | "original" | "ignore"
    tweet_type: Optional[str] = None

class ReplyPayload(BaseModel):
    input_type: str               # "text"; URL fetch was removed with X support
    content: str                  # pasted text
    model_override: Optional[str] = None  # "haiku"|"sonnet"|null

class ReplyRegenPayload(BaseModel):
    move: str
    original_tweet: str
    model_override: Optional[str] = None


@app.post("/api/publish")
async def api_publish(request: Request, payload: PublishPayload):
    _require_csrf(request)
    platform = payload.platform.lower()
    source   = payload.source.lower()

    if platform not in ("both", "x", "threads"):
        raise HTTPException(400, "platform must be both|x|threads")
    if source not in ("pending", "combo"):
        raise HTTPException(400, "source must be pending|combo")

    source_file = PENDING_TWEET if source == "pending" else PENDING_COMBO
    data = _read_json_safe(source_file)
    if not data:
        raise HTTPException(404, f"No pending file found at {source_file.name}")

    # ── Extract tweet text (combo: "tweet" field; pending: "tweet"/"text") ──
    if source == "combo":
        tweet_text = data.get("tweet") or data.get("wire") or ""
        if not tweet_text:
            raise HTTPException(422, "pending_combo.json missing tweet field")
    else:
        tweet_text = data.get("tweet") or data.get("text") or ""
        if not tweet_text:
            raise HTTPException(422, "Source file has no tweet text")

    # Build media args — use --video for .mp4, --image otherwise
    media_args: list[str] = []
    media_type = data.get("media_type", "photo")
    media_paths = data.get("media_paths") or []
    if not media_paths and data.get("media_path"):
        media_paths = [data["media_path"]]

    if media_paths:
        valid_paths = [p for p in media_paths if p and Path(p).exists()]
        missing = [p for p in media_paths if p and not Path(p).exists()]
        if missing:
            print(f"[publish/{source}] WARNING: {len(missing)} media file(s) missing, publishing text-only: {missing}", flush=True)
        media_paths = valid_paths

    if media_type == "video" and media_paths:
        mp = media_paths[0]
        if mp and Path(mp).exists():
            media_args += ["--video", mp]
            print(f"[publish/{source}] media flag=--video path={mp}", flush=True)
        elif mp:
            print(f"[publish/{source}] video path not found: {mp}", flush=True)
    elif media_paths:
        valid = [p for p in media_paths if p and Path(p).exists()]
        if valid:
            # threads_publisher.py expects repeated --image flags for carousels.
            for mp in valid:
                media_args += ["--image", mp]
            print(f"[publish/{source}] media flag=--image count={len(valid)}", flush=True)
        for mp in media_paths:
            if mp and not Path(mp).exists():
                print(f"[publish/{source}] media path not found: {mp}", flush=True)

    # X publishing is retired: route every publish request to Threads only.
    requested_platform = platform
    platform = "threads"
    cmd = ["python3", "threads_publisher.py", "--quiet"] + media_args + [tweet_text]
    print(f"[publish/{source}] requested_platform={requested_platform} routed_platform=threads cmd={cmd[:6]}", flush=True)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(BOT_DIR),
            timeout=360 if media_type == "video" else 120,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Publish timed out — check Threads token, media URL, or video processing")
    stdout = result.stdout + result.stderr
    if result.returncode != 0:
        print(f"[publish/{source}] Threads publish failed rc={result.returncode}: {stdout[-1200:]}", flush=True)

    # Parse Threads result.
    threads_success = result.returncode == 0
    threads_post_id = None

    m_t = re.search(r"\[SUCCESS\].*?ID:\s*(\S+)", stdout)
    if m_t:
        threads_post_id = m_t.group(1)

    # Write to publish_log.json so Recent Posts panel updates.
    tweet_type_log = data.get("tweet_type")
    _has_media = bool(media_args)
    _append_publish_log("threads", threads_success, tweet_text, tweet_id=threads_post_id,
                        tweet_type=tweet_type_log, has_media=_has_media, media_type=media_type)

    wire_repost_warning = bool(re.match(r'^(just in|🚨)', tweet_text, re.IGNORECASE))

    return {
        "threads_success": threads_success,
        "threads_post_id": threads_post_id,
        "stdout": stdout[-2000:],  # last 2000 chars for debugging
        "wire_repost_warning": wire_repost_warning,
    }


@app.post("/api/generate")
async def api_generate(request: Request, payload: GeneratePayload):
    _require_csrf(request)
    if not _GENERATOR_AVAILABLE:
        raise HTTPException(503, f"generator.py unavailable: {_GENERATOR_ERROR}")

    tweet_type = None if payload.tweet_type == "RANDOM" else payload.tweet_type
    headline_dict = {"title": payload.headline, "summary": payload.headline, "source": "manual"}

    loop = asyncio.get_event_loop()
    tweet_text = await loop.run_in_executor(
        None, lambda: _generate_tweet(headline_dict, tweet_type=tweet_type, manual=payload.manual,
                                       model_override=payload.model_override)
    )

    data = {
        "tweet": tweet_text,
        "headline": headline_dict,
        "tweet_type": tweet_type or "RANDOM",
        "generated_at": datetime.now().isoformat(),
    }
    data = _attach_media_to_pending(data)
    _save_json(PENDING_TWEET, data)

    mo = (payload.model_override or "").lower().strip()
    if mo and mo not in ("auto",):
        model_display = mo
    else:
        raw = _get_model(tweet_type or "ANALISIS", manual=True)
        model_display = raw.split("/")[-1].replace("claude-", "").replace("-20251001", "")

    return {
        "tweet": tweet_text,
        "tweet_type": tweet_type or "RANDOM",
        "char_count": len(tweet_text),
        "model_used": model_display,
        "has_media": bool(data.get("media_paths")),
    }


@app.post("/api/mixed")
async def api_mixed(request: Request, payload: MixedPayload):
    _require_csrf(request)
    if not _GENERATOR_AVAILABLE:
        raise HTTPException(503, f"generator.py unavailable: {_GENERATOR_ERROR}")

    headline_dict = {"title": payload.headline, "summary": payload.headline, "source": "manual"}
    loop = asyncio.get_event_loop()

    # Generate single combined post: headline + blank line + analysis
    tweet = await loop.run_in_executor(
        None, lambda: _generate_combinada_tweet(headline_dict, manual=True)
    )

    data = {
        "tweet": tweet,
        "headline": headline_dict,
        "generated_at": datetime.now().isoformat(),
        "tweet_type": "COMBINADA",
    }
    # Carry media from pending_tweet.json or monitor_pending.json (mirrors cmd_mixed in sol_commands.py)
    for src in (PENDING_TWEET, MONITOR_PENDING):
        if src.exists():
            try:
                src_data = json.loads(src.read_text())
                paths = src_data.get("media_paths") or (
                    [src_data["media_path"]] if src_data.get("media_path") else []
                )
                paths = [p for p in paths if Path(p).exists()]
                if paths:
                    data["media_paths"] = paths
                    data["media_path"] = paths[0]
                    data["media_type"] = src_data.get("media_type", "photo")
                    print(f"[mixed] attached {len(paths)} media file(s) from {src.name}", flush=True)
                    break
            except Exception:
                pass
    _save_json(PENDING_COMBO, data)

    return {
        "tweet": tweet,
        "char_count": len(tweet),
        "has_media": bool(data.get("media_paths")),
    }


@app.post("/api/generate/regenerate")
async def api_regenerate(payload: RegeneratePayload):
    if not _GENERATOR_AVAILABLE:
        raise HTTPException(503, f"generator.py unavailable: {_GENERATOR_ERROR}")

    existing = _read_json_safe(PENDING_TWEET)
    if not existing:
        raise HTTPException(404, "No pending_tweet.json to regenerate from")

    headline_dict = existing.get("headline") or {
        "title": existing.get("tweet", ""), "summary": "", "source": "manual"
    }
    if payload.instruction:
        headline_dict = dict(headline_dict, instruction=payload.instruction)

    tweet_type = payload.tweet_type or existing.get("tweet_type") or None
    if tweet_type == "RANDOM":
        tweet_type = None

    loop = asyncio.get_event_loop()
    tweet_text = await loop.run_in_executor(
        None, lambda: _generate_tweet(headline_dict, tweet_type=tweet_type, manual=True)
    )

    data = {**existing, "tweet": tweet_text, "tweet_type": tweet_type or "RANDOM",
            "generated_at": datetime.now().isoformat()}
    _save_json(PENDING_TWEET, data)

    return {
        "tweet": tweet_text,
        "tweet_type": tweet_type or "RANDOM",
        "char_count": len(tweet_text),
        "model_used": None,
    }


@app.get("/api/validate")
async def api_validate():
    data = _read_json_safe(PENDING_TWEET)
    if not data or not data.get("tweet"):
        # Fall back to pending_combo.json
        data = _read_json_safe(PENDING_COMBO)
    if not data or not data.get("tweet"):
        return {"empty": True}

    tweet = data["tweet"]
    char_count = len(tweet)

    # 1. Char count
    if char_count > 280:
        char_status = "error"
    elif char_count > 270:
        char_status = "warning"
    else:
        char_status = "ok"

    # 2. AI-isms
    AI_ISMS = [
        "it's worth noting", "it is worth noting", "importantly", "crucially",
        "it's important to", "as an ai", "i cannot", "delve", "underscore",
        "tapestry", "nuanced", "multifaceted", "in conclusion", "to summarize",
        "in summary", "furthermore", "moreover", "nevertheless",
        "it goes without saying", "needless to say", "at the end of the day",
        "game changer", "paradigm shift",
    ]
    tweet_lower = tweet.lower()
    found_isms = [p for p in AI_ISMS if p in tweet_lower]

    # 3. Rhetorical move
    move = "none"
    if re.search(r'\d+[%$]|\$\d+|\d+\s*(billion|million|trillion)', tweet, re.I):
        move = "Cold Fact Drop"
    elif re.search(r'\bnobody\b|\bno one\b|\bunnoticed\b|\boverlooked\b|\bignored\b', tweet, re.I):
        move = "Nobody Noticed"
    elif re.search(r'\b(19|20)\d{2}\b|\bagain\b|\bbefore\b|\blast time\b', tweet, re.I):
        move = "History Rhyme"
    elif re.search(r'\d+\s*[+\-*/]\s*\d+|\d+%.*vs|\bcompared to\b|\bversus\b', tweet, re.I):
        move = "Math Check"
    else:
        sentences = [s.strip() for s in re.split(r'[.!?]+', tweet) if s.strip()]
        if len(sentences) >= 2:
            move = "Buried Lede (possible)"

    # 4. Moralizing
    MORAL_WORDS = [
        "should", "must", "need to", "have to", "ought to",
        "it's wrong", "it's right", "shameful", "disgraceful",
        "unacceptable", "outrageous",
    ]
    found_moral = [p for p in MORAL_WORDS if p in tweet_lower]

    # Overall
    if char_status == "error" or found_isms or found_moral:
        overall = "fail"
    elif char_status == "warning" or move == "none":
        overall = "warning"
    else:
        overall = "pass"

    return {
        "empty": False,
        "char_count": char_count,
        "char_status": char_status,
        "ai_isms": found_isms,
        "rhetorical_move": move,
        "moralizing": found_moral,
        "overall": overall,
    }


@app.post("/api/reset")
async def api_reset(request: Request):
    _require_csrf(request)
    cleared = []
    for path in BOT_DIR.glob("pending_*.json"):
        try:
            path.unlink()
            cleared.append(path.name)
        except Exception:
            pass
    return {"cleared": sorted(cleared)}


@app.get("/api/logs/tail")
async def api_logs_tail(file: str = "sol_commands", lines: int = 50):
    if file not in LOG_ALLOWLIST:
        raise HTTPException(400, f"file must be one of: {', '.join(sorted(LOG_ALLOWLIST))}")
    lines = max(1, min(lines, 500))
    log_path = LOGS_DIR / f"{file}.log"
    tail = _tail_file(log_path, lines)
    return {"lines": tail, "file": file, "count": len(tail)}


@app.get("/api/logs/stream")
async def api_logs_stream(request: Request):
    log_path = LOGS_DIR / "sol_commands.log"

    async def event_generator():
        try:
            with open(log_path, "r", errors="replace") as f:
                # Send last 8 lines immediately on connect
                all_lines = f.readlines()
                for line in all_lines[-8:]:
                    yield {"data": line.rstrip("\n")}
                # Then tail new lines from end of file
                f.seek(0, 2)
                while True:
                    if await request.is_disconnected():
                        break
                    line = f.readline()
                    if line:
                        yield {"data": line.rstrip("\n")}
                    else:
                        await asyncio.sleep(0.5)
        except FileNotFoundError:
            yield {"data": f"[error] Log file not found: {log_path}"}

    return EventSourceResponse(event_generator())


@app.get("/api/brain/history")
async def api_brain_history():
    raw = _read_json_safe(BRAIN_HISTORY)
    if not raw or not isinstance(raw, list):
        return {"turns": [], "total": 0}

    turns = []
    for i, entry in enumerate(raw):
        role = entry.get("role", "unknown")
        content = entry.get("content", "")
        action = confidence = instruction = None
        try:
            parsed = json.loads(content)
            action = parsed.get("action")
            confidence = parsed.get("confidence")
            instruction = parsed.get("instruction")
        except Exception:
            pass
        turns.append({
            "index": i,
            "role": role,
            "action": action,
            "confidence": confidence,
            "instruction": instruction or "",
            "raw_content": content[:120],
        })

    last20 = turns[-20:][::-1]  # newest first
    return {"turns": last20, "total": len(raw)}


@app.delete("/api/scheduler/{n}")
async def api_scheduler_delete(request: Request, n: int):
    _require_csrf(request)
    if not (1 <= n <= 99):
        raise HTTPException(400, "n must be between 1 and 99")
    sched_file = BOT_DIR / f"pending_sched_{n}.json"
    if sched_file.exists():
        sched_file.unlink()
        return {"deleted": True}
    return {"deleted": False}


# ─── MONITOR FEED ─────────────────────────────────────────────────────────────

def _read_queue() -> list:
    """Load monitor_queue.json under filelock; return [] on missing/corrupt."""
    with FileLock(str(MONITOR_QUEUE_LOCK), timeout=5):
        try:
            raw = MONITOR_QUEUE.read_text()
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []


def _write_queue(queue: list) -> None:
    """Write monitor_queue.json atomically under filelock."""
    with FileLock(str(MONITOR_QUEUE_LOCK), timeout=5):
        tmp = MONITOR_QUEUE.parent / f".tmp_{MONITOR_QUEUE.name}"
        tmp.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, MONITOR_QUEUE)


@app.get("/api/monitor/queue")
async def api_monitor_queue():
    """Return full queue, oldest first."""
    return JSONResponse(_read_queue())


@app.get("/api/monitor/current")
async def api_monitor_current():
    """Return oldest unprocessed entry, or null."""
    queue = _read_queue()
    return JSONResponse(queue[0] if queue else None)


ALLOWED_MEDIA_EXT = {".jpg", ".jpeg", ".png", ".mp4", ".gif"}

@app.get("/media/{filename}")
async def serve_media(filename: str):
    filename = urllib.parse.unquote(filename)  # normalize %2F and similar encoding
    if Path(filename).suffix.lower() not in ALLOWED_MEDIA_EXT:
        raise HTTPException(status_code=403, detail="File type not allowed")
    path = (MEDIA_DIR / filename).resolve()
    if not str(path).startswith(str(MEDIA_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


@app.post("/api/monitor/action/{alert_id}")
async def api_monitor_action(request: Request, alert_id: str, payload: MonitorActionPayload):
    _require_csrf(request)
    queue = _read_queue()
    entry = next((e for e in queue if e.get("id") == alert_id), None)
    if entry is None:
        raise HTTPException(404, f"Alert {alert_id} not found in queue")

    headline_dict = entry.get("headline", {})
    action = payload.action.lower()

    try:
        if action == "generate":
            loop = asyncio.get_event_loop()
            tweet = await loop.run_in_executor(
                None, lambda: _generate_tweet(headline_dict, tweet_type=payload.tweet_type, manual=True)
            )
            data = {
                "tweet": tweet,
                "tweet_type": payload.tweet_type or "WIRE",
                "generated_at": datetime.now().isoformat(),
                "headline": headline_dict,
            }
            # Copy media from queue entry
            media_paths = entry.get("media_paths") or ([entry["media_path"]] if entry.get("media_path") else [])
            media_paths = [p for p in media_paths if Path(p).exists()]
            if media_paths:
                data["media_paths"] = media_paths
                data["media_path"] = media_paths[0]
                data["media_type"] = entry.get("media_type", "photo")
                print(f"[monitor/generate] attached {len(media_paths)} media file(s)", flush=True)
            _save_json(PENDING_TWEET, data)

        elif action == "mixed":
            loop = asyncio.get_event_loop()
            tweet = await loop.run_in_executor(
                None, lambda: _generate_combinada_tweet(headline_dict, manual=True)
            )
            data = {
                "tweet": tweet,
                "tweet_type": "COMBINADA",
                "generated_at": datetime.now().isoformat(),
                "headline": headline_dict,
            }
            # Copy media from queue entry
            media_paths = entry.get("media_paths") or ([entry["media_path"]] if entry.get("media_path") else [])
            media_paths = [p for p in media_paths if Path(p).exists()]
            if media_paths:
                data["media_paths"] = media_paths
                data["media_path"] = media_paths[0]
                data["media_type"] = entry.get("media_type", "photo")
                print(f"[monitor/mixed] attached {len(media_paths)} media file(s)", flush=True)
            _save_json(PENDING_COMBO, data)

        elif action == "original":
            tweet = headline_dict.get("title", "")
            if not tweet:
                raise HTTPException(422, "headline.title is empty")
            media_args: list[str] = []
            media_paths = entry.get("media_paths") or []
            if not media_paths and entry.get("media_path"):
                media_paths = [entry["media_path"]]
            for mp in media_paths:
                if mp and Path(mp).exists():
                    flag = "--video" if Path(mp).suffix.lower() == ".mp4" else "--image"
                    media_args += [flag, mp]
                    print(f"[monitor/original] media flag={flag} path={mp}", flush=True)
                elif mp:
                    print(f"[monitor/original] media path not found: {mp}", flush=True)
            cmd = ["python3", "threads_publisher.py", "--quiet"] + media_args + [tweet]
            print(f"[monitor/original] running Threads-only command: {cmd[:6]}", flush=True)
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BOT_DIR), timeout=360 if entry.get("media_type") == "video" else 120)
            stdout = result.stdout + result.stderr
            if result.stdout:
                print(f"[monitor/original] stdout: {result.stdout[:400]}", flush=True)
            if result.stderr:
                print(f"[monitor/original] stderr: {result.stderr[:400]}", flush=True)
            m_t = re.search(r"\[SUCCESS\].*?ID:\s*(\S+)", stdout)
            _append_publish_log("threads", result.returncode == 0, tweet,
                                tweet_id=m_t.group(1) if m_t else None,
                                has_media=bool(media_args), media_type=entry.get("media_type", "photo"))
            if result.returncode != 0:
                # Remove from queue even on publish failure so it doesn't get stuck
                queue = [e for e in queue if e.get("id") != alert_id]
                _write_queue(queue)
                return {"success": False, "action": action, "tweet": tweet, "remaining": len(queue)}

        elif action == "ignore":
            tweet = None

        else:
            raise HTTPException(400, f"Unknown action: {action}")

        # Remove processed entry from queue
        queue = [e for e in queue if e.get("id") != alert_id]
        _write_queue(queue)
        return {"success": True, "action": action, "tweet": tweet if action != "ignore" else None, "remaining": len(queue)}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ─── THREADS ANALYTICS ────────────────────────────────────────────────────────

@app.get("/api/threads/analytics")
async def api_threads_analytics(limit: int = 20):
    limit = max(1, min(limit, 50))
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "threads_analytics", BOT_DIR / "threads_analytics.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return JSONResponse(mod.fetch_posts(limit=limit))
    except Exception as e:
        return JSONResponse({"error": str(e), "posts": [], "count": 0})


# ─── REPLY GENERATOR ──────────────────────────────────────────────────────────

def _reply_get_client():
    """Returns (client, is_openrouter, model_id) for reply generation."""
    or_key = os.getenv("OPENROUTER_API_KEY")
    if or_key and _OPENAI_AVAILABLE:
        return _OpenAI(api_key=or_key, base_url=OPENROUTER_BASE), True
    return None, False


def _reply_get_context():
    """Load sol_posts_today and headlines_in_queue for reply generation."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sol_posts = []
    try:
        entries = json.loads(CONTEXT_JSON.read_text())
        for e in entries:
            if str(e.get("timestamp", "")).startswith(today):
                txt = e.get("tweet_text", "").strip()
                if txt:
                    sol_posts.append(txt)
        sol_posts = sol_posts[-10:]
    except Exception:
        pass

    headlines = []
    try:
        queue = json.loads(MONITOR_QUEUE.read_text())
        for e in queue[:5]:
            title = e.get("headline", {}).get("title", "")
            if title:
                headlines.append(f"- {title}")
    except Exception:
        pass

    return "\n".join(sol_posts) or "(none)", "\n".join(headlines) or "(none)"


def _reply_call(system: str, user_msg: str, model_id: str) -> str:
    client, is_or = _reply_get_client()
    if is_or and client:
        resp = client.chat.completions.create(
            model=model_id,
            max_tokens=800,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_msg},
            ],
        )
        return resp.choices[0].message.content.strip()
    # Fallback: direct Anthropic SDK
    import anthropic as _ant
    ant = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    resp = ant.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    return resp.content[0].text.strip()


def _reply_parse(raw: str) -> dict:
    """Strip code fences and parse JSON from model output."""
    cleaned = re.sub(r"```json\s*|```\s*", "", raw).strip()
    return json.loads(cleaned)


@app.post("/api/replies/generate")
async def api_replies_generate(payload: ReplyPayload):
    # Resolve original text. URL fetching via X/Twitter API was removed with X support.
    if payload.input_type == "url":
        return JSONResponse({"error": "URL fetch is disabled. Paste the text instead."}, status_code=422)
    else:
        tweet_text = payload.content.strip()
        if not tweet_text:
            return JSONResponse({"error": "content is empty"}, status_code=422)

    # Load system prompt and user template
    try:
        system_prompt = REPLY_PROMPT.read_text()
        user_template = REPLY_USER_TMPL.read_text()
    except FileNotFoundError as e:
        raise HTTPException(500, f"Prompt file missing: {e}")

    sol_posts_today, headlines_in_queue = _reply_get_context()
    user_msg = (user_template
                .replace("{{original_tweet}}", tweet_text)
                .replace("{{sol_posts_today}}", sol_posts_today)
                .replace("{{headlines_in_queue}}", headlines_in_queue))

    # Select model
    override = (payload.model_override or "").lower()
    model_id = REPLY_MODEL_MAP.get(override, REPLY_DEFAULT_MODEL)

    try:
        raw = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _reply_call(system_prompt, user_msg, model_id)
        )
        parsed = _reply_parse(raw)
    except Exception as e:
        raise HTTPException(500, f"Reply generation failed: {e}")

    sol_count = len([l for l in sol_posts_today.split("\n") if l.strip()])
    hl_count  = len([l for l in headlines_in_queue.split("\n") if l.strip() and l != "(none)"])
    return JSONResponse({
        "replies":        parsed.get("replies", []),
        "context_used":   parsed.get("context_used", []),
        "original_tweet": tweet_text,
        "model_used":     model_id,
        "sol_count":      sol_count,
        "hl_count":       hl_count,
    })


@app.post("/api/replies/regenerate-one")
async def api_replies_regenerate_one(payload: ReplyRegenPayload):
    try:
        system_prompt = REPLY_PROMPT.read_text()
    except FileNotFoundError as e:
        raise HTTPException(500, f"Prompt file missing: {e}")

    sol_posts_today, headlines_in_queue = _reply_get_context()
    user_msg = (
        f"ORIGINAL_TWEET:\n{payload.original_tweet}\n\n"
        f"SOL_POSTS_TODAY:\n{sol_posts_today}\n\n"
        f"HEADLINES_IN_QUEUE:\n{headlines_in_queue}\n\n"
        f"Regenerate ONLY the '{payload.move}' reply. "
        f"Output a single JSON object: {{\"move\": \"{payload.move}\", \"text\": \"...\", \"char_count\": N}}"
    )

    override = (payload.model_override or "").lower()
    model_id = REPLY_MODEL_MAP.get(override, REPLY_DEFAULT_MODEL)

    try:
        raw = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _reply_call(system_prompt, user_msg, model_id)
        )
        cleaned = re.sub(r"```json\s*|```\s*", "", raw).strip()
        parsed = json.loads(cleaned)
    except Exception as e:
        raise HTTPException(500, f"Regen failed: {e}")

    return JSONResponse(parsed)


# ─── SIGNALS ─────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/api/signals/gdelt")
async def signals_gdelt():
    global _gdelt_cache
    if not _GDELT_AVAILABLE:
        return JSONResponse({"error": "gdeltdoc not installed", "updated_at": _now_iso()})
    if _gdelt_cache["data"] and (time.time() - _gdelt_cache["ts"]) < 900:
        return JSONResponse(_gdelt_cache["data"])
    keywords = ["Iran Hormuz", "BRICS", "NATO", "China Taiwan", "oil price"]
    try:
        gd = GdeltDoc()
        topics = []
        for kw in keywords:
            try:
                f = GdeltFilters(timespan="2h", num_records=10, keyword=kw)
                df = gd.article_search(f)
                if df is not None and not df.empty:
                    articles = []
                    for _, row in df.iterrows():
                        articles.append({
                            "title": str(row.get("title", "")),
                            "url": str(row.get("url", "")),
                            "domain": str(row.get("domain", "")),
                            "seendate": str(row.get("seendate", "")),
                        })
                    topics.append({"keyword": kw, "articles": articles, "article_count": len(articles)})
                else:
                    topics.append({"keyword": kw, "articles": [], "article_count": 0})
            except Exception:
                topics.append({"keyword": kw, "articles": [], "article_count": 0})
        result = {"updated_at": _now_iso(), "topics": topics}
        _gdelt_cache = {"data": result, "ts": time.time()}
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e), "updated_at": _now_iso()})


@app.get("/api/signals/polymarket")
async def signals_polymarket():
    global _polymarket_cache
    if _polymarket_cache["data"] and (time.time() - _polymarket_cache["ts"]) < 300:
        return JSONResponse(_polymarket_cache["data"])
    if _requests is None:
        return JSONResponse({"error": "requests not available", "updated_at": _now_iso()})
    keywords = ["iran", "israel", "nato", "china", "russia", "ukraine", "oil", "fed", "bitcoin", "brics"]
    try:
        resp = _requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={"active": "true", "closed": "false", "limit": 50},
            headers={"User-Agent": "sol-dashboard/1.0"},
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
        markets = []
        for m in raw:
            question = m.get("question") or m.get("title") or ""
            if not any(re.search(r'\b' + kw + r'\b', question, re.IGNORECASE) for kw in keywords):
                continue
            # probability_yes from outcomePrices (JSON string) or lastTradePrice
            prob = None
            outcome_prices = m.get("outcomePrices")
            if outcome_prices:
                try:
                    parsed_prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                    prob = float(parsed_prices[0])
                except Exception:
                    pass
            if prob is None:
                try:
                    prob = float(m.get("lastTradePrice") or m.get("price") or 0.5)
                except Exception:
                    prob = 0.5
            # volume
            try:
                volume = float(m.get("volume") or m.get("volumeNum") or 0)
            except Exception:
                volume = 0.0
            # url
            slug = m.get("slug") or m.get("id") or ""
            url = m.get("url") or f"https://polymarket.com/event/{slug}"
            markets.append({
                "id": str(m.get("id", "")),
                "question": question,
                "probability_yes": round(prob, 4),
                "volume": volume,
                "url": url,
            })
        markets.sort(key=lambda x: x["volume"], reverse=True)
        result = {"updated_at": _now_iso(), "markets": markets[:10]}
        _polymarket_cache = {"data": result, "ts": time.time()}
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e), "updated_at": _now_iso()})


@app.get("/api/signals/markets")
async def signals_markets():
    global _markets_cache
    if _markets_cache["data"] and (time.time() - _markets_cache["ts"]) < 300:
        return JSONResponse(_markets_cache["data"])
    if not _YFINANCE_AVAILABLE:
        return JSONResponse({"error": "yfinance not installed", "updated_at": _now_iso()})
    tickers = [
        ("BTC-USD",   "BTC"),
        ("CL=F",      "WTI OIL"),
        ("^GSPC",     "S&P 500"),
        ("DX-Y.NYB",  "DXY"),
        ("GC=F",      "GOLD"),
    ]
    try:
        assets = []
        for ticker_sym, name in tickers:
            try:
                t = _yfinance.Ticker(ticker_sym)
                info = t.fast_info
                price = float(info.last_price or 0)
                prev_close = float(info.previous_close or info.regular_market_previous_close or price)
                if prev_close and prev_close != 0:
                    change_pct = (price - prev_close) / prev_close * 100
                else:
                    change_pct = 0.0
                if change_pct > 0.1:
                    direction = "up"
                elif change_pct < -0.1:
                    direction = "down"
                else:
                    direction = "flat"
                assets.append({
                    "symbol": ticker_sym,
                    "name": name,
                    "price": round(price, 4),
                    "change_pct": round(change_pct, 2),
                    "direction": direction,
                })
            except Exception as e:
                assets.append({
                    "symbol": ticker_sym,
                    "name": name,
                    "price": None,
                    "change_pct": None,
                    "direction": "flat",
                    "error": str(e),
                })
        result = {"updated_at": _now_iso(), "assets": assets}
        _markets_cache = {"data": result, "ts": time.time()}
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e), "updated_at": _now_iso()})


@app.get("/api/signals")
async def signals_combined():
    gdelt = await signals_gdelt()
    poly = await signals_polymarket()
    mkts = await signals_markets()
    return JSONResponse({
        "gdelt": json.loads(gdelt.body),
        "polymarket": json.loads(poly.body),
        "markets": json.loads(mkts.body),
    })


# ─── N8N INTEGRATION ENDPOINTS ──────────────────────────────────────────────

GDELT_BASELINE     = BOT_DIR / "gdelt_baseline.json"
GDELT_BASELINE_LOCK = BOT_DIR / "gdelt_baseline.lock"


@app.get("/api/n8n/gdelt-baseline")
async def n8n_gdelt_baseline_get():
    try:
        if GDELT_BASELINE.exists():
            return JSONResponse(json.loads(GDELT_BASELINE.read_text()))
        return JSONResponse({})
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/n8n/gdelt-baseline")
async def n8n_gdelt_baseline_post(request: Request):
    """Partial update: {keyword, count, set_alert: bool}.
    Updates only the named keyword. set_alert=true stamps last_alert=now."""
    try:
        data = await request.json()
        keyword  = data["keyword"]
        count    = int(data["count"])
        set_alert = bool(data.get("set_alert", False))
        lock = FileLock(str(GDELT_BASELINE_LOCK))
        with lock:
            if GDELT_BASELINE.exists():
                baseline = json.loads(GDELT_BASELINE.read_text())
            else:
                baseline = {}
            entry = baseline.get(keyword, {"count": 0, "last_alert": None})
            entry["count"] = count
            if set_alert:
                entry["last_alert"] = datetime.now(timezone.utc).isoformat()
            baseline[keyword] = entry
            tmp = GDELT_BASELINE.with_suffix(".tmp")
            tmp.write_text(json.dumps(baseline, indent=2))
            tmp.rename(GDELT_BASELINE)
        return JSONResponse({"saved": True, "keyword": keyword, "count": count})
    except Exception as e:
        raise HTTPException(500, str(e))
