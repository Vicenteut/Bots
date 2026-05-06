# Sol Bot — Model Routing Optimization
**Fecha:** Marzo 2026
**Contexto:** Precios verificados vía OpenRouter / APIs directas

---

## ⚠️ Acción Inmediata Requerida

Gemini 2.0 Flash (`google/gemini-2.0-flash-001`) está deprecated y se apaga el **1 de junio de 2026**. Los slots de WIRE y DEBATE necesitan migración obligatoria, independientemente de cualquier otra decisión de routing.

---

## Tabla de Precios Relevantes (Marzo 2026, por 1M tokens)

| Modelo | Input | Output | Latencia | Español | Instruction Following |
|---|---|---|---|---|---|
| Claude Opus 4.6 | $5.00 | $25.00 | Alta | Excelente | Excelente |
| Claude Sonnet 4.6 | $3.00 | $15.00 | Media | Excelente | Excelente |
| Claude Haiku 4.5 | $1.00 | $5.00 | Baja | Muy bueno | Muy bueno |
| Gemini 2.5 Flash | $0.30 | $2.50 | Baja | Bueno | Bueno |
| Gemini 2.5 Pro | $1.25 | $10.00 | Media | Bueno | Bueno |
| Gemini 3 Flash | $0.50 | $3.00 | Baja | Bueno+ | Bueno |
| Gemini 3.1 Pro | $2.00 | $12.00 | Media-Alta | Bueno+ | Bueno+ |
| DeepSeek V3.2 | $0.28 | $0.42 | Baja | Aceptable | Aceptable |
| Grok 4 fast | $0.20 | $0.50 | Baja | Débil | Aceptable |
| GPT-5.4 | $2.50 | $15.00 | Media | Muy bueno | Muy bueno |

---

## Estimación de Tokens por Tweet

Componente típico de una generación:
- System prompt (Sol persona + hooks + moods): ~1,500–2,000 tokens
- Contexto (últimos 15 tweets): ~1,000 tokens
- News input: ~500–1,000 tokens
- **Total input: ~3,000–4,000 tokens**
- Output (tweet): ~100–250 tokens

Usando **3,500 input / 200 output** como base:

| Modelo | Costo/tweet |
|---|---|
| Gemini 2.5 Flash | ~$0.0016 |
| Gemini 3 Flash | ~$0.0024 |
| Claude Haiku 4.5 | ~$0.0045 |
| Claude Sonnet 4.6 | ~$0.0135 |
| Claude Opus 4.6 | ~$0.0225 |
| DeepSeek V3.2 | ~$0.0011 |

Con **prompt caching** de Claude (system prompt cached = 90% descuento en input repetido):
- Sonnet 4.6 con cache: ~$0.005/tweet
- Haiku 4.5 con cache: ~$0.002/tweet

---

## 1. Routing por Tipo de Contenido

### WIRE (Breaking News)
**Carga cognitiva:** Baja–media. Compresión + claridad. Ocasionalmente requiere comprimir complejidad geopolítica en 2 líneas.

**Problema actual:** Gemini 2.0 Flash funciona para titulares simples pero es superficial con geopolítica compleja. Además, se apaga en junio.

**Recomendación AUTO:** `google/gemini-2.5-flash` ($0.30/$2.50)
- Tiene hybrid reasoning (thinking mode configurable), muy superior a 2.0 Flash
- Para WIREs simples, es más que suficiente
- Para WIREs con complejidad geopolítica, activar thinking con budget mínimo de 1,024 tokens

**Recomendación MANUAL:** `anthropic/claude-sonnet-4-6` ($3.00/$15.00)
- El owner está esperando y revisando. La calidad justifica el costo.
- Mejor adherencia a la voz editorial de Sol

**Fallback:** Gemini 3 Flash ($0.50/$3.00) — si 2.5 Flash tiene problemas de disponibilidad

**Costo estimado** AUTO: ~$0.0016/tweet | MANUAL: ~$0.0135/tweet

---

### ANALYSIS (Insight Profundo)
**Carga cognitiva:** Alta. Razonamiento multi-paso, comprensión macro, insight no obvio. Este es el contenido que define la marca de Sol.

**Estado actual:** Sonnet 4.6 — funciona bien.

**Recomendación AUTO:** `anthropic/claude-sonnet-4-6` ($3.00/$15.00)
- No hay modelo más barato que iguale la combinación de: razonamiento profundo + español nativo + adherencia a system prompts complejos
- Gemini 2.5 Pro ($1.25/$10) sería ~40% más barato pero su instruction following con personalidades complejas es inferior
- Extended thinking disponible si se necesita más profundidad

**Recomendación MANUAL:** `anthropic/claude-opus-4-6` ($5.00/$25.00)
- El costo bajó de $15/$75 (Opus 4.1) a $5/$25 — ahora es viable para uso editorial selectivo
- La diferencia de calidad en análisis geopolítico profundo es perceptible
- A ~$0.0225/tweet, 5 tweets manuales al día = ~$0.11/día — totalmente viable

