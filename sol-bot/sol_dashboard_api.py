"""
Sol Dashboard API — Tier 1
FastAPI + htmx operational dashboard, port 8502
"""
import asyncio
import base64
import glob
import hashlib
import json
import os
import re
import secrets
import subprocess
import urllib.parse
import urllib.request
from filelock import FileLock
try:
    from openai import OpenAI as _OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psutil
from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from starlette.middleware.base import BaseHTTPMiddleware
from ingestion_utils import append_or_merge_queue, normalize_ingest_payload, priority_rank, score_alert_details
from recommendation_engine import get_learning_summary, recommend_for_alert
from topic_utils import classify_topic

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
MONITOR_QUEUE_MAX  = int(os.getenv("MONITOR_QUEUE_MAX", "100") or "100")
MEDIA_DIR          = BOT_DIR / "media"
SOURCE_CONFIG      = BOT_DIR / "source_config.json"
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

THREADS_POST_MAX_CHARS = 500
THREADS_POST_WARN_CHARS = 460
REMOTE_MONITOR_IMAGE_MAX_BYTES = int(os.getenv("REMOTE_MONITOR_IMAGE_MAX_BYTES", str(5 * 1024 * 1024)) or str(5 * 1024 * 1024))
REMOTE_MONITOR_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

# ─── SIGNALS CACHE ───────────────────────────────────────────────────────────
_gdelt_cache: dict = {"data": None, "ts": 0.0}
_polymarket_cache: dict = {"data": None, "ts": 0.0}
_markets_cache: dict = {"data": None, "ts": 0.0}

# ─── AUTH ────────────────────────────────────────────────────────────────────
DASHBOARD_USER = os.getenv("DASHBOARD_USER", "sol")
DASHBOARD_PASSWORD_HASH = (os.getenv("DASHBOARD_PASSWORD_HASH") or "").strip().lower()
INGEST_API_TOKEN = (os.getenv("INGEST_API_TOKEN") or "").strip()
INGEST_RATE_LIMIT_PER_MIN = int(os.getenv("INGEST_RATE_LIMIT_PER_MIN", "60") or "60")
if not DASHBOARD_PASSWORD_HASH or DASHBOARD_PASSWORD_HASH == "change_me_to_sha256_hash":
    raise RuntimeError("DASHBOARD_PASSWORD_HASH must be set in the environment")
if not re.fullmatch(r"[0-9a-f]{64}", DASHBOARD_PASSWORD_HASH):
    raise RuntimeError("DASHBOARD_PASSWORD_HASH must be a 64-character SHA-256 hex digest")

SESSION_COOKIE = "sol_session"
SESSION_MAX_AGE = 86400 * 7
# Cryptographically random session token — generated at startup, never derived from credentials
SESSION_TOKEN  = secrets.token_hex(32)
# CSRF token — separate random value, sent to browser and echoed back on state-changing requests
CSRF_TOKEN     = secrets.token_hex(32)
_ingest_rate_events: list[float] = []


def _check_credentials(user: str, pwd: str) -> bool:
    pwd_hash = hashlib.sha256(pwd.encode("utf-8")).hexdigest()
    return (
        secrets.compare_digest(user, DASHBOARD_USER)
        and secrets.compare_digest(pwd_hash, DASHBOARD_PASSWORD_HASH)
    )


def _check_ingest_auth_header(auth: str) -> bool:
    if not INGEST_API_TOKEN:
        return False
    prefix = "Bearer "
    if not auth.startswith(prefix):
        return False
    token = auth[len(prefix):].strip()
    return secrets.compare_digest(token, INGEST_API_TOKEN)


def _require_ingest_auth(request: Request) -> None:
    if not INGEST_API_TOKEN:
        raise HTTPException(503, "INGEST_API_TOKEN is not configured")
    if not _check_ingest_auth_header(request.headers.get("Authorization", "")):
        raise HTTPException(401, "Invalid ingest token")


def _require_ingest_rate_limit() -> None:
    now = time.time()
    window_start = now - 60
    while _ingest_rate_events and _ingest_rate_events[0] < window_start:
        _ingest_rate_events.pop(0)
    if len(_ingest_rate_events) >= INGEST_RATE_LIMIT_PER_MIN:
        raise HTTPException(429, "Ingest rate limit exceeded")
    _ingest_rate_events.append(now)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 0. Allow login POST, manifest, and static assets through unauthenticated
        path = request.url.path
        if (path == "/login" and request.method == "POST") or \
           path == "/manifest.json" or path.startswith("/static/") or \
           path.startswith("/media/"):
            return await call_next(request)

        if path == "/api/monitor/ingest" and request.method == "POST":
            if _check_ingest_auth_header(request.headers.get("Authorization", "")):
                return await call_next(request)
            return Response(
                content="Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="Sol Ingest"'},
            )

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
                        httponly=True, samesite="lax", max_age=SESSION_MAX_AGE,
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


