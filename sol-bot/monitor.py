from telethon import TelegramClient, events
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from filelock import FileLock

from config import BASE_DIR, get_list_env, get_required_env
from ingestion_utils import append_or_merge_queue, normalize_ingest_payload
from telegram_client import send_message, send_photo, send_video, send_media_group

API_ID = get_required_env("TELEGRAM_API_ID", cast=int)
API_HASH = get_required_env("TELEGRAM_API_HASH")
CANALES = [int(channel_id) for channel_id in get_list_env("TELEGRAM_SOURCE_CHANNEL_IDS")]

# Human-readable names for Telegram channel IDs (add more as needed)
CHANNEL_NAMES = {
    "-1002006131201": "BRICSNews",
    "-1001556054753": "WatcherGuru",
    "-1003706885368": "Sol Test",
}

MONITOR_PENDING_FILE = BASE_DIR / "monitor_pending.json"
MONITOR_QUEUE_FILE   = BASE_DIR / "monitor_queue.json"
MONITOR_QUEUE_LOCK   = BASE_DIR / "monitor_queue.lock"
MEDIA_DIR = BASE_DIR / "media"
MEDIA_DIR.mkdir(exist_ok=True)
MONITOR_QUEUE_MAX = int(os.getenv("MONITOR_QUEUE_MAX", "100") or "100")

# Videos longer than this will be skipped
MAX_VIDEO_DURATION_SEC = 60

# Buffer for grouped (album) messages: grouped_id -> list of events
group_buffer: dict = {}
group_tasks: dict = {}


