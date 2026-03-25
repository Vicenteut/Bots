# Sol Bot — Copywriting Engine Review

**Reviewed:** 2026-03-25
**Scope:** System prompt, content generation pipeline, platform strategy, anti-detection

---

## A. Hook Quality

### Current state
The system uses 4 tweet types (WIRE, ANALISIS, DEBATE, CONEXION) as implicit hook frameworks. The system prompt includes example hooks but doesn't explicitly rotate "hook angles" (curiosidad, contrarian, dinero, advertencia, autoridad) — that logic described in the architecture doc is **not implemented in the actual code**. The `generate_tweet()` function only passes `tweet_type`, not a hook angle.

### Issues found

1. **Missing hook angle rotation in code.** The 5 hook angles exist only in documentation, not in `generator.py`. The user prompt sent to Claude doesn't include an angle parameter. This means hook variety depends entirely on Claude's internal randomness within the system prompt constraints — which will converge toward repetitive patterns over time.

2. **Template fatigue risk.** The system prompt hardcodes recognizable starters: "JUST IN:", "Opinion impopular:", "Lo que nadie dice:". After ~50 posts, followers will pattern-match these. Audiences on X unfollow accounts that feel formulaic.

3. **No hook length variation.** All hooks target ~100 chars. Some of the highest-performing tweets on X use ultra-short hooks (under 40 chars): "Esto no tiene sentido.", "Nadie lo vio venir.", "Se viene."

### Recommendations

**R1: Implement hook angle rotation in code**
```python
HOOK_ANGLES = ["curiosidad", "contrarian", "dinero", "advertencia", "autoridad", "urgencia", "exclusividad"]

def generate_tweet(headline: dict, tweet_type=None, hook_angle=None) -> str:
    if tweet_type is None:
        tweet_type = random.choice(TWEET_TYPES)
    if hook_angle is None:
        hook_angle = random.choice(HOOK_ANGLES)

    prompt = f"""Noticia: {headline['title']}
Contexto: {headline['summary'][:400]}
Fuente: {headline['source']}

Tipo de tweet: {tweet_type}
Angulo de hook: {hook_angle}

Genera UN tweet (max 280 chars). Usa el angulo "{hook_angle}" para la primera linea.
Solo el texto, nada mas. No pongas comillas."""
```

**R2: Add 3 new hook angles**
- **Urgencia:** "Tienes 48 horas antes de que esto impacte tu portafolio..."
- **Exclusividad:** "Dato que pocos estan viendo..."
- **Prueba social:** "Los institucionales ya se movieron. Tu no."

**R3: Add a "no-template" hook mode**
One in every 5 tweets should NOT use any template pattern. Just start with a raw observation:
- "El yuan subio 3% esta semana y nadie dijo nada."
- "Rusia acaba de hacer algo que no hacia desde 2014."

This breaks the pattern recognition cycle.

**R4: Vary hook length deliberately**
Add to system prompt:
```
VARIACION DE LARGO DE HOOK:
- 30% de hooks: ultra-cortos (bajo 50 chars). Ej: "Esto no tiene sentido."
- 50% de hooks: normales (50-100 chars)
- 20% de hooks: largos (100-140 chars, solo para WIRE con datos especificos)
```

---

## B. Tone & Voice Calibration

### Issues found

1. **The "imperfection" approach is counterproductive.** Explicitly asking Claude to add "una imperfeccion por tweet" creates *calculated* imperfections that are *more* detectable than natural writing. Real humans don't distribute exactly one imperfection per post. Some posts are clean; others are messy. The regularity of the imperfection IS the tell.

2. **No persistent personality.** Sol has style rules but no character. It doesn't have consistent opinions on recurring topics. A real analyst would be consistently hawkish or dovish on China, consistently bullish or bearish on crypto, have known biases. This absence of consistency is an AI tell — humans have priors.

3. **Tone doesn't shift between content types.** A WIRE should feel urgent and factual. An ANALISIS should feel contemplative and insider-y. A DEBATE should feel confident and provocative. Currently, the system prompt applies one uniform tone.

### Recommendations

**R5: Replace "imperfection quota" with "voice personality"**

