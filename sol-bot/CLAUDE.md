# Sol-Bot — Guía para Claude

Bot de noticias autónomo (@napoleotics en X, @papayita_bot en Threads). Ingiere RSS y mensajes de canales de Telegram, genera copy con IA, publica en Threads/X.

**Lee este archivo completo antes de tocar código de este proyecto.**

---

## Procesos vivos (systemd)

Sol-Bot corre como **dos procesos separados** que comparten archivos JSON en disco. Esto importa muchísimo: cualquier acceso a estado compartido necesita coordinación.

| Servicio | Qué hace | Archivo |
|----------|----------|---------|
| `sol-commands.service` | Polling loop de Telegram (recibe órdenes del owner) | `sol_commands.py` |
| `sol-dashboard.service` | FastAPI + uvicorn en puerto 8502 (panel web) | `sol_dashboard_api.py` |
| `xbot-monitor.service` | Monitor de canales de Telegram (Telethon) | `monitor.py` |
| `sol-rss-fetcher.timer` | Ingesta RSS cada 15 min | `rss_fetcher.py` |
| `sol-threads-analytics.timer` | Sync de métricas de Threads cada hora | `threads_analytics.py` |
| `sol-reel-metrics.timer` | ETL diario de métricas de reels | `reel_metrics_etl.py` |

**Reiniciar todo el bot:**
```bash
systemctl restart xbot-monitor sol-commands sol-dashboard
```

**Reiniciar solo el listener de comandos** (lo más común tras editar `sol_commands.py`):
```bash
systemctl restart sol-commands
```

**Ver logs en vivo:**
```bash
journalctl -u sol-commands -f --no-pager
journalctl -u sol-dashboard -f --no-pager
tail -f /root/x-bot/logs/sol_commands.log
```

---

## Arquitectura (mapa mental)

```
Telegram channels ──► monitor.py ──► monitor_queue.json (FileLock)
                                  └► monitor_pending.json
                                  
RSS feeds (timer) ──► rss_fetcher.py ──► monitor_queue.json (FileLock)

Owner Telegram ──► sol_commands.py
                       ├── brain.py (intent classifier, Haiku)
                       ├── generator.py (copywriting LLM)
                       │       └── memory.py → context.json
                       ├── publish_service.py (shared logic)
                       └── threads_publisher.py (subprocess)

Web ──► sol_dashboard_api.py (FastAPI :8502)
            ├── lee/escribe los MISMOS json files que sol_commands
            └── publish_service.py (shared logic)

Bases de datos:
  analytics.db          — historial de posts y métricas
  threads_analytics.db  — métricas de Threads
```

---

## Convenciones críticas

### 1. **Toda I/O de JSON pasa por `json_store.py`**

Nunca uses `path.write_text(json.dumps(...))` ni `json.loads(path.read_text())` para archivos JSON compartidos. Los dos procesos pueden tocar el mismo archivo simultáneamente y sin lock obtienes corrupción silenciosa o pérdida de datos.

```python
from json_store import read_json, write_json, append_to_json_list

# Read (devuelve default si falta o está corrupto)
data = read_json(PENDING_FILE, default={})

# Write atómico bajo FileLock
write_json(PENDING_FILE, data)

# Append a una lista, todo bajo lock (evita TOCTOU)
append_to_json_list(PUBLISH_LOG, entry)
```

**Por qué:** En 2026-05 había race conditions en `pending_tweet.json`, `monitor_pending.json`, `context.json`, `publish_log.json`. La carrera más fea: `_append_publish_log` leía la lista, añadía una entrada y la guardaba — si los dos procesos publicaban casi a la vez, el segundo perdía la entrada del primero. Resuelto con `append_to_json_list`. Ver commits `03c30e8`, `f35525e`, `58a146a`, `e8a6fb6`.

**Excepción:** archivos `.txt` planos (e.g. `PENDING_NEWS_FILE`) y archivos `.pid` no necesitan json_store.

### 2. **Lógica de publicación vive en `publish_service.py`**

Las funciones `extract_threads_result`, `classify_publish_result`, `media_kind`, `append_publish_log` existieron duplicadas en `sol_commands.py` y `sol_dashboard_api.py` y empezaron a divergir. Ahora viven en `publish_service.py`:

```python
from publish_service import (
    extract_threads_result as _extract_threads_result,
    classify_publish_result as _classify_publish_result,
    media_kind as _media_kind,
    append_publish_log as _append_publish_log,
)
```