def _monitored_services() -> list[dict]:
    names = [
        item.strip() for item in os.getenv(
            "SOL_MONITORED_SERVICES",
            "xbot-monitor,sol-commands,sol-dashboard,cloudflared,sol-threads-analytics.timer,sol-rss-fetcher.timer",
        ).split(",")
        if item.strip()
    ]
    services = []
    for name in names:
        try:
            active = subprocess.run(
                ["systemctl", "is-active", name],
                capture_output=True, text=True, timeout=2, check=False,
            ).stdout.strip()
        except Exception:
            active = "unknown"
        try:
            enabled = subprocess.run(
                ["systemctl", "is-enabled", name],
                capture_output=True, text=True, timeout=2, check=False,
            ).stdout.strip()
        except Exception:
            enabled = "unknown"
        services.append({
            "name": name,
            "active": active,
            "enabled": enabled,
            "ok": active in {"active", "inactive"} if name.endswith(".timer") else active == "active",
        })
    return services


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
    tmp = path.parent / f".tmp_{path.name}"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


_PRESERVE_PENDING_KEYS = {
    "media_paths", "media_path", "media_type", "headline", "source_alert_id", "source_name",
    "tweet_type", "metadata", "canonical_url", "source_type", "topic_tag", "topic_guess",
    "score", "priority_label", "credibility", "related_sources", "related_source_count",
}