Remove:
```
- Una imperfeccion por tweet: pregunta retorica, frase cortada, o sarcasmo
```

Replace with a character sheet:
```
PERSONALIDAD DE SOL:
- Eres esceptico del consenso. Si todos dicen X, tu instinto es explorar no-X.
- Crees que los mercados financieros estan mas conectados a la geopolitica de lo que la mayoria entiende.
- Eres moderadamente alcista en Bitcoin a largo plazo pero cinico sobre altcoins.
- Desconfias de la Fed y de los bancos centrales en general.
- Admiras a los contrarians que acertaron: Burry, Dalio, Taleb.
- Tienes sentido del humor seco. No eres gracioso a proposito, pero a veces eres sarcastico.
- Cuando no sabes algo, lo dices. "No tengo claro que significa esto todavia."
```

This creates organic imperfections because the character naturally wouldn't always be polished.

**R6: Add tone modifiers per tweet type**
```python
TONE_MODIFIERS = {
    "WIRE": "Tono: urgente, factual, cero opinion. Solo el dato y el impacto inmediato.",
    "ANALISIS": "Tono: reflexivo, como un memo interno. Conecta puntos que otros no ven.",
    "DEBATE": "Tono: provocador pero con sustancia. Di algo que haga que alguien responda.",
    "CONEXION": "Tono: detective, como si acabaras de descubrir algo. Mezcla asombro con preocupacion.",
}
```

Add to the user prompt: `{TONE_MODIFIERS[tweet_type]}`

**R7: Add "mood variance"**
Not every post should be high-energy. Some should be casual:
```python
MOODS = ["energetico", "reflexivo", "preocupado", "sarcastico", "casual"]
mood = random.choice(MOODS)
# Add to prompt: f"Estado de animo para este tweet: {mood}"
```

---

## C. Content Structure

### Issues found

1. **4-line max is too rigid.** WIRE tweets should be 2 lines (urgency). ANALISIS can go 4-5 lines. DEBATE works best at 3 lines. One-size-fits-all structure hurts engagement.

2. **The content calendar is too predictable.** Fixed day-type mapping (Monday=analysis, Tuesday=debate) doesn't match how news works. A market crash on Tuesday shouldn't produce a "debate" post — it should produce a WIRE. The calendar should be *reactive*, not *prescriptive*.

3. **Thread structure is formulaic.** Every thread ends with "Si esto fue util, comparte." This is a known engagement-farming pattern that X's algorithm has started deprioritizing (as of 2025). Also, the 🧵 emoji is now a strong AI-bot signal.

4. **`content_calendar.py` doesn't use the system prompt from `generator.py`.** The calendar's `generate_content()` creates its own Claude call without the SYSTEM prompt, meaning calendar-generated content has no personality guardrails — it'll sound like generic Claude.

### Recommendations

**R8: Dynamic line limits per type**
```
WIRE: 2 lineas max. Dato + impacto. Nada mas.
ANALISIS: 3-5 lineas. Hook + contexto + angulo + consecuencia.
DEBATE: 3 lineas. Opinion + dato que la respalda + pregunta.
CONEXION: 3-4 lineas. Evento A + Evento B + "la conexion que nadie ve" + implicacion.
```

**R9: Replace rigid calendar with weighted reactive system**
```python
def get_tweet_type(headline, day_of_week):
    # Breaking news always gets WIRE regardless of day
    if is_breaking(headline):
        return "WIRE"

    # Weight by day but don't lock
    weights = DAY_WEIGHTS[day_of_week]  # e.g., Monday: {"ANALISIS": 0.6, "DEBATE": 0.2, "WIRE": 0.1, "CONEXION": 0.1}
    return random.choices(list(weights.keys()), weights=list(weights.values()))[0]
```

**R10: Fix content_calendar.py to use the shared system prompt**
```python
from generator import SYSTEM  # Use the same personality

message = client.messages.create(
    model=MODEL,
    max_tokens=1024,
    system=SYSTEM,  # Add this
    messages=[{"role": "user", "content": user_prompt}],
)
```

**R11: Modernize thread closers**
Replace "Si esto fue util, comparte 🔁" with varied closers:
- "Esto es lo que se por ahora. Si sale algo nuevo, lo agrego."
- "¿Me estoy perdiendo algo? Genuinamente pregunto."
- "Veremos en 2 semanas si esto envejece bien."
- No closer at all — just end with the last point.

