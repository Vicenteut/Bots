#!/usr/bin/env python3
"""Reply suggestion generator for @napoleotics with humanization."""
import os
import random
import time
from datetime import datetime

import anthropic

from content_utils import sanitize_generated_text
from config import load_environment, get_required_env
from http_utils import retry_call
from telegram_client import send_message

load_environment()

REPLY_SYSTEM = """Eres el analista detras de @napoleotics. Genera UNA reply para un tweet de una cuenta grande.

TIPOS DE REPLY (se te indicara cual usar):
1. DATO_CONTRARIO - Aporta un dato que contradice o matiza el tweet original
2. CONEXION_MACRO - Conecta el tweet con un evento macro que nadie menciono
3. PREGUNTA_RETORICA - Pregunta que hace pensar y genera engagement
4. CONTEXTO_HISTORICO - Trae un paralelo historico relevante
5. OPERADOR - Dato de mercado/trading que complementa

REGLAS:
- Max 200 caracteres (replies cortos funcionan mejor)
- Sin hashtags
- Sin emojis (max 1 si es necesario)
- Tono: seguro pero no arrogante
- NUNCA empieces con "Interesante" o "Buen punto"
- Aporta VALOR, no halagues
- Escribe en espanol

ANTI-DETECCION IA:
- Varia longitud de oraciones
- Usa contracciones y lenguaje informal cuando sea natural
- Incluye opinion personal con friccion
- Escribe como humano que tiene prisa, no como ensayo academico"""

client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
get_required_env("TELEGRAM_BOT_TOKEN")
get_required_env("TELEGRAM_CHAT_ID")

def send_tg(text):
    try:
        send_message(text)
    except Exception as e:
        print('Telegram error: ' + str(e))


def generate_reply(account, tweet_text):
    reply_type = random.choice([
        'DATO_CONTRARIO', 'CONEXION_MACRO', 'PREGUNTA_RETORICA',
        'CONTEXTO_HISTORICO', 'OPERADOR'
    ])
    nl = chr(10)
    prompt = 'Cuenta: @' + account + nl
    prompt += 'Tweet: ' + tweet_text + nl
    prompt += 'Tipo: ' + reply_type + nl + nl
    prompt += 'Reply (solo texto):'

    response = retry_call(lambda: client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=100,
        system=REPLY_SYSTEM,
        messages=[{'role': 'user', 'content': prompt}]
    ))
    return sanitize_generated_text(response.content[0].text, max_chars=240)


def main():
    delay = random.randint(3, 30) * 60 + random.randint(0, 59)
    print('[' + str(datetime.now()) + '] Reply scanner delay: ' + str(delay // 60) + ' min')
    time.sleep(delay)

    from fetcher import get_latest_headlines
    headlines = get_latest_headlines()
    if not headlines:
        print('No headlines')
        return

    selected = random.sample(headlines, min(3, len(headlines)))
    nl = chr(10)
    suggestions = []

    for h in selected:
        try:
            reply = generate_reply(h['source'], h['title'])
            suggestions.append({'a': h['source'], 'o': h['title'], 'r': reply})
        except Exception as e:
            print('Reply error: ' + str(e))

    if not suggestions:
        return

    msg = 'Sugerencias de reply (' + str(len(suggestions)) + '):' + nl + nl
    for i, s in enumerate(suggestions, 1):
        msg += str(i) + '. @' + s['a'] + nl
        msg += 'Tweet: ' + s['o'][:150] + nl
        msg += 'Tu reply: ' + s['r'] + nl + nl
    msg += 'Copia y pega en X desde tu telefono.'

    send_tg(msg)
    print('[' + str(datetime.now()) + '] Enviadas ' + str(len(suggestions)))


if __name__ == '__main__':
    main()
