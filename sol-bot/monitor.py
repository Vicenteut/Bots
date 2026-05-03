from telethon import TelegramClient, events
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from config import BASE_DIR, get_list_env, get_required_env
from telegram_client import send_message, send_photo, send_video, send_media_group

API_ID = get_required_env("TELEGRAM_API_ID", cast=int)
API_HASH = get_required_env("TELEGRAM_API_HASH")
CANALES = [int(channel_id) for channel_id in get_list_env("TELEGRAM_SOURCE_CHANNEL_IDS")]

MONITOR_PENDING_FILE = BASE_DIR / "monitor_pending.json"
MEDIA_DIR = BASE_DIR / "media"
MEDIA_DIR.mkdir(exist_ok=True)

# Videos longer than this will be skipped
MAX_VIDEO_DURATION_SEC = 60

# Buffer for grouped (album) messages: grouped_id -> list of events
group_buffer: dict = {}
group_tasks: dict = {}


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


async def _forward_to_bot(mensaje: str, canal: str, media_paths: list, media_type: str | None):
    """Save monitor_pending.json and send notification to the Sol bot chat."""
    display = mensaje if mensaje else "[Solo media — sin texto]"
    caption = f"\U0001f4e1 @{canal}:\n\n{display}\n\n\u00bfGenero un tweet?"

    headline = {
        "title": mensaje,
        "summary": mensaje,
        "source": canal,
        "url": "",
    }
    pending_data = {
        "headline": headline,
        "received_at": datetime.now().isoformat(),
    }

    if media_paths:
        pending_data["media_paths"] = media_paths          # list of all paths
        pending_data["media_path"] = media_paths[0]        # first (backward compat)
        pending_data["media_type"] = media_type or "photo"

    MONITOR_PENDING_FILE.write_text(
        json.dumps(pending_data, ensure_ascii=False, indent=2)
    )

    # Send to bot
    if len(media_paths) > 1 and media_type == "photo":
        send_media_group(media_paths, caption)
    elif media_paths and media_type == "photo":
        send_photo(media_paths[0], caption)
    elif media_paths and media_type == "video":
        send_video(media_paths[0], caption)
    else:
        send_message(caption)

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
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Sesion no valida")
        return
    print("Monitoreando canales configurados...")
    await client.run_until_disconnected()


asyncio.run(main())