**Si añades algo a la lógica de publicación, hazlo en `publish_service.py`** — los dos procesos lo recogen automáticamente.

### 3. **`asyncio.get_running_loop()`, no `get_event_loop()`**

`get_event_loop()` está deprecado en Python 3.10 y será error en 3.12. Dentro de funciones `async def`, usa `get_running_loop()`. Ver commit `1846a3e`.

### 4. **Tests viven en `tests/` y usan pytest**

```bash
cd /root/x-bot/sol-bot && python3 -m pytest tests/ -v
```

Hay 21 tests de utilidades base (`test_json_store.py`, `test_publish_service.py`). **Si añades una utilidad pura nueva (algo sin side effects de red), añade tests.** No hace falta testear endpoints de FastAPI ni el LLM en sí.

---

## Modelos de IA y proveedores

`generator.py` y `brain.py` pueden hablar tanto con Anthropic directo como con OpenRouter (proxy OpenAI-compatible).

| Variable env | Si está set... |
|--------------|----------------|
| `OPENROUTER_API_KEY` | Se usa como **primario** (path is_openrouter=True) |
| `ANTHROPIC_API_KEY` | Fallback si OpenRouter no está |

**Hoy mismo (2026-05) ambos están set, así que el bot va por OpenRouter.** El path Anthropic directo tiene `cache_control: ephemeral` aplicado al system prompt (commit `82dcdec`) — no se exercita actualmente. Para activar caching real, hay que: (a) quitar `OPENROUTER_API_KEY`, o (b) replicar el caching en el path OpenRouter.

**Mapeo de tweet types a modelos** (en `generator.py`):
- `WIRE` → Gemini Flash (rápido, breve)
- `DEBATE` → Haiku
- `ANALISIS`, `CONEXION` → Sonnet

---

## Publicación de media en Threads

`threads_publisher.py` se invoca como **subprocess** desde `sol_commands.py` y `sol_dashboard_api.py`. Devuelve resultado vía `[THREADS_RESULT]` en stdout que parsea `extract_threads_result`.

**Hosting de imágenes/videos:** Litterbox (`litter.catbox.moe`, TTL 1h).

```bash
# .env
THREADS_IMAGE_HOST=litterbox
```

Probamos brevemente self-hosted vía `media.theclamletter.com` (Cloudflare → nginx → FastAPI `/media/`) en 2026-05 pero Meta no lograba ingerir las imágenes desde ese host (probablemente bloqueo de IP/bot por Cloudflare incluso con WAF skip y BIC apagado). Decisión: volver a Litterbox por simplicidad. El TTL de 1h es suficiente porque Meta hace el fetch en el momento de crear el contenedor.

`threads_publisher.py:get_public_url()` sigue existiendo para el modo `THREADS_IMAGE_HOST=self` por si en el futuro se quiere reintentar, pero **no usar en producción** sin re-validar end-to-end con Meta antes.

---

## Estado compartido en disco

Lista de archivos JSON con escritura por más de un proceso. **Todos deben pasar por `json_store`.**

| Archivo | Escritores | Lectores |
|---------|-----------|----------|
| `pending_tweet.json` | sol_commands, dashboard | ambos |
| `pending_combo.json` | sol_commands, dashboard | ambos |
| `monitor_pending.json` | sol_commands, dashboard, monitor | todos |
| `monitor_queue.json` | rss_fetcher, monitor | dashboard, sol_commands |
| `context.json` | memory.py (vía sol_commands o dashboard) | ambos |
| `brain_history.json` | brain.py (vía sol_commands) | sol_commands |
| `logs/publish_log.json` | sol_commands, dashboard | dashboard |

---

## Cosas que NO hacer

- ❌ Editar `sol_commands.py` o `sol_dashboard_api.py` y duplicar lógica de publicación. Va en `publish_service.py`.
- ❌ Usar `path.write_text(json.dumps(...))` para JSON compartido. Usa `json_store`.
- ❌ Añadir `import tempfile` dentro de funciones para hacer escritura atómica manual. `json_store` ya lo hace.
- ❌ Añadir un nuevo proceso/servicio que escriba a un JSON existente sin actualizar este CLAUDE.md.
- ❌ Reactivar `THREADS_IMAGE_HOST=self` sin re-validar con Meta primero — falló en 2026-05 (ver sección "Publicación de media en Threads").
- ❌ Mockear la base de datos en tests — los integration tests del flujo de publicación deben usar SQLite real.
- ❌ Commitear `.env` ni archivos `*.bak.*` ni `__pycache__`.
- ❌ Reiniciar `sol-commands` mientras hay un post pendiente sin antes guardar `pending_tweet.json` (lo hace automáticamente, pero no abortes a la fuerza).

