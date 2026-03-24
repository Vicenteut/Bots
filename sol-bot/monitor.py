from telethon import TelegramClient, events
import asyncio

from config import BASE_DIR, get_list_env, get_required_env
from telegram_client import send_message

API_ID = get_required_env("TELEGRAM_API_ID", cast=int)
API_HASH = get_required_env("TELEGRAM_API_HASH")
CANALES = [int(channel_id) for channel_id in get_list_env("TELEGRAM_SOURCE_CHANNEL_IDS")]

client = TelegramClient(str(BASE_DIR / "monitor_session"), API_ID, API_HASH)


def enviar_telegram(texto):
    try:
        send_message(texto)
    except Exception as exc:
        print(f"Telegram send failed: {exc}")


@client.on(events.NewMessage(chats=CANALES))
async def handler(event):
    try:
        mensaje = event.message.message
        if not mensaje or len(mensaje) < 20:
            return
        canal = event.chat.username or "canal"
        texto = f"\U0001f4e1 @{canal}:\n\n{mensaje}\n\n\u00bfGenero un tweet?"
        enviar_telegram(texto)
        print(f"Enviada: {mensaje[:80]}")
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
