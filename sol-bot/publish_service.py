"""
publish_service.py — Lógica compartida entre sol_commands.py y sol_dashboard_api.py.

Extrae las funciones duplicadas para que un fix llegue a ambos procesos.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from json_store import append_to_json_list
from topic_utils import classify_topic

logger = logging.getLogger(__name__)

PUBLISH_LOG = Path("/root/x-bot/logs/publish_log.json")


def extract_threads_result(output: str) -> dict:
    """Parse the structured [THREADS_RESULT] line emitted by threads_publisher.py."""
    for line in (output or "").splitlines():
        if line.startswith("[THREADS_RESULT]"):
            try:
                raw = line.split("]", 1)[1].strip()
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
    return {}


def media_kind(media_type: str, media_paths: list) -> str:
    if media_type == "video" and media_paths:
        return "video"
    if len(media_paths) > 1:
        return "carousel"
    if len(media_paths) == 1:
        return "image"
    return "text"


def classify_publish_result(output: str, returncode: int, media_kind_str: str) -> dict:
    """Classify the output of a threads_publisher.py subprocess call into a structured result."""
    parsed = extract_threads_result(output)
    post_id = parsed.get("post_id") if parsed else None
    success = returncode == 0 and bool(post_id or parsed.get("success"))
    category = parsed.get("category") if parsed else None
    message = parsed.get("message") if parsed else None

    if not success and not category:
        lower = (output or "").lower()
        if "csrf" in lower or "token" in lower or "permission" in lower or "unauthorized" in lower:
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
        message = interesting[-1] if interesting else (lines[-1] if lines else "Threads publish failed")

    return {
        "success": success,
        "post_id": post_id,
        "status": "OK" if success else (category or "FAILED"),
        "error_category": None if success else category,
        "error_message": None if success else message,
        "stage": parsed.get("stage") if parsed else None,
        "http_code": parsed.get("http_code") if parsed else None,
        "fbtrace_id": parsed.get("fbtrace_id") if parsed else None,
        "public_media_urls": parsed.get("media_urls") if isinstance(parsed.get("media_urls"), list) else [],
        "media_kind": parsed.get("media_type") or media_kind_str,
    }


def append_publish_log(
    platform: str,
    success: bool,
    tweet: str,
    tweet_id: str = None,
    tweet_type: str = None,
    model_used: str = None,
    has_media: bool = False,
    media_type: str = "text",
    media_count: int = 0,
    status: str = None,
    error_category: str = None,
    error_message: str = None,
    fbtrace_id: str = None,
    public_media_urls: list = None,
) -> None:
    """Append one publish event to logs/publish_log.json. Never raises."""
    try:
        entry = {
            "published_at": datetime.now().isoformat(),
            "platform": platform,
            "success": success,
            "tweet_id": tweet_id,
            "text_preview": (tweet or "")[:80],
            "tweet_type": tweet_type,
            "topic_tag": classify_topic(tweet),
            "model_used": model_used,
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
        append_to_json_list(PUBLISH_LOG, entry)
    except Exception as e:
        logger.error(f"[publish_log] Failed to append entry: {e}")