---

## Comandos del owner por Telegram

(Definidos en `sol_commands.py`)

```
GENERAR
  <texto>           Genera post desde titular
  título | contexto Con contexto extra
  /noticia <text>   Explícito

FORMATO (regenera el último)
  /wire             Breaking
  /analisis         Análisis profundo
  /debate           Pregunta/opinión
  /conexion         Ángulo macro
  /regenera         Otro ángulo random
  /mixed            WIRE+ANALISIS en secuencia

PUBLICAR
  /publica          Publica en Threads
  /publica threads  Threads only
  /original         Publica original sin generar
  /to               Solo Threads original
  /traduce          Traduce y publica

SCHEDULER
  /publica 1        Publica post 1 del scheduler
  /publica 2        Publica post 2

INFO
  /status           Estado del bot
  /ayuda            Lista completa
```

---

## Tests y verificaciones

```bash
# Suite completa
cd /root/x-bot/sol-bot && python3 -m pytest tests/ -v

# Solo utilidades de I/O
python3 -m pytest tests/test_json_store.py -v

# Solo lógica de publish_service
python3 -m pytest tests/test_publish_service.py -v

# Sintaxis de archivos clave
python3 -c "import ast; [ast.parse(open(f).read()) for f in ['sol_commands.py','sol_dashboard_api.py','generator.py','memory.py']]; print('OK')"

# Estado de servicios
systemctl status sol-commands sol-dashboard xbot-monitor

# Race condition smoke test (debería completar sin error)
python3 -c "
from json_store import append_to_json_list
import threading, tempfile
from pathlib import Path
p = Path(tempfile.mktemp(suffix='.json'))
threads = [threading.Thread(target=lambda i=i: [append_to_json_list(p, {'i':i,'k':k}) for k in range(5)]) for i in range(4)]
[t.start() for t in threads]; [t.join() for t in threads]
import json
assert len(json.loads(p.read_text())) == 20
print('concurrency OK')
"
```

---

## Variables de entorno relevantes

(En `/root/x-bot/.env` y `/root/x-bot/sol-bot/.env` — **nunca imprimas valores completos**)

| Variable | Para qué |
|----------|----------|
| `TELEGRAM_BOT_TOKEN` | Bot de Telegram (Sol) |
| `OPENROUTER_API_KEY` | Proxy LLM (primario) |
| `ANTHROPIC_API_KEY` | LLM directo (fallback / caching) |
| `GEMINI_API_KEY` | Para WIRE (Flash) |
| `THREADS_ACCESS_TOKEN` | Publicación en Threads |
| `THREADS_USER_ID` | User ID de Threads |
| `THREADS_MEDIA_HOST` | URL pública para servir media (https://) |
| `THREADS_IMAGE_HOST` | `self` (recomendado) o `litterbox` (legacy) |
| `X_AUTH_TOKEN`, `X_CT0`, `X_TWID` | Cookies para publicar en X (vía `post_thread.js`) |
| `DASHBOARD_USER`, `DASHBOARD_PASSWORD_HASH` | Auth del dashboard |
| `INGEST_API_TOKEN` | Token para ingestar headlines vía API |
| `REELS_PUBLIC_BASE` | Base URL para reels servidos |

---

## Histórico relevante

- **2026-05-06 — Hardening arquitectónico (3 fases, 8 commits).** Eliminó race conditions en JSON compartido, consolidó lógica duplicada en `publish_service.py`, fix de deprecación de asyncio, prompt caching en path Anthropic, self-hosted media. Plan completo en `docs/superpowers/plans/2026-05-06-arch-hardening.md`. Backups de `.env` previos en `.env.bak.pre-task9`.

---

## Cuando dudes

- Si vas a tocar I/O de archivos compartidos → `json_store`
- Si vas a tocar lógica de publish/clasificación → `publish_service`
- Si vas a tocar el flujo de generación → `generator.py` (y considera memory/brain)
- Si vas a añadir un endpoint web → `sol_dashboard_api.py`
- Si vas a añadir un comando de Telegram → `sol_commands.py`

Si lo que vas a hacer no encaja en ninguna de estas casillas, **para y pregunta** antes de codear.