**Fallback:** Gemini 2.5 Pro ($1.25/$10.00) — razonamiento decente, más barato, pero voz menos consistente

**Costo estimado** AUTO: ~$0.0135/tweet | MANUAL: ~$0.0225/tweet

---

### DEBATE (Pregunta Retórica)
**Carga cognitiva:** Media-alta. Requiere entender la narrativa dominante para desafiarla con una pregunta inteligente. El modelo necesita "entender el juego" para hacer la pregunta correcta.

**Problema actual:** Gemini Flash genera preguntas obvias o mal construidas. Este es el slot más subóptimo del routing actual.

**Recomendación AUTO:** `anthropic/claude-haiku-4-5` ($1.00/$5.00)
- El upgrade más importante del routing. Haiku 4.5 es dramáticamente mejor que cualquier Flash para tareas que requieren nuance retórica
- Excelente instruction following — mantendrá la voz de Sol
- Español de alta calidad
- A $0.0045/tweet, es ~3x más caro que Gemini Flash pero la diferencia de calidad es enorme
- Si 6 DEBATEs/día × $0.0045 = $0.027/día — negligible

**Recomendación MANUAL:** `anthropic/claude-sonnet-4-6` ($3.00/$15.00)

**Fallback AUTO:** Gemini 2.5 Flash con thinking activado — pero la voz editorial probablemente se rompa

**Costo estimado** AUTO: ~$0.0045/tweet | MANUAL: ~$0.0135/tweet

---

### CONNECTION (Conexión de Eventos)
**Carga cognitiva:** Alta. Pensamiento abstracto, síntesis macro, creatividad. Similar a ANALYSIS pero más creativo.

**Estado actual:** Sonnet 4.6 — funciona bien.

**Recomendación AUTO:** `anthropic/claude-sonnet-4-6` ($3.00/$15.00)
- La síntesis abstracta requiere un modelo que "entienda" geopolítica a nivel macro.

**Recomendación MANUAL:** `anthropic/claude-opus-4-6` ($5.00/$25.00)
- CONNECTION es donde Opus brilla más. Conectar eventos dispares requiere razonamiento lateral donde la diferencia Sonnet→Opus es más notable.

**Fallback:** Gemini 2.5 Pro ($1.25/$10.00)

**Costo estimado** AUTO: ~$0.0135/tweet | MANUAL: ~$0.0225/tweet

---

## 2. Routing por Modo — Tabla Final

```python
# Automatic mode (scheduler) — optimizado para costo con calidad mínima viable
MODEL_MAP_AUTO = {
    "WIRE":       "google/gemini-2.5-flash",        # $0.30/$2.50
    "DEBATE":     "anthropic/claude-haiku-4-5",     # $1.00/$5.00
    "ANALISIS":   "anthropic/claude-sonnet-4-6",    # $3.00/$15.00
    "CONEXION":   "anthropic/claude-sonnet-4-6",    # $3.00/$15.00
}

# Manual mode (human-in-the-loop) — optimizado para calidad máxima
MODEL_MAP_MANUAL = {
    "WIRE":       "anthropic/claude-sonnet-4-6",    # $3.00/$15.00
    "DEBATE":     "anthropic/claude-sonnet-4-6",    # $3.00/$15.00
    "ANALISIS":   "anthropic/claude-opus-4-6",      # $5.00/$25.00
    "CONEXION":   "anthropic/claude-opus-4-6",      # $5.00/$25.00
}

# Fallback chain (si OpenRouter falla)
FALLBACK_CHAIN = {
    "anthropic/claude-opus-4-6":   "anthropic/claude-sonnet-4-6",
    "anthropic/claude-sonnet-4-6": "anthropic/claude-haiku-4-5",
    "anthropic/claude-haiku-4-5":  "google/gemini-2.5-flash",
    "google/gemini-2.5-flash":     "google/gemini-3-flash",
}

def get_model(content_type: str, mode: str = "auto") -> str:
    if mode == "manual":
        return MODEL_MAP_MANUAL[content_type]
    return MODEL_MAP_AUTO[content_type]
```

---

## 3. content_calendar.py (Planificación Editorial)

**Recomendación:** `anthropic/claude-sonnet-4-6`
- Corre una vez al día. Un mal plan editorial afecta todos los tweets del día.
- Sonnet es más que suficiente para planificación editorial.

**Costo diario estimado:** ~$0.01

---

## 4. reply_scanner.py (Respuestas Cortas)

**Recomendación:** `anthropic/claude-haiku-4-5` (mantener, actualizar a 4.5)
- 200 caracteres = ~50 tokens de output
- Haiku 4.5 es el piso de calidad aceptable para mantener la voz de Sol en replies
- Alternativas más baratas (DeepSeek, Grok) tienen español débil

**Costo estimado:** ~$0.002/reply. 20 replies/día = $0.04/día

**Optimización futura:** Si volumen >50/día, Gemini 2.5 Flash para draft + Haiku para refinamiento.

---