def _preserve_pending_fields(existing: dict) -> dict:
    return {k: existing[k] for k in _PRESERVE_PENDING_KEYS if k in existing}


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
                        has_media: bool = False, media_type: str = "",
                        media_count: int = 0, status: str = None,
                        error_category: str = None, error_message: str = None,
                        fbtrace_id: str = None, public_media_urls: list[str] = None) -> None:
    """Append a publish event to logs/publish_log.json (same format as sol_commands.py)."""
    try:
        entry = {
            "published_at": datetime.now().isoformat(),
            "platform": platform,
            "success": success,
            "tweet_id": tweet_id,
            "text_preview": (tweet or "")[:80],
            "tweet_type": tweet_type,
            "topic_tag": classify_topic(tweet),
            "char_count": len(tweet) if tweet else 0,
            "has_media": has_media,
            "media_type": media_type,
            "media_count": media_count,
            "status": status or ("OK" if success else "FAILED"),
            "error_category": error_category,
            "error_message": (error_message or "")[:500] if error_message else None,
            "fbtrace_id": fbtrace_id,
            "public_media_urls": public_media_urls or [],
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


def _extract_threads_result(output: str) -> dict:
    """Parse the structured result emitted by threads_publisher.py."""
    result = {}
    for line in (output or "").splitlines():
        if line.startswith("[THREADS_RESULT]"):
            raw = line.split("]", 1)[1].strip()
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    result = parsed
            except Exception:
                pass
    return result


def _classify_publish_result(output: str, returncode: int, media_kind: str) -> dict:
    parsed = _extract_threads_result(output)
    post_id = parsed.get("post_id") if parsed else None
    success = returncode == 0 and bool(post_id or parsed.get("success"))
    category = parsed.get("category") if parsed else None
    message = parsed.get("message") if parsed else None
    stage = parsed.get("stage") if parsed else None

    if not success and not category:
        lower = (output or "").lower()
        if "csrf" in lower:
            category = "AUTH_ERROR"
        elif "token" in lower or "permission" in lower or "unauthorized" in lower:
            category = "AUTH_ERROR"
        elif "content-type" in lower or "media url" in lower or "no valid image" in lower or "container failed" in lower:
            category = "MEDIA_ERROR"
        elif "timed out" in lower or "timeout" in lower:
            category = "TIMEOUT"
        elif "http error" in lower or "meta error" in lower or "fbtrace_id" in lower:
            category = "META_ERROR"
        else:
            category = "FAILED"

    if not message and not success:
        lines = [ln.strip() for ln in (output or "").splitlines() if ln.strip()]
        interesting = [ln for ln in lines if "[ERROR]" in ln or "[META ERROR]" in ln or "Container failed" in ln]
        message = (interesting[-1] if interesting else (lines[-1] if lines else "Threads publish failed"))

    status = "OK" if success else (category or "FAILED")
    return {
        "success": success,
        "post_id": post_id,
        "status": status,
        "error_category": None if success else category,
        "error_message": None if success else message,
        "stage": stage,
        "http_code": parsed.get("http_code") if parsed else None,
        "fbtrace_id": parsed.get("fbtrace_id") if parsed else None,
        "public_media_urls": parsed.get("media_urls") if isinstance(parsed.get("media_urls"), list) else [],
        "media_kind": parsed.get("media_type") or media_kind,
    }


def _media_kind_from_args(media_type: str, media_paths: list[str]) -> str:
    if media_type == "video" and media_paths:
        return "video"
    if len(media_paths) > 1:
        return "carousel"
    if len(media_paths) == 1:
        return "image"
    return "text"


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
    if _check_credentials(username, password):
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE, SESSION_TOKEN,
            httponly=True, samesite="lax", max_age=SESSION_MAX_AGE,
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
    """Raise 403 if the X-CSRF-Token header is missing or invalid."""
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
        "system_services": _monitored_services(),
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


class ComboSavePayload(BaseModel):
    tweet: str


class RegeneratePayload(BaseModel):
    instruction: Optional[str] = None
    tweet_type: Optional[str] = None


class MonitorActionPayload(BaseModel):
    action: str                   # "generate" | "mixed" | "recommend" | "original" | "ignore"
    tweet_type: Optional[str] = None
    edited_title: Optional[str] = None
    edited_summary: Optional[str] = None


class MonitorBulkPayload(BaseModel):
    ids: list[str]


class MonitorSavePayload(BaseModel):
    edited_title: str
    edited_summary: Optional[str] = None


class MonitorIngestHeadline(BaseModel):
    title: str
    summary: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None


class MonitorIngestPayload(BaseModel):
    external_id: Optional[str] = None
    received_at: Optional[str] = None
    published_at: Optional[str] = None
    source_name: str
    source_type: str = "webhook"
    canonical_url: Optional[str] = None
    url: Optional[str] = None
    headline: MonitorIngestHeadline
    media_urls: list[str] = Field(default_factory=list)
    media_paths: list[str] = Field(default_factory=list)
    media_path: Optional[str] = None
    media_type: Optional[str] = None
    language: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

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
    if len(tweet_text) > THREADS_POST_MAX_CHARS:
        raise HTTPException(422, f"Threads post is {len(tweet_text)} chars; max is {THREADS_POST_MAX_CHARS}")

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
            raise HTTPException(422, f"Media file missing: {missing[0]}")
        media_paths = valid_paths
    media_kind = _media_kind_from_args(media_type, media_paths)

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

    # Legacy platform selectors are ignored: route every publish request to Threads only.
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
        _append_publish_log("threads", False, tweet_text, tweet_type=data.get("tweet_type"),
                            has_media=bool(media_args), media_type=media_kind,
                            media_count=len(media_paths), status="TIMEOUT",
                            error_category="TIMEOUT",
                            error_message="Publish timed out — check Threads token, media URL, or video processing")
        raise HTTPException(504, "Publish timed out — check Threads token, media URL, or video processing")
    stdout = result.stdout + result.stderr
    if result.returncode != 0:
        print(f"[publish/{source}] Threads publish failed rc={result.returncode}: {stdout[-1200:]}", flush=True)

    parsed_result = _classify_publish_result(stdout, result.returncode, media_kind)
    threads_success = parsed_result["success"]
    threads_post_id = parsed_result["post_id"]
    if not threads_post_id:
        m_t = re.search(r"\[SUCCESS\].*?ID:\s*(\S+)", stdout)
        if m_t:
            threads_post_id = m_t.group(1)
            threads_success = result.returncode == 0
            if threads_success:
                parsed_result["status"] = "OK"
                parsed_result["error_category"] = None
                parsed_result["error_message"] = None

    # Write to publish_log.json so Recent Posts panel updates.
    tweet_type_log = data.get("tweet_type")
    _has_media = bool(media_args)
    _append_publish_log("threads", threads_success, tweet_text, tweet_id=threads_post_id,
                        tweet_type=tweet_type_log, has_media=_has_media, media_type=media_kind,
                        media_count=len(media_paths), status=parsed_result["status"],
                        error_category=parsed_result["error_category"],
                        error_message=parsed_result["error_message"],
                        fbtrace_id=parsed_result["fbtrace_id"],
                        public_media_urls=parsed_result["public_media_urls"])

    wire_repost_warning = bool(re.match(r'^(just in|🚨)', tweet_text, re.IGNORECASE))

    return {
        "threads_success": threads_success,
        "threads_post_id": threads_post_id,
        "status": "OK" if threads_success else parsed_result["status"],
        "error_category": parsed_result["error_category"],
        "error_message": parsed_result["error_message"],
        "stage": parsed_result["stage"],
        "http_code": parsed_result["http_code"],
        "fbtrace_id": parsed_result["fbtrace_id"],
        "media_type": media_kind,
        "media_count": len(media_paths),
        "public_media_urls": parsed_result["public_media_urls"],
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
async def api_regenerate(request: Request, payload: RegeneratePayload):
    _require_csrf(request)
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


@app.post("/api/pending/combo/save")
async def api_pending_combo_save(request: Request, payload: ComboSavePayload):
    _require_csrf(request)
    existing = _read_json_safe(PENDING_COMBO)
    if not existing:
        raise HTTPException(404, "No pending_combo.json to save")

    tweet = (payload.tweet or "").strip()
    if not tweet:
        raise HTTPException(422, "Combo text is empty")
    if len(tweet) > THREADS_POST_MAX_CHARS:
        raise HTTPException(422, f"Threads post is {len(tweet)} chars; max is {THREADS_POST_MAX_CHARS}")

    data = {**existing, "tweet": tweet, "edited_at": datetime.now().isoformat()}
    _save_json(PENDING_COMBO, data)
    return {"ok": True, "pending_combo": data, "char_count": len(tweet)}


@app.post("/api/pending/combo/regenerate")
async def api_pending_combo_regenerate(request: Request, payload: RegeneratePayload):
    _require_csrf(request)
    if not _GENERATOR_AVAILABLE:
        raise HTTPException(503, f"generator.py unavailable: {_GENERATOR_ERROR}")

    existing = _read_json_safe(PENDING_COMBO)
    if not existing:
        raise HTTPException(404, "No pending_combo.json to regenerate")

    headline_dict = existing.get("headline") or {
        "title": existing.get("tweet", ""), "summary": existing.get("tweet", ""), "source": "manual"
    }
    if payload.instruction:
        headline_dict = dict(headline_dict, instruction=payload.instruction)

    loop = asyncio.get_event_loop()
    tweet = await loop.run_in_executor(
        None, lambda: _generate_combinada_tweet(headline_dict, manual=True)
    )
    if len(tweet) > THREADS_POST_MAX_CHARS:
        raise HTTPException(422, f"Generated combo is {len(tweet)} chars; max is {THREADS_POST_MAX_CHARS}")

    preserved = _preserve_pending_fields(existing)
    data = {
        **preserved,
        "tweet": tweet,
        "headline": headline_dict,
        "generated_at": datetime.now().isoformat(),
        "tweet_type": "COMBINADA",
    }
    _save_json(PENDING_COMBO, data)
    return {"ok": True, "pending_combo": data, "char_count": len(tweet)}


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
    if char_count > THREADS_POST_MAX_CHARS:
        char_status = "error"
    elif char_count > THREADS_POST_WARN_CHARS:
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
        "char_limit": THREADS_POST_MAX_CHARS,
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


def _read_source_config() -> dict:
    try:
        data = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"sources": []}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"sources": []}