def _atomic_write_json(path: Path, data) -> None:
    """Write JSON atomically using a temp file + os.replace to prevent corruption."""
    tmp = path.parent / f".tmp_{path.name}"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def get_video_duration(path: str) -> float:
    """Return video duration in seconds using OpenCV. Returns 0 on error."""
    try:
        import cv2
        cap = cv2.VideoCapture(path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        if fps > 0:
            return frames / fps
    except Exception:
        pass
    return 0


async def _download_media(event, ts: int, index: int = 0):
    """Download media from a Telethon message event. Returns (path, type) or (None, None)."""
    if event.message.photo:
        dest = str(MEDIA_DIR / f"monitor_{ts}_{index}.jpg")
        await event.message.download_media(dest)
        if os.path.exists(dest):
            print(f"Photo saved: {dest}")
            return dest, "photo"

    elif event.message.video or event.message.gif:
        dest = str(MEDIA_DIR / f"monitor_{ts}_{index}.mp4")
        await event.message.download_media(dest)
        if os.path.exists(dest):
            duration = get_video_duration(dest)
            if duration > MAX_VIDEO_DURATION_SEC:
                print(f"Video too long ({duration:.0f}s > {MAX_VIDEO_DURATION_SEC}s), skipping")
                os.remove(dest)
            else:
                print(f"Video saved: {dest} ({duration:.0f}s)")
                return dest, "video"

    return None, None


def send_monitor_keyboard(caption: str):
    """Send monitor alert text + action buttons as an inline keyboard message."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    payload = {
        "chat_id": chat_id,
        "text": caption,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "⚡ Generate",  "callback_data": "mon_generate"},
                    {"text": "🧩 Mixed",     "callback_data": "mon_mixed"},
                    {"text": "📰 Original",  "callback_data": "mon_original"},
                ],
                [
                    {"text": "🚫 Ignorar", "callback_data": "mon_ignore"},
                ],
            ]
        },
    }
    import urllib.request as _req
    r = _req.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _req.urlopen(r, timeout=35):
            pass
    except Exception as exc:
        print(f"send_monitor_keyboard error: {exc}")


async def _forward_to_bot(mensaje: str, canal: str, media_paths: list, media_type: str | None):
    """Save monitor_pending.json and send notification to the Sol bot chat."""
    display = mensaje if mensaje else "[Solo media — sin texto]"
    caption = f"\U0001f4e1 @{canal}:\n\n{display}"

    source_name = CHANNEL_NAMES.get(str(canal), canal)

    headline = {
        "title": mensaje,
        "summary": mensaje,
        "source": source_name,
        "url": "",
    }
    pending_data = {
        "headline": headline,
        "received_at": datetime.now().isoformat(),
        "source_name": source_name,
        "source_type": "telegram",
    }

    if media_paths:
        pending_data["media_paths"] = media_paths          # list of all paths
        pending_data["media_path"] = media_paths[0]        # first (backward compat)
        pending_data["media_type"] = media_type or "photo"

    # ── Backwards compat: keep single-entry file for sol_commands.py ──────────
    _atomic_write_json(MONITOR_PENDING_FILE, pending_data)

    # ── Append to persistent queue (filelock prevents TOCTOU race) ────────────
    with FileLock(str(MONITOR_QUEUE_LOCK), timeout=5):
        try:
            queue = json.loads(MONITOR_QUEUE_FILE.read_text()) if MONITOR_QUEUE_FILE.exists() else []
        except (json.JSONDecodeError, OSError) as e:
            print(f"[monitor] Corrupt queue file, resetting: {e}")
            queue = []

        entry = normalize_ingest_payload(
            {
                "id": str(uuid.uuid4()),
                "source_name": source_name,
                "source_type": "telegram",
                "received_at": pending_data["received_at"],
                "headline": headline,
                "media_paths": media_paths,
                "media_path": media_paths[0] if media_paths else "",
                "media_type": media_type or "",
                "metadata": {"credibility": "medium", "priority": "normal"},
            }
        )
        queue, _stored, status = append_or_merge_queue(queue, entry, max_items=MONITOR_QUEUE_MAX)
        print(f"[monitor] queued status={status} source={source_name} score={_stored.get('score')}", flush=True)

        _atomic_write_json(MONITOR_QUEUE_FILE, queue)

    # Send media (if any) then always follow with the action keyboard
    if len(media_paths) > 1 and media_type == "photo":
        send_media_group(media_paths, caption)
    elif media_paths and media_type == "photo":
        send_photo(media_paths[0], caption)
    elif media_paths and media_type == "video":
        send_video(media_paths[0], caption)

    send_monitor_keyboard(caption if not media_paths else "¿Qué hago con esta noticia?")
    print(f"Enviada: {mensaje[:80]}")


async def process_group(grouped_id: int):
    """Wait 2s for all album messages to arrive, then process together."""
    await asyncio.sleep(2.0)

    events_list = group_buffer.pop(grouped_id, [])
    group_tasks.pop(grouped_id, None)

    if not events_list:
        return

    canal = getattr(events_list[0].chat, "username", None) or str(events_list[0].chat_id)

    # Use the longest text found across all messages in the group
    mensaje = ""
    for ev in events_list:
        txt = ev.message.message or ""
        if len(txt) > len(mensaje):
            mensaje = txt

    if not mensaje and not any(ev.message.media for ev in events_list):
        return
    if mensaje and len(mensaje) < 5:
        print(f"[FILTRADO grupo] {canal}: {repr(mensaje[:50])}")
        return

    ts = int(datetime.now().timestamp())
    media_paths = []
    media_type = None

    for i, ev in enumerate(events_list):
        path, mtype = await _download_media(ev, ts, i)
        if path:
            media_paths.append(path)
            if media_type is None:
                media_type = mtype  # first media type wins (photo or video)

    await _forward_to_bot(mensaje, canal, media_paths, media_type)


async def process_single(event):
    """Handle a single (non-album) message."""
    mensaje = event.message.message or ""
    canal = getattr(event.chat, "username", None) or str(event.chat_id)

    if not mensaje and not event.message.media:
        return
    if mensaje and len(mensaje) < 5:
        print(f"[FILTRADO] {canal}: {repr(mensaje[:50])}")
        return

    ts = int(datetime.now().timestamp())
    media_paths = []
    media_type = None

    path, mtype = await _download_media(event, ts, 0)
    if path:
        media_paths.append(path)
        media_type = mtype

    await _forward_to_bot(mensaje, canal, media_paths, media_type)


client = TelegramClient(str(BASE_DIR / "monitor_session"), API_ID, API_HASH)


@client.on(events.NewMessage(chats=CANALES))
async def handler(event):
    try:
        grouped_id = event.message.grouped_id

        if grouped_id:
            # Album message — buffer and wait for siblings
            if grouped_id not in group_buffer:
                group_buffer[grouped_id] = []
            group_buffer[grouped_id].append(event)

            # Cancel previous timer and restart
            if grouped_id in group_tasks:
                group_tasks[grouped_id].cancel()

            loop = asyncio.get_event_loop()
            task = loop.create_task(process_group(grouped_id))
            group_tasks[grouped_id] = task
        else:
            await process_single(event)

    except Exception as exc:
        print(f"Monitor handler error: {exc}")


async def main():
    MONITOR_PID_FILE = Path(__file__).parent / "monitor.pid"
    if MONITOR_PID_FILE.exists():
        try:
            pid = int(MONITOR_PID_FILE.read_text().strip())
            os.kill(pid, 0)
            print(f"Monitor already running (PID {pid}), exiting.")
            sys.exit(0)
        except (ProcessLookupError, ValueError):
            pass  # stale pid file — overwrite
    MONITOR_PID_FILE.write_text(str(os.getpid()))
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("ERROR: Sesion no valida")
            return
        print("Monitoreando canales configurados...")
        await client.run_until_disconnected()
    finally:
        MONITOR_PID_FILE.unlink(missing_ok=True)


asyncio.run(main())
