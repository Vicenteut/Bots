from telethon import TelegramClient, events
import asyncio
import urllib.request
import json

API_ID = 31328352
API_HASH = "644e51daa95d310cdff2a25565185eae"
BOT_TOKEN = "8603788822:AAHkhXtvyFBqYSA-hglE0aXr_0rAZhFaWxM"
CHAT_ID = 6054558214

CANALES = [
    -1002006131201,
    -1001556054753
]

client = TelegramClient("/root/x-bot/monitor_session", API_ID, API_HASH)

def enviar_telegram(texto):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": CHAT_ID, "text": texto}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req)

@client.on(events.NewMessage(chats=CANALES))
async def handler(event):
    mensaje = event.message.message
    if not mensaje or len(mensaje) < 20:
        return
    canal = event.chat.username or "canal"
    texto = f"📡 @{canal}:\n\n{mensaje}\n\n¿Genero un tweet?"
    enviar_telegram(texto)
    print(f"Enviada: {mensaje[:80]}")

async def main():
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Sesión no válida")
        return
    print("Monitoreando WatcherGuru y BRICSNews...")
    await client.run_until_disconnected()

asyncio.run(main())