Remove 🧵 emoji. Use "Abro hilo:" or "Va hilo corto:" or just start the thread without announcing it.

---

## D. Engagement Optimization

### Missing copywriting patterns

1. **No "open loops".** The most engaging tweets create curiosity gaps that make people click to read more or reply to ask. Example: "China acaba de hacer algo con sus reservas que no hacia desde 2008. Y curiosamente, solo 3 paises lo notaron."

2. **No "pattern interrupts".** Every Sol tweet follows news→insight→question. Occasionally start with the conclusion: "El dolar va a caer. Aqui esta por que." Or start with a question: "¿Que pasa cuando el segundo tenedor de deuda americana decide que ya no quiere serlo?"

3. **No engagement triggers for saves/bookmarks.** X now heavily weights bookmarks. Tweets with concrete data (numbers, dates, percentages) get bookmarked more. Add to prompt: "Incluye al menos un dato numerico especifico cuando sea posible."

4. **No quote-tweet bait.** Tweets that people want to quote (to agree or disagree) get massive reach. The DEBATE type should be more polarizing. Instead of "Opinion impopular: X", try "X. Y el que piense diferente no esta viendo los numeros."

### Stage-based strategy

**R12: Adapt engagement strategy to follower count**

**0-1K followers (current stage):**
- Focus on reply game: reply to big accounts in your niche with sharp takes
- Use `reply_scanner.py` more aggressively — 5-10 replies/day to accounts with 10K+ followers
- Controversial takes get more reach at this stage; lean into DEBATE
- Quote-tweet big accounts with your own angle added

**1K-10K followers:**
- Shift to threads and educational content (these get shared more)
- Start original analysis that establishes authority
- Reduce controversy slightly — you now have a reputation to build

**10K+ followers:**
- Original reporting and insider-level analysis
- Community engagement (polls, "what do you think?" posts)
- Cross-platform content differences matter more here

**R13: Optimize A/B testing**
The current system generates variants but doesn't track which angle performs best. Connect `analytics_tracker.py` to generator choices:
```python
# Store which type/angle was used for each tweet
# After 48 hours, pull metrics
# Weight future random choices toward better-performing combinations
```

This turns blind randomization into a learning system.

---

## E. Platform-Specific Optimization

### Issues found

1. **Threads and X get identical copy** (minus flag emojis and hashtags). This is suboptimal. The platforms have fundamentally different audiences and algorithms.

2. **Threads rewards conversation starters and shares.** The algorithm is explore-heavy — it pushes content to non-followers. Posts should be more accessible and less insider-y on Threads.

3. **X rewards replies and bookmarks.** Controversial, data-rich posts perform best. The copy should be sharper and more provocative on X.

4. **No timing differentiation.** Both platforms publish simultaneously, but optimal posting times differ.

### Recommendations

**R14: Generate platform-specific variants**
```python
def generate_tweet(headline, tweet_type=None, platform="x"):
    platform_instruction = {
        "x": "Escribe para X/Twitter. Se provocador y directo. Incluye datos que la gente quiera guardar (bookmark).",
        "threads": "Escribe para Threads. Se mas accesible y conversacional. La audiencia es mas casual. Haz preguntas que inviten respuestas."
    }

    prompt = f"""...
Plataforma: {platform}
{platform_instruction[platform]}
..."""
```

**R15: Threads-specific adjustments**
- Longer posts OK on Threads (500 char limit)
- More conversational tone
- End with questions more often (drives comments, which Threads rewards)
- Use topic labels strategically: #Breaking for urgency, #Crypto for discoverability

**R16: Stagger publishing times**
- X: Keep current schedule (7:30, 11, 5 CST)
- Threads: Shift 30-90 min later (different audience peak times)
- Track which times perform best per platform and adapt

---

## F. Anti-AI Detection

### Current AI tells in the system

1. **Consistent quality.** Every post is well-structured with clean grammar. Humans have off days. Some posts should be shorter, rougher, less polished.