## 5. analytics_insights.py (Análisis de Performance)

**Recomendación:** `anthropic/claude-sonnet-4-6`
- Tarea analítica pesada donde la calidad del insight importa más que el costo
- Considerar Batch API de Anthropic (50% descuento, entrega ≤24h)
- Explorar: Sonnet 4.6 con extended thinking para análisis de patrones

**Costo diario estimado:** ~$0.02–0.05

---

## 6. Evaluación de Modelos Alternativos

### ✅ Recomendados para considerar
- **Gemini 2.5 Flash** — mejor reemplazo de 2.0 Flash. Hybrid reasoning. Débil en system prompts complejos.
- **Gemini 3 Flash** — buen fallback. Todavía en preview, menos estable.

### ⚠️ No recomendados para Sol Bot
- **DeepSeek V3.2** — español suena a traducción. Posible uso: pre-filtrado de noticias (donde idioma output no importa).
- **Llama 4/3.x** — instruction following inconsistente con prompts largos. Rate limits en OpenRouter.
- **Command R+** — sin ventaja clara sobre Haiku 4.5.
- **Grok 4 fast** — español débil, no mantiene personalidades editoriales.
- **GPT-5.4** — competitivo con Sonnet pero sin ventaja clara que justifique cambio.
- **Gemini 3.1 Pro** — en preview, instruction following con personalidades complejas inferior a Claude.

---

## 7. Presupuesto Diario Estimado

### Modo Automático (3 sesiones × 3 tweets = ~9 tweets/día)

| Tipo | Cantidad | Modelo | Costo/tweet | Subtotal |
|---|---|---|---|---|
| WIRE | 3 | Gemini 2.5 Flash | $0.0016 | $0.0048 |
| DEBATE | 2 | Claude Haiku 4.5 | $0.0045 | $0.0090 |
| ANALISIS | 2 | Claude Sonnet 4.6 | $0.0135 | $0.0270 |
| CONEXION | 2 | Claude Sonnet 4.6 | $0.0135 | $0.0270 |
| content_calendar | 1 | Claude Sonnet 4.6 | $0.0100 | $0.0100 |
| analytics_insights | 1 | Claude Sonnet 4.6 | $0.0300 | $0.0300 |
| replies | ~10 | Claude Haiku 4.5 | $0.0020 | $0.0200 |
| **TOTAL AUTO** | | | | **~$0.13/día** |

### Modo Manual (~3–5 tweets/día adicionales)

| Tipo | Cantidad | Modelo | Costo/tweet | Subtotal |
|---|---|---|---|---|
| WIRE | 1 | Claude Sonnet 4.6 | $0.0135 | $0.0135 |
| DEBATE | 1 | Claude Sonnet 4.6 | $0.0135 | $0.0135 |
| ANALISIS | 1 | Claude Opus 4.6 | $0.0225 | $0.0225 |
| CONEXION | 1 | Claude Opus 4.6 | $0.0225 | $0.0225 |
| **TOTAL MANUAL** | | | | **~$0.07/día** |

**Total Diario Combinado: ~$0.20/día (~$6/mes)**

---

## 8. Optimizaciones Avanzadas

### Prompt Caching (Anthropic API)
El system prompt de Sol (~1,500–2,000 tokens) es idéntico en cada llamada.
- Cache write: 1.25× input price (primera llamada)
- Cache read: 0.1× input price (llamadas subsiguientes)
- TTL: 5 minutos por defecto
- **Ahorro estimado: ~30–40% en input tokens** para sesiones con múltiples tweets

### Routing Dinámico por Complejidad
```python
def smart_route(news_item, content_type, mode):
    complexity = estimate_complexity(news_item)
    if mode == "auto" and content_type == "WIRE" and complexity > THRESHOLD:
        return "anthropic/claude-haiku-4-5"  # upgrade de Flash
    return get_model(content_type, mode)
```

### Escalamiento por Confianza
Post-generación, evaluar calidad con modelo barato (Gemini Flash como juez). Si score es bajo, regenerar con siguiente modelo en la cadena.

### Batch API para analytics_insights.py
50% descuento. Entrega en ≤24 horas. Ideal para análisis no urgentes.

---

## Resumen Ejecutivo

1. **Migración urgente** de Gemini 2.0 Flash → Gemini 2.5 Flash (WIRE) y Claude Haiku 4.5 (DEBATE)
2. **Diferenciar AUTO vs MANUAL** — el mayor cambio arquitectural. Manual usa modelos premium.
3. **DEBATE es el slot más mejorado** — de Flash (preguntas obvias) a Haiku (retórica con nuance)
4. **Opus 4.6 ahora es viable** para modo manual gracias a la caída de precio ($5/$25 vs $15/$75 anterior)
5. **Costo mensual estimado: ~$6** — sostenible y con margen para escalar
6. No hay modelo alternativo en OpenRouter que supere a Claude para: español nativo + personalidad editorial compleja + razonamiento geopolítico
7. **Prompt caching es la optimización de costo más impactante** a implementar