def _append_or_merge_monitor_entry(entry: dict) -> tuple[dict, str, int]:
    """Append an ingested alert or merge it into an existing dedup group."""
    with FileLock(str(MONITOR_QUEUE_LOCK), timeout=5):
        try:
            data = json.loads(MONITOR_QUEUE.read_text(encoding="utf-8")) if MONITOR_QUEUE.exists() else []
            queue = data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            queue = []
        queue, stored, status = append_or_merge_queue(queue, entry, max_items=MONITOR_QUEUE_MAX)
        tmp = MONITOR_QUEUE.parent / f".tmp_{MONITOR_QUEUE.name}"
        tmp.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, MONITOR_QUEUE)
    return stored, status, len(queue)


def _entry_media_paths(entry: dict) -> list[str]:
    paths = entry.get("media_paths") or ([entry["media_path"]] if entry.get("media_path") else [])
    return [p for p in paths if p]


def _valid_media_paths(entry: dict) -> list[str]:
    return [p for p in _entry_media_paths(entry) if Path(p).exists()]


def _remote_image_ext(url: str, content_type: str) -> str | None:
    content_type = (content_type or "").split(";", 1)[0].strip().lower()
    if content_type in REMOTE_MONITOR_IMAGE_TYPES:
        return REMOTE_MONITOR_IMAGE_TYPES[content_type]
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return None


