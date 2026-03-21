#!/usr/bin/env python3
"""Reply suggestion generator for @napoleotics with humanization."""
import sys, os, json, random, time, urllib.request
from datetime import datetime

sys.path.insert(0, '/root/x-bot')
os.chdir('/root/x-bot')
from dotenv import load_dotenv
load_dotenv('/root/x-bot/.env')
import anthropic

BOT_TOKEN = '8603788822:AAHkhXtvyFBqYSA-hglE0aXr_0rAZhFaWxM'
CHAT_ID = 6054558214

REPLY_SYSTEM = """Eres el analista detras de @napoleotics. Genera UNA reply para un tweet de una cuenta grande.

REGLAS:
- Max 240 caracteres, en espanol
- NUNCA repitas lo que dice el tweet original
- SIEMPRE agrega perspectiva nueva: dato, conexion macro, contexto historico, o pregunta provocadora
- Tono: informado, directo, con autoridad pero sin arrogancia
- Maximo 1 emoji si es relevante (bandera, grafico)
- Sin hashtags

TIPOS DE REPLY (alterna):
1. DATO CONTRARIO: "Todos celebran X, pero el dato real es Y..."
2. CONEXION MACRO: "Esto se conecta con [evento]. El impacto real es..."
3. PREGUNTA RETORICA: "Y si esto no es coincidencia?"
4. CONTEXTO HISTORICO: "La ultima vez que paso fue en [fecha] y el resultado fue..."
5. OPERADOR: "Lo que significa para [mercado]: [consecuencia concreta]"

ANTI-DETECCION IA:
- Varia largo de oraciones
- Incluye opinion con friccion
- Usa una imperfeccion: pregunta sin respuesta, frase cortada, sarcasmo
- NUNCA: "Es importante", "Cabe señalar", "Sin embargo", "Furthermore"
- Escribe como humano que tiene prisa, no como ensayo academico"""

client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

def send_tg(text):
    url = 'https://api.telegram.org/bot' + BOT_TOKEN + '/sendMessage'
    data = json.dumps({'chat_id': CHAT_ID, 'text': text}).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req)
    except Exception as e:
        print('Telegram error: ' + str(e))

def generate_reply(account, tweet_text):
    reply_type = random.choice([
        'DATO_CONTRARIO', 'CONEXION_MACRO', 'PREGUNTA_RETORICA',
        'CONTEXTO_HISTORICO', 'OPERADOR'
    ])
    NL = chr(10)
    prompt = 'Cuenta: @' + account + NL
    prompt += 'Tweet: ' + tweet_text + NL
    prompt += 'Tipo: ' + reply_type + NL + NL
    prompt += 'Reply (solo texto):'

    response = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=100,
        system=REPLY_SYSTEM,
        messages=[{'role': 'user', 'content': prompt}]
    )
    return response.content[0].text.strip().strip('"')

def main():
    delay = random.randint(3, 30) * 60 + random.randint(0, 59)
    print('[' + str(datetime.now()) + '] Reply delay: ' + str(delay // 60) + 'm')
    time.sleep(delay)

    from fetcher import get_latest_headlines
    headlines = get_latest_headlines(6)
    if not headlines:
        print('No headlines')
        return

    selected = random.sample(headlines, min(3, len(headlines)))
    NL = chr(10)
    suggestions = []

    for h in selected:
        try:
            reply = generate_reply(h['source'], h['title'])
            suggestions.append({'a': h['source'], 'o': h['title'], 'r': reply})
        except Exception as e:
            print('Error: ' + str(e))

    if not suggestions:
        return

    msg = 'Sugerencias de reply (' + str(len(suggestions)) + '):' + NL + NL
    for i, s in enumerate(suggestions, 1):
        msg += str(i) + '. @' + s['a'] + NL
        msg += 'Tweet: ' + s['o'][:150] + NL
        msg += 'Tu reply: ' + s['r'] + NL + NL
    msg += 'Copia y pega en X desde tu telefono.'

    send_tg(msg)
    print('[' + str(datetime.now()) + '] Enviadas ' + str(len(suggestions)))

if __name__ == '__main__':
    main()