2. **No memory or continuity.** Each tweet is generated independently. A human analyst would reference their own previous takes: "Dije hace 2 semanas que esto iba a pasar." The lack of self-reference is a tell.

3. **Perfect emoji discipline.** Exactly 1-2 emojis per post, always flags or alerts. Humans sometimes use 0, sometimes use 3, and occasionally use unexpected ones.

4. **No current event references beyond the headline.** A human analyst would connect today's news to something they read last week, or to an ongoing saga. Sol treats every headline as isolated.

5. **The banned phrase list is too narrow.** Beyond the listed phrases, Claude Haiku has other tells in Spanish: "Es clave entender", "Lo cierto es que", "Queda claro que", "No es menor que", "Resulta interesante". These should also be banned.

### Recommendations

**R17: Add continuity/memory system**
Store the last 10 published tweets and include them as context:
```python
RECENT_TWEETS = load_recent_tweets(limit=10)  # from a local JSON or DB

system_prompt_addition = f"""
Tus ultimos tweets publicados (para mantener continuidad y no repetirte):
{chr(10).join(RECENT_TWEETS)}

REGLAS DE CONTINUIDAD:
- NO repitas temas que ya cubriste en las ultimas 24 horas
- Si un tema es seguimiento de algo anterior, referencialo: "Update sobre lo que dije ayer..."
- Mantén consistencia en tus opiniones. Si dijiste X sobre China ayer, no digas lo contrario hoy sin explicar por que cambiaste de opinion.
"""
```

**R18: Expand banned phrase list**
```
NUNCA uses estas frases (suenan a IA):
- "Es importante destacar", "En este contexto", "Cabe señalar"
- "Sin embargo", "Furthermore", "Moreover"
- "Es clave entender", "Lo cierto es que", "Queda claro que"
- "No es menor que", "Resulta interesante", "Vale la pena mencionar"
- "En definitiva", "Dicho esto", "A modo de conclusion"
- "Esto nos lleva a", "Es preciso señalar"
```

**R19: Add variance to emoji usage**
```
EMOJIS:
- 60% de tweets: 1 emoji (bandera o alerta)
- 25% de tweets: 0 emojis
- 15% de tweets: 2 emojis
- Nunca mas de 2
- Ocasionalmente usa emojis inesperados: 💀 para algo que murio, 🤡 para algo absurdo
```

**R20: Develop a "running narrative" system**
Tag topics when publishing (e.g., "china-treasuries", "fed-rates", "btc-etf"). When the same topic appears again, the prompt should include context:
```
Este tema ya lo cubriste antes:
- 2026-03-20: "China vendio $30B en Treasuries"
- 2026-03-23: "El yuan sube por tercera semana"

Genera un tweet que conecte con tus takes anteriores. Puedes decir "como dije", "update:", "esto confirma lo que veniamos diciendo", etc.
```

---

## Priority Implementation Order

| Priority | Recommendation | Impact | Effort |
|----------|---------------|--------|--------|
| 1 | R10: Fix content_calendar.py system prompt | High | Low |
| 2 | R1: Implement hook angle rotation | High | Low |
| 3 | R5: Character sheet instead of imperfection quota | High | Low |
| 4 | R17: Continuity/memory system | High | Medium |
| 5 | R6: Tone modifiers per tweet type | Medium | Low |
| 6 | R18: Expand banned phrase list | Medium | Low |
| 7 | R8: Dynamic line limits | Medium | Low |
| 8 | R14: Platform-specific copy | High | Medium |
| 9 | R9: Reactive calendar | Medium | Medium |
| 10 | R13: A/B testing feedback loop | High | High |

---

## Summary

The core architecture is solid. The biggest gaps are:

1. **Implementation gaps**: Hook angles described in docs aren't in code. Calendar doesn't use the system prompt. Fix these first.
2. **No personality**: Sol has style rules but no character. A persistent personality with consistent opinions will both improve engagement and reduce AI detectability.
3. **No memory**: Each tweet is generated in isolation. Adding continuity between posts is the single highest-impact change for authenticity.
4. **Platform parity**: X and Threads need different copy. Same text on both is leaving engagement on the table.
5. **Static strategy**: The system randomizes but doesn't learn. Connecting analytics to generation choices creates a feedback loop that improves over time.