def _should_download_remote_monitor_media(entry: dict) -> bool:
    score, label, _reasons = score_alert_details(entry)
    return label in {"high", "breaking"} or score >= 60


def _download_remote_monitor_image(entry: dict, label: str) -> str | None:
    """Download a remote RSS preview image when it is eligible for publishing.

    The inbox can preview remote `media_urls`, but Threads publishing needs a
    local file path. Keep this fallback conservative: high/breaking alerts only.
    """
    if not _should_download_remote_monitor_media(entry):
        return None
    urls = entry.get("media_urls") or []
    if not isinstance(urls, list) or not urls:
        return None

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    source_name = entry.get("source_name") or "monitor"
    external_id = entry.get("external_id") or entry.get("id") or ""
    for url in [u for u in urls if isinstance(u, str) and u.startswith(("http://", "https://"))]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sol-dashboard/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                content_type = resp.headers.get("Content-Type", "")
                ext = _remote_image_ext(url, content_type)
                if not ext:
                    print(f"[monitor/{label}] skipped remote media unsupported type={content_type} url={url}", flush=True)
                    continue
                declared_size = resp.headers.get("Content-Length")
                if declared_size and int(declared_size) > REMOTE_MONITOR_IMAGE_MAX_BYTES:
                    print(f"[monitor/{label}] skipped remote media too large size={declared_size} url={url}", flush=True)
                    continue
                data = resp.read(REMOTE_MONITOR_IMAGE_MAX_BYTES + 1)
                if len(data) > REMOTE_MONITOR_IMAGE_MAX_BYTES:
                    print(f"[monitor/{label}] skipped remote media over limit url={url}", flush=True)
                    continue
        except Exception as exc:
            print(f"[monitor/{label}] remote media download failed url={url}: {exc}", flush=True)
            continue

        slug = "".join(c.lower() if c.isalnum() else "_" for c in source_name)[:32].strip("_") or "monitor"
        digest = hashlib.sha1(f"{source_name}:{external_id}:{url}".encode("utf-8")).hexdigest()[:16]
        path = MEDIA_DIR / f"monitor_{slug}_{digest}{ext}"
        try:
            path.write_bytes(data)
        except Exception as exc:
            print(f"[monitor/{label}] remote media write failed path={path}: {exc}", flush=True)
            continue
        print(f"[monitor/{label}] downloaded remote media: {path}", flush=True)
        return str(path)
    return None


def _suggest_monitor_format(entry: dict) -> str:
    headline = entry.get("headline", {}) or {}
    text = f"{headline.get('title', '')}\n{headline.get('summary', '')}".strip()
    topic = classify_topic(text)
    low = text.lower()
    if topic in {"crypto", "mercados"} and len(text) >= 140:
        return "COMBINADA"
    if len(text) <= 140 or low.startswith(("just in", "breaking", "urgent")):
        return "WIRE"
    if topic == "geopolitica" and len(text) >= 180:
        return "ANALISIS"
    return "ANALISIS"


