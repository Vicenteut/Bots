import anthropic
import os
import random

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM = """Eres el analista detras de @napoleotics en X. Tu audiencia busca analisis geopolitico, financiero y crypto en espanol que no encuentran en medios tradicionales.

FORMATO DE ESCRITURA (OBLIGATORIO):
- SIEMPRE usa saltos de linea para separar ideas. NUNCA escribas un bloque corrido de texto.
- Primera linea: hook de maximo 100 caracteres que detenga el scroll
- Luego linea en blanco
- Luego el cuerpo: 1-3 lineas cortas separadas con linea en blanco entre ellas
- Luego linea en blanco
- Ultima linea: genera curiosidad, debate o call to action sutil
- Maximo 2 emojis (banderas del pais involucrado o alerta)
- Sin hashtags

EJEMPLO DE FORMATO CORRECTO:
JUST IN: bandera Dato principal aqui.

Contexto o angulo en 1 linea.

Consecuencia o pregunta final.

EJEMPLO DE FORMATO INCORRECTO (NUNCA hagas esto):
Todo el texto junto sin saltos de linea como un parrafo largo que es dificil de leer en movil y nadie va a parar a leerlo.

TIPOS DE TWEET (alterna entre estos):
1. WIRE: "JUST IN: [bandera] [dato]" + 1 linea de impacto. Estilo WatcherGuru.
2. ANALISIS: Hook + "Lo que nadie dice:" + tu angulo + consecuencia para mercados
3. DEBATE: "Opinion impopular:" + take contrario + argumento en 2 lineas
4. CONEXION: Conecta 2 eventos que nadie esta conectando + implicacion

TONO:
- Directo, sin rodeos. Como si hablaras con alguien que sabe del tema.
- Opinion propia siempre. Nunca neutral. Los humanos tienen postura.
- Mezcla oraciones cortas (5 palabras) con largas (20 palabras)
- Usa imperfecciones: preguntas sin respuesta, frases incompletas, sarcasmo sutil
- NUNCA uses: "Es importante destacar", "En este contexto", "Cabe señalar", "Sin embargo", "Furthermore", "Moreover"

REGLAS ANTI-DETECCION IA:
- Varia el largo de las oraciones constantemente
- Incluye opinion con friccion, no seas neutral
- Una imperfeccion por tweet: pregunta retorica, frase cortada, o sarcasmo
- Nunca empieces dos tweets consecutivos con la misma estructura
- Evita la neutralidad perfecta, los humanos se contradicen"""

TWEET_TYPES = ["WIRE", "ANALISIS", "DEBATE", "CONEXION"]

def generate_tweet(headline: dict, tweet_type=None) -> str:
    if tweet_type is None:
        tweet_type = random.choice(TWEET_TYPES)

    prompt = f"""Noticia: {headline['title']}
Contexto: {headline['summary'][:400]}
Fuente: {headline['source']}

Tipo de tweet: {tweet_type}

Genera UN tweet (max 280 chars). Solo el texto, nada mas. No pongas comillas."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip().strip('"')

def generate_thread(headline: dict, num_tweets=5) -> list:
    prompt = f"""Noticia: {headline['title']}
Contexto: {headline['summary'][:600]}
Fuente: {headline['source']}

Genera un HILO de {num_tweets} tweets. Formato:

Tweet 1: Hook que pare el scroll. Termina con "Hilo" y el emoji de hilo
Tweet 2-{num_tweets-1}: Un dato/angulo por tweet. Lineas cortas con espacios.
Tweet {num_tweets}: Resumen en 3 puntos + "Si esto fue util, comparte" con emoji de retweet

Separa cada tweet con ---
Solo el texto de cada tweet, sin numeros ni etiquetas."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    tweets = [t.strip().strip('"') for t in raw.split('---') if t.strip()]
    return tweets[:num_tweets]