def _enrich_monitor_entry(entry: dict) -> dict:
    enriched = dict(entry)
    headline = dict(enriched.get("headline") or {})
    text = f"{headline.get('title', '')}\n{headline.get('summary', '')}".strip()
    paths = _entry_media_paths(enriched)
    received = enriched.get("received_at")
    age_seconds = None
    if received:
        try:
            dt = datetime.fromisoformat(received)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_seconds = max(0, int((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()))
        except Exception:
            age_seconds = None
    enriched["headline"] = headline
    enriched["source_name"] = enriched.get("source_name") or headline.get("source") or "Unknown"
    enriched["media_count"] = len(paths)
    enriched["has_media"] = bool(paths or enriched.get("media_urls"))
    enriched["age_seconds"] = age_seconds
    enriched["topic_guess"] = classify_topic(text)
    enriched["suggested_format"] = _suggest_monitor_format(enriched)
    enriched["editorial_recommendation"] = recommend_for_alert(enriched, fallback_format=enriched["suggested_format"])
    enriched["source_type"] = enriched.get("source_type") or "telegram"
    enriched["credibility"] = enriched.get("credibility") or "medium"
    enriched["priority"] = enriched.get("priority") or "normal"
    enriched["related_source_count"] = int(enriched.get("related_source_count") or 1)
    enriched["duplicate_count"] = int(enriched.get("duplicate_count") or 0)
    enriched["possible_duplicate"] = bool(enriched.get("possible_duplicate"))
    enriched["score"], enriched["priority_label"], enriched["score_reasons"] = score_alert_details(enriched)
    enriched["priority_rank"] = priority_rank(enriched["priority_label"])
    enriched["related_sources"] = enriched.get("related_sources") or [
        {
            "source_name": enriched["source_name"],
            "source_type": enriched["source_type"],
            "canonical_url": enriched.get("canonical_url") or headline.get("url", ""),
        }
    ]
    enriched["media_files"] = [
        {"path": p, "filename": Path(p).name, "exists": Path(p).exists()}
        for p in paths
    ]
    return enriched


def _monitor_sort_key(entry: dict) -> tuple:
    return (
        int(entry.get("priority_rank", priority_rank(entry.get("priority_label")))),
        -int(entry.get("score") or 0),
        (entry.get("source_name") or "").lower(),
        entry.get("received_at") or "",
    )


def _headline_from_payload(entry: dict, payload: MonitorActionPayload | MonitorSavePayload) -> dict:
    headline = dict(entry.get("headline") or {})
    if getattr(payload, "edited_title", None) is not None:
        headline["title"] = (payload.edited_title or "").strip()
    if getattr(payload, "edited_summary", None) is not None:
        headline["summary"] = (payload.edited_summary or "").strip()
    if not headline.get("summary"):
        headline["summary"] = headline.get("title", "")
    if entry.get("source_name"):
        headline["source"] = entry.get("source_name")
    return headline


def _attach_entry_media(data: dict, entry: dict, label: str) -> None:
    media_paths = _valid_media_paths(entry)
    if not media_paths:
        downloaded = _download_remote_monitor_image(entry, label)
        if downloaded:
            media_paths = [downloaded]
    if media_paths:
        data["media_paths"] = media_paths
        data["media_path"] = media_paths[0]
        data["media_type"] = entry.get("media_type", "photo")
        if not entry.get("media_type"):
            data["media_type"] = "photo"
        if entry.get("media_urls"):
            data["media_source_urls"] = entry.get("media_urls")
        print(f"[monitor/{label}] attached {len(media_paths)} media file(s)", flush=True)


@app.get("/api/monitor/queue")
async def api_monitor_queue():
    """Return enriched queue ordered by editorial priority bands."""
    enriched = [_enrich_monitor_entry(e) for e in _read_queue()]
    return JSONResponse(sorted(enriched, key=_monitor_sort_key))


@app.get("/api/recommendation/alert/{alert_id}")
async def api_alert_recommendation(alert_id: str):
    """Return the analytics-backed editorial recommendation for one alert."""
    entry = next((e for e in _read_queue() if e.get("id") == alert_id), None)
    if entry is None:
        raise HTTPException(404, f"Alert {alert_id} not found in queue")
    enriched = _enrich_monitor_entry(entry)
    return JSONResponse(enriched.get("editorial_recommendation") or {})


@app.get("/api/monitor/sources")
async def api_monitor_sources():
    """Return configured sources for dashboard filters and operations."""
    config = _read_source_config()
    sources = [
        {
            "name": s.get("name"),
            "type": s.get("type"),
            "enabled": bool(s.get("enabled")),
            "credibility": s.get("credibility", "medium"),
            "base_priority": s.get("base_priority", "normal"),
            "is_official": bool(s.get("is_official", False)),
            "redistributable": bool(s.get("redistributable", True)),
        }
        for s in config.get("sources", [])
        if isinstance(s, dict)
    ]
    return JSONResponse({"sources": sources})


@app.post("/api/monitor/ingest")
async def api_monitor_ingest(request: Request, payload: MonitorIngestPayload):
    """Private ingestion endpoint for n8n, RSS fetchers, APIs, and future sources."""
    _require_ingest_auth(request)
    _require_ingest_rate_limit()
    try:
        raw = payload.model_dump(exclude_none=True)
    except AttributeError:
        raw = payload.dict(exclude_none=True)
    entry = normalize_ingest_payload(raw)
    if not entry.get("headline", {}).get("title"):
        raise HTTPException(422, "headline.title is required")
    stored, status, remaining = _append_or_merge_monitor_entry(entry)
    enriched = _enrich_monitor_entry(stored)
    print(
        f"[monitor/ingest] status={status} source={enriched.get('source_name')} "
        f"type={enriched.get('source_type')} score={enriched.get('score')} "
        f"priority={enriched.get('priority_label')}",
        flush=True,
    )
    return {
        "success": True,
        "status": status,
        "id": stored.get("id"),
        "dedup_key": stored.get("dedup_key"),
        "score": enriched.get("score"),
        "priority_label": enriched.get("priority_label"),
        "related_source_count": enriched.get("related_source_count"),
        "remaining": remaining,
    }


@app.get("/api/monitor/current")
async def api_monitor_current():
    """Return oldest unprocessed entry, or null."""
    queue = _read_queue()
    return JSONResponse(_enrich_monitor_entry(queue[0]) if queue else None)


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


@app.post("/api/monitor/save/{alert_id}")
async def api_monitor_save(request: Request, alert_id: str, payload: MonitorSavePayload):
    _require_csrf(request)
    queue = _read_queue()
    changed = False
    for entry in queue:
        if entry.get("id") != alert_id:
            continue
        headline = dict(entry.get("headline") or {})
        title = payload.edited_title.strip()
        if not title:
            raise HTTPException(422, "edited_title is empty")
        headline["title"] = title
        headline["summary"] = (payload.edited_summary or title).strip()
        headline["source"] = entry.get("source_name") or headline.get("source", "manual")
        entry["headline"] = headline
        entry["source_name"] = entry.get("source_name") or headline.get("source")
        entry["edited_at"] = datetime.now().isoformat()
        changed = True
        break
    if not changed:
        raise HTTPException(404, f"Alert {alert_id} not found in queue")
    _write_queue(queue)
    return {"success": True, "alert": _enrich_monitor_entry(next(e for e in queue if e.get("id") == alert_id))}


@app.post("/api/monitor/bulk-ignore")
async def api_monitor_bulk_ignore(request: Request, payload: MonitorBulkPayload):
    _require_csrf(request)
    ids = {str(i) for i in payload.ids if str(i).strip()}
    if not ids:
        return {"success": True, "removed": 0, "remaining": len(_read_queue())}
    queue = _read_queue()
    before = len(queue)
    queue = [e for e in queue if e.get("id") not in ids]
    _write_queue(queue)
    removed = before - len(queue)
    print(f"[monitor/bulk-ignore] removed={removed} ids={list(ids)[:8]}", flush=True)
    return {"success": True, "removed": removed, "remaining": len(queue)}


@app.post("/api/monitor/action/{alert_id}")
async def api_monitor_action(request: Request, alert_id: str, payload: MonitorActionPayload):
    _require_csrf(request)
    queue = _read_queue()
    entry = next((e for e in queue if e.get("id") == alert_id), None)
    if entry is None:
        raise HTTPException(404, f"Alert {alert_id} not found in queue")

    action = payload.action.lower()
    headline_dict = _headline_from_payload(entry, payload)
    source_name = entry.get("source_name") or headline_dict.get("source", "Unknown")
    media_count = len(_entry_media_paths(entry))
    recommendation = None
    if action == "recommend":
        rec_entry = dict(entry)
        rec_entry["headline"] = headline_dict
        recommendation = recommend_for_alert(
            _enrich_monitor_entry(rec_entry),
            fallback_format=_suggest_monitor_format(rec_entry),
        )
        recommended_format = (recommendation.get("format") or _suggest_monitor_format(entry) or "ANALISIS").upper()
        action = "mixed" if recommended_format in {"COMBINADA", "MIXED"} else "generate"
        payload.tweet_type = "COMBINADA" if action == "mixed" else recommended_format

    try:
        if action == "generate":
            tweet_type = (payload.tweet_type or _suggest_monitor_format(entry) or "WIRE").upper()
            if tweet_type == "COMBINADA":
                tweet_type = "ANALISIS"
            loop = asyncio.get_event_loop()
            tweet = await loop.run_in_executor(
                None, lambda: _generate_tweet(headline_dict, tweet_type=tweet_type, manual=True)
            )
            data = {
                "tweet": tweet,
                "tweet_type": tweet_type,
                "generated_at": datetime.now().isoformat(),
                "headline": headline_dict,
                "source_alert_id": alert_id,
                "source_name": source_name,
            }
            _attach_entry_media(data, entry, "generate")
            _save_json(PENDING_TWEET, data)
            pending_target = "pending_tweet"

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
                "source_alert_id": alert_id,
                "source_name": source_name,
            }
            _attach_entry_media(data, entry, "mixed")
            _save_json(PENDING_COMBO, data)
            pending_target = "pending_combo"

        elif action == "original":
            tweet = headline_dict.get("title", "").strip()
            if not tweet:
                raise HTTPException(422, "headline.title is empty")
            data = {
                "tweet": tweet,
                "tweet_type": "ORIGINAL",
                "generated_at": datetime.now().isoformat(),
                "headline": headline_dict,
                "source_alert_id": alert_id,
                "source_name": source_name,
            }
            _attach_entry_media(data, entry, "original")
            _save_json(PENDING_TWEET, data)
            pending_target = "pending_tweet"

        elif action == "ignore":
            tweet = None
            pending_target = None

        else:
            raise HTTPException(400, f"Unknown action: {action}")

        queue = [e for e in queue if e.get("id") != alert_id]
        _write_queue(queue)
        print(
            f"[monitor/action] action={action} source={source_name} pending={pending_target} media_count={media_count}",
            flush=True,
        )
        return {
            "success": True,
            "action": action,
            "recommendation": recommendation,
            "tweet": tweet if action != "ignore" else None,
            "pending_target": pending_target,
            "remaining": len(queue),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ─── THREADS ANALYTICS ────────────────────────────────────────────────────────

@app.get("/api/threads/analytics")
async def api_threads_analytics(
    days: int = 7,
    limit: int = 20,
    sort: str = "date",
    format: Optional[str] = None,
    topic: Optional[str] = None,
    media: Optional[str] = None,
):
    days = max(1, min(days, 90))
    limit = max(1, min(limit, 50))
    sort = (sort or "date").strip().lower()
    if sort not in {"views", "likes", "replies", "comments", "engagement", "date", "total_engagement"}:
        sort = "date"
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "threads_analytics", BOT_DIR / "threads_analytics.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        data = mod.get_analytics(days=days, limit=limit, sort=sort, format=format, topic=topic, media=media)
        data["learning_summary"] = get_learning_summary(days=days)
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": str(e), "summary": {}, "recent_posts": []})


@app.post("/api/threads/analytics/sync")
async def api_threads_analytics_sync(request: Request, limit: int = 50):
    _require_csrf(request)
    limit = max(1, min(limit, 50))
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "threads_analytics", BOT_DIR / "threads_analytics.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return JSONResponse(mod.sync_posts(limit=limit))
    except Exception as e:
        return JSONResponse({"success": False, "count": 0, "error": str(e)})


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
async def api_replies_generate(request: Request, payload: ReplyPayload):
    _require_csrf(request)
    # Resolve original text. URL fetching was removed; paste source text instead.
    if payload.input_type == "url":
        return JSONResponse({"error": "URL fetch is disabled. Paste the text instead."}, status_code=422)
    else:
        post_text = payload.content.strip()
        if not post_text:
            return JSONResponse({"error": "content is empty"}, status_code=422)

    # Load system prompt and user template
    try:
        system_prompt = REPLY_PROMPT.read_text()
        user_template = REPLY_USER_TMPL.read_text()
    except FileNotFoundError as e:
        raise HTTPException(500, f"Prompt file missing: {e}")

    sol_posts_today, headlines_in_queue = _reply_get_context()
    user_msg = (user_template
                .replace("{{original_tweet}}", post_text)
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
        "original_tweet": post_text,
        "model_used":     model_id,
        "sol_count":      sol_count,
        "hl_count":       hl_count,
    })


@app.post("/api/replies/regenerate-one")
async def api_replies_regenerate_one(request: Request, payload: ReplyRegenPayload):
    _require_csrf(request)
    try:
        system_prompt = REPLY_PROMPT.read_text()
    except FileNotFoundError as e:
        raise HTTPException(500, f"Prompt file missing: {e}")

    sol_posts_today, headlines_in_queue = _reply_get_context()
    user_msg = (
        f"ORIGINAL_POST:\n{payload.original_tweet}\n\n"
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
    _require_csrf(request)
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
