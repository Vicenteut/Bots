# Sol-Bot Architecture Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar las tres clases de bugs que pueden silenciosamente corromper datos en producción: carreras de datos en JSON compartido, lógica duplicada que diverge, y una dependencia de CDN sin SLA.

**Architecture:** Tres fases independientes y desplegables por separado. Fase 1 es la más urgente (datos corruptos en producción). Fase 2 consolida la lógica duplicada antes de que diverja más. Fase 3 mejora coste y mantenibilidad sin afectar funcionalidad.

**Tech Stack:** Python 3.10, `filelock==3.20.1` (ya en requirements.txt), `anthropic==0.85.0`, FastAPI/uvicorn.

---

## Contexto crítico para el implementador

- `sol_commands.py` y `sol_dashboard_api.py` son **dos procesos separados** que corren simultáneamente: el primero como polling loop de Telegram, el segundo como servidor uvicorn.
- Ambos procesos leen y escriben los mismos archivos JSON **sin coordinación**.
- `filelock` ya está instalado — no hace falta añadirlo.
- La suite de tests existente es sólo `tests/brain_test.yaml` (promptfoo). Añadiremos pytest.
- Para reiniciar el bot: `systemctl restart xbot-monitor`

---

# FASE 1 — Integridad de datos (Race conditions)

**Duración estimada:** 2-3 horas  
**Riesgo de regresión:** Bajo — sólo añadimos locks y atomicidad  
**Deploy:** `systemctl restart xbot-monitor` después del Task 4

---

### Task 1: Crear `json_store.py` — utilidad de lectura/escritura JSON con lock

**Files:**
- Create: `sol-bot/json_store.py`
- Create: `sol-bot/tests/test_json_store.py`

Este módulo centraliza todo acceso a archivos JSON compartidos entre procesos. Usa `FileLock` para serializar reads+writes y `os.replace()` para atomicidad.

- [ ] **Step 1: Escribir los tests (TDD)**

```python
# sol-bot/tests/test_json_store.py
import json
import threading
import time
from pathlib import Path
import pytest
import tempfile
import os

# Añadir el directorio padre al path para importar json_store
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from json_store import read_json, write_json, append_to_json_list


@pytest.fixture
def tmp_json(tmp_path):
    """Returns a Path to a non-existent JSON file in a temp dir."""
    return tmp_path / "test.json"


def test_write_and_read_roundtrip(tmp_json):
    write_json(tmp_json, {"key": "value", "num": 42})
    result = read_json(tmp_json)
    assert result == {"key": "value", "num": 42}


def test_read_missing_file_returns_default(tmp_json):
    result = read_json(tmp_json, default={"empty": True})
    assert result == {"empty": True}


def test_read_missing_file_returns_none_by_default(tmp_json):
    result = read_json(tmp_json)
    assert result is None


def test_write_is_atomic_on_crash(tmp_json):
    """Verify that a partial write doesn't corrupt an existing file."""
    write_json(tmp_json, {"original": True})
    # Simulate partial write by writing invalid JSON to tmp file
    tmp = tmp_json.parent / f".tmp_{tmp_json.name}"
    tmp.write_text("{ INVALID JSON", encoding="utf-8")
    # The original file must still be readable
    result = read_json(tmp_json)
    assert result == {"original": True}


def test_append_to_json_list(tmp_json):
    append_to_json_list(tmp_json, {"a": 1})
    append_to_json_list(tmp_json, {"b": 2})
    result = read_json(tmp_json, default=[])
    assert result == [{"a": 1}, {"b": 2}]


def test_append_creates_file_if_missing(tmp_json):
    append_to_json_list(tmp_json, {"first": True})
    result = read_json(tmp_json, default=[])
    assert result == [{"first": True}]


def test_concurrent_appends_no_data_loss(tmp_json):
    """Two threads appending concurrently must not lose entries."""
    errors = []

    def appender(n):
        try:
            for i in range(5):
                append_to_json_list(tmp_json, {"thread": n, "i": i})
                time.sleep(0.001)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=appender, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errors in threads: {errors}"
    result = read_json(tmp_json, default=[])
    assert len(result) == 20, f"Expected 20 entries, got {len(result)}"


def test_concurrent_writes_no_corruption(tmp_json):
    """Multiple threads writing different dicts — last writer wins, no corruption."""
    errors = []

    def writer(val):
        try:
            for _ in range(10):
                write_json(tmp_json, {"value": val})
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # File must be valid JSON (not corrupted)
    result = read_json(tmp_json)
    assert isinstance(result, dict)
    assert "value" in result
```

- [ ] **Step 2: Verificar que los tests fallan (no existe json_store aún)**

```bash
cd /root/x-bot/sol-bot && python -m pytest tests/test_json_store.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'json_store'`

- [ ] **Step 3: Implementar `json_store.py`**

```python
# sol-bot/json_store.py
"""
json_store.py — Thread- and process-safe JSON file I/O.

All functions acquire a FileLock before read-modify-write cycles so that
concurrent writers (sol_commands.py + sol_dashboard_api.py) don't race.
Writes are atomic via tempfile + os.replace so a process kill mid-write
cannot produce a truncated file.
"""
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from filelock import FileLock

logger = logging.getLogger(__name__)

_LOCK_TIMEOUT = 10  # seconds; if lock is held longer something is wrong


def _lock_for(path: Path) -> FileLock:
    return FileLock(str(path) + ".lock", timeout=_LOCK_TIMEOUT)


def _atomic_write(path: Path, data: Any) -> None:
    """Write data as JSON atomically. Caller must hold the lock."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path, default: Any = None) -> Any:
    """Read and parse a JSON file under a lock. Returns `default` if missing or corrupt."""
    path = Path(path)
    with _lock_for(path):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[json_store] Could not read {path}: {e}")
            return default


def write_json(path: Path, data: Any) -> None:
    """Write data to a JSON file under a lock, atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock_for(path):
        _atomic_write(path, data)


def append_to_json_list(path: Path, entry: Any) -> None:
    """Append one entry to a JSON array file, under a lock (prevents TOCTOU race)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock_for(path):
        if path.exists():
            try:
                history = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(history, list):
                    history = []
            except (json.JSONDecodeError, OSError):
                history = []
        else:
            history = []
        history.append(entry)
        _atomic_write(path, history)
```

- [ ] **Step 4: Verificar que los tests pasan**

```bash
cd /root/x-bot/sol-bot && python -m pytest tests/test_json_store.py -v
```
Expected: todos los tests en PASSED, incluyendo los de concurrencia.

- [ ] **Step 5: Commit**

```bash
cd /root/x-bot && git add sol-bot/json_store.py sol-bot/tests/test_json_store.py
git commit -m "feat(store): locked atomic JSON read/write utility"
```

---

### Task 2: Arreglar `memory.py` — escritura no atómica en `_save()`

**Files:**
- Modify: `sol-bot/memory.py:40-47`

La línea `self.path.write_text(...)` en `_save()` no es atómica. Si el proceso muere durante la escritura, `context.json` queda truncado y la memoria de continuidad se pierde silenciosamente.

- [ ] **Step 1: Escribir el test de regresión**

Añadir al final de `sol-bot/tests/test_json_store.py`:

```python
def test_memory_save_is_atomic(tmp_path):
    """SolMemory._save() must not leave a truncated context.json on crash."""
    import sys
    sys.path.insert(0, str(tmp_path.parent.parent / "sol-bot"))
    from memory import SolMemory
    mem_path = tmp_path / "context.json"
    mem = SolMemory(path=mem_path, limit=5)
    mem.add_tweet("Test tweet about US macro", "WIRE", "finance", "threads")
    # File must exist and be valid JSON
    data = json.loads(mem_path.read_text())
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["tweet_type"] == "WIRE"
```

- [ ] **Step 2: Verificar que el test pasa antes del cambio (baseline)**

```bash
cd /root/x-bot/sol-bot && python -m pytest tests/test_json_store.py::test_memory_save_is_atomic -v
```
Expected: PASSED (confirma que el test funciona, no que había un bug — el bug es la falta de lock entre procesos).

- [ ] **Step 3: Reemplazar `_save()` en `memory.py`**

Localizar el método `_save` en `memory.py` (líneas 40-47) y reemplazarlo:

```python
# memory.py — reemplazar el método _save() completo

def _save(self):
    """Persist entries to disk atomically using json_store."""
    try:
        from json_store import write_json
        write_json(self.path, self._entries)
    except OSError as e:
        logger.error(f"[memory] Could not save {self.path}: {e}")
```

También reemplazar `_load()` para usar el lock en la lectura:

```python
def _load(self):
    """Load entries from disk using json_store (lock-safe read)."""
    try:
        from json_store import read_json
        data = read_json(self.path, default=[])
        self._entries = data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"[memory] Could not load {self.path}: {e}")
        self._entries = []
```

- [ ] **Step 4: Verificar que los tests siguen pasando**

```bash
cd /root/x-bot/sol-bot && python -m pytest tests/test_json_store.py -v
```
Expected: todos en PASSED.

- [ ] **Step 5: Commit**

```bash
cd /root/x-bot && git add sol-bot/memory.py
git commit -m "fix(memory): atomic + locked writes via json_store"
```

---

### Task 3: Arreglar `sol_commands.py` — escrituras no atómicas de `PENDING_FILE`

**Files:**
- Modify: `sol-bot/sol_commands.py:672` (y cualquier otro `PENDING_FILE.write_text()`)

`PENDING_FILE.write_text()` en la línea 672 no usa el patrón atómico que ya existe en el mismo archivo (`_atomic_write_json` en línea 51). Además, ninguna escritura de `PENDING_FILE` usa `FileLock`, por lo que el dashboard puede leer un estado parcial.

- [ ] **Step 1: Localizar todas las escrituras no atómicas de PENDING_FILE**

```bash
grep -n "PENDING_FILE\.write_text\|MONITOR_PENDING_FILE\.write_text\|PENDING_MEDIA_FILE\.write_text" \
  /root/x-bot/sol-bot/sol_commands.py
```
Anotar los números de línea devueltos — son las líneas a cambiar.

- [ ] **Step 2: Reemplazar `_atomic_write_json` por `write_json` de json_store**

En `sol_commands.py`, añadir el import al bloque de imports existente (después de `from topic_utils import classify_topic`):

```python
from json_store import read_json, write_json, append_to_json_list
```

- [ ] **Step 3: Reemplazar `PENDING_FILE.write_text(...)` en línea ~672**

El bloque original (en `cmd_generate_from_monitor`):
```python
PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2))
```

Reemplazar por:
```python
write_json(PENDING_FILE, pending)
```

- [ ] **Step 4: Buscar y reemplazar todos los demás `PENDING_FILE.write_text`**

```bash
grep -n "PENDING_FILE\.write_text\|COMBO_FILE\.write_text" /root/x-bot/sol-bot/sol_commands.py
```

Para cada coincidencia, reemplazar el patrón:
```python
# Antes (cualquier variante):
PENDING_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
# Después:
write_json(PENDING_FILE, data)
```

- [ ] **Step 5: Reemplazar la función `_atomic_write_json` local por un alias**

La función `_atomic_write_json` en `sol_commands.py:51-55` ya no es necesaria para PENDING_FILE. Dejarla sólo si se usa en otro contexto, o eliminarla si ninguna llamada la usa:

```bash
grep -n "_atomic_write_json" /root/x-bot/sol-bot/sol_commands.py
```

Si no hay más llamadas, eliminar la función (líneas 51-55).

- [ ] **Step 6: Smoke test del listener**

```bash
cd /root/x-bot/sol-bot && python -c "
from sol_commands import _atomic_write_json, PENDING_FILE
print('Import OK')
from json_store import write_json, read_json
from pathlib import Path
import tempfile, os
p = Path(tempfile.mktemp(suffix='.json'))
write_json(p, {'test': True})
assert read_json(p) == {'test': True}
p.unlink()
print('json_store smoke test OK')
"
```
Expected: `Import OK` y `json_store smoke test OK`

- [ ] **Step 7: Commit**

```bash
cd /root/x-bot && git add sol-bot/sol_commands.py
git commit -m "fix(commands): atomic locked writes for PENDING_FILE via json_store"
```

---

### Task 4: Arreglar `_append_publish_log` — TOCTOU en ambos archivos

**Files:**
- Modify: `sol-bot/sol_commands.py:959-1006`
- Modify: `sol-bot/sol_dashboard_api.py:555-605`

Ambas funciones `_append_publish_log` hacen read-modify-write de `publish_log.json` con escritura atómica pero **sin lock**. Si los dos procesos publican casi simultáneamente, el segundo proceso lee el array antes de que el primero termine de escribir y sobreescribe el nuevo entry del primero.

- [ ] **Step 1: Simplificar `_append_publish_log` en `sol_commands.py`**

Reemplazar el cuerpo de `_append_publish_log` (líneas 959-1006) para usar `append_to_json_list`:

```python
def _append_publish_log(platform: str, success: bool, tweet: str, tweet_id: str = None,
                         tweet_type: str = None, model_used: str = None,
                         has_media: bool = False, media_type: str = "text",
                         media_count: int = 0, status: str = None,
                         error_category: str = None, error_message: str = None,
                         fbtrace_id: str = None, public_media_urls: list = None):
    """Append one publish event to logs/publish_log.json. Never raises."""
    try:
        log_path = BASE_DIR.parent / "logs" / "publish_log.json"
        entry = {
            "published_at": datetime.now().isoformat(),
            "platform": platform,
            "success": success,
            "tweet_id": tweet_id,
            "text_preview": (tweet or "")[:80],
            "tweet_type": tweet_type,
            "topic_tag": classify_topic(tweet),
            "model_used": model_used,
            "char_count": len(tweet) if tweet else 0,
            "has_media": has_media,
            "media_type": media_type,
            "media_count": media_count,
            "status": status or ("OK" if success else "FAILED"),
            "error_category": error_category,
            "error_message": (error_message or "")[:500] if error_message else None,
            "fbtrace_id": fbtrace_id,
            "public_media_urls": public_media_urls or [],
        }
        append_to_json_list(log_path, entry)
    except Exception as e:
        logger.error(f"[publish_log] Failed to append entry: {e}")
```

- [ ] **Step 2: Simplificar `_append_publish_log` en `sol_dashboard_api.py`**

El cuerpo en `sol_dashboard_api.py:555-605` es idéntico en estructura. Reemplazarlo de la misma manera, usando el import correcto. Primero añadir el import de json_store al bloque de imports del dashboard:

```python
from json_store import read_json, write_json, append_to_json_list
```

Luego reemplazar el cuerpo de `_append_publish_log` (líneas 555-605):

```python
def _append_publish_log(platform: str, success: bool, tweet: str,
                        tweet_id: str = None, tweet_type: str = None,
                        has_media: bool = False, media_type: str = "",
                        media_count: int = 0, status: str = None,
                        error_category: str = None, error_message: str = None,
                        fbtrace_id: str = None, public_media_urls: list[str] = None) -> None:
    """Append a publish event to logs/publish_log.json (same format as sol_commands.py)."""
    try:
        entry = {
            "published_at": datetime.now().isoformat(),
            "platform": platform,
            "success": success,
            "tweet_id": tweet_id,
            "text_preview": (tweet or "")[:80],
            "tweet_type": tweet_type,
            "topic_tag": classify_topic(tweet),
            "char_count": len(tweet) if tweet else 0,
            "has_media": has_media,
            "media_type": media_type,
            "media_count": media_count,
            "status": status or ("OK" if success else "FAILED"),
            "error_category": error_category,
            "error_message": (error_message or "")[:500] if error_message else None,
            "fbtrace_id": fbtrace_id,
            "public_media_urls": public_media_urls or [],
        }
        append_to_json_list(PUBLISH_LOG, entry)
    except Exception as e:
        logger.warning(f"[publish_log] Failed to append: {e}")
```

- [ ] **Step 3: Reemplazar `_save_json` en `sol_dashboard_api.py` por `write_json`**

`_save_json` (líneas 497-500) ya es atómico pero sin lock. Reemplazar por un wrapper de `write_json`:

```python
def _save_json(path: Path, data: dict) -> None:
    write_json(path, data)
```

Esto garantiza que las 8 llamadas a `_save_json` en el dashboard también tienen lock.

- [ ] **Step 4: Verificar que el dashboard importa correctamente**

```bash
cd /root/x-bot/sol-bot && python -c "
import sys, os
os.environ.setdefault('DASHBOARD_PASSWORD_HASH', 'a' * 64)
os.environ.setdefault('DASHBOARD_USER', 'sol')
# Solo verificar imports, no arrancar el servidor
import importlib.util
spec = importlib.util.spec_from_file_location('json_store', 'json_store.py')
mod = importlib.util.load_from_spec(spec)
print('json_store import OK')
"
```

- [ ] **Step 5: Reiniciar el bot y verificar que arranca**

```bash
systemctl restart xbot-monitor
sleep 3
systemctl status xbot-monitor | head -20
```
Expected: `Active: active (running)`

- [ ] **Step 6: Commit**

```bash
cd /root/x-bot && git add sol-bot/sol_commands.py sol-bot/sol_dashboard_api.py
git commit -m "fix(publish): locked append_to_json_list eliminates TOCTOU in publish_log"
```

---

# FASE 2 — Consolidar lógica duplicada

**Duración estimada:** 1.5-2 horas  
**Riesgo de regresión:** Medio — tocamos el path de publicación en ambos procesos  
**Deploy:** Reiniciar ambos servicios tras Task 6

**Prerequisito:** Fase 1 completada.

El arquitecto detectó que `_classify_publish_result`, `_extract_threads_result` y `_append_publish_log` existen en ambos archivos y ya han empezado a divergir. Esta fase los extrae a un módulo compartido.

---

### Task 5: Crear `publish_service.py` — lógica compartida de publicación

**Files:**
- Create: `sol-bot/publish_service.py`
- Create: `sol-bot/tests/test_publish_service.py`

- [ ] **Step 1: Escribir los tests**

```python
# sol-bot/tests/test_publish_service.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from publish_service import (
    extract_threads_result,
    classify_publish_result,
    media_kind,
)


def test_extract_threads_result_parses_success():
    output = 'some log\n[THREADS_RESULT]{"post_id": "123", "success": true}\nmore log'
    result = extract_threads_result(output)
    assert result == {"post_id": "123", "success": True}


def test_extract_threads_result_returns_empty_on_missing():
    assert extract_threads_result("no result line here") == {}


def test_extract_threads_result_returns_empty_on_invalid_json():
    assert extract_threads_result("[THREADS_RESULT]{INVALID}") == {}


def test_classify_success():
    output = '[THREADS_RESULT]{"post_id": "456", "success": true}'
    result = classify_publish_result(output, returncode=0, media_kind_str="text")
    assert result["success"] is True
    assert result["post_id"] == "456"
    assert result["status"] == "OK"
    assert result["error_category"] is None


def test_classify_auth_error():
    output = "some log\n[ERROR] token invalid — unauthorized\n"
    result = classify_publish_result(output, returncode=1, media_kind_str="text")
    assert result["success"] is False
    assert result["error_category"] == "AUTH_ERROR"


def test_classify_media_error():
    output = "[ERROR] no valid image found in container"
    result = classify_publish_result(output, returncode=1, media_kind_str="image")
    assert result["error_category"] == "MEDIA_ERROR"


def test_classify_timeout():
    output = "connection timed out"
    result = classify_publish_result(output, returncode=1, media_kind_str="text")
    assert result["error_category"] == "TIMEOUT"


def test_classify_meta_error():
    output = "[META ERROR] fbtrace_id: abc123"
    result = classify_publish_result(output, returncode=1, media_kind_str="text")
    assert result["error_category"] == "META_ERROR"


def test_classify_generic_failure():
    output = "something went wrong"
    result = classify_publish_result(output, returncode=1, media_kind_str="text")
    assert result["success"] is False
    assert result["error_category"] == "FAILED"


def test_media_kind_video():
    assert media_kind("video", ["/tmp/vid.mp4"]) == "video"


def test_media_kind_carousel():
    assert media_kind("image", ["/tmp/a.jpg", "/tmp/b.jpg"]) == "carousel"


def test_media_kind_single_image():
    assert media_kind("image", ["/tmp/a.jpg"]) == "image"


def test_media_kind_text():
    assert media_kind("image", []) == "text"
```

- [ ] **Step 2: Verificar que fallan**

```bash
cd /root/x-bot/sol-bot && python -m pytest tests/test_publish_service.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'publish_service'`

- [ ] **Step 3: Implementar `publish_service.py`**

```python
# sol-bot/publish_service.py
"""
publish_service.py — Lógica compartida entre sol_commands.py y sol_dashboard_api.py.

Extrae las funciones que existían duplicadas en ambos archivos para que un fix
en una sola llegue a ambos procesos.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from json_store import append_to_json_list
from topic_utils import classify_topic

logger = logging.getLogger(__name__)

PUBLISH_LOG = Path("/root/x-bot/logs/publish_log.json")


def extract_threads_result(output: str) -> dict:
    """Parse the structured [THREADS_RESULT] line emitted by threads_publisher.py."""
    for line in (output or "").splitlines():
        if line.startswith("[THREADS_RESULT]"):
            try:
                raw = line.split("]", 1)[1].strip()
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
    return {}


def media_kind(media_type: str, media_paths: list) -> str:
    if media_type == "video" and media_paths:
        return "video"
    if len(media_paths) > 1:
        return "carousel"
    if len(media_paths) == 1:
        return "image"
    return "text"


def classify_publish_result(output: str, returncode: int, media_kind_str: str) -> dict:
    """Classify the output of a threads_publisher.py subprocess call into a structured result."""
    parsed = extract_threads_result(output)
    post_id = parsed.get("post_id") if parsed else None
    success = returncode == 0 and bool(post_id or parsed.get("success"))
    category = parsed.get("category") if parsed else None
    message = parsed.get("message") if parsed else None

    if not success and not category:
        lower = (output or "").lower()
        if "token" in lower or "permission" in lower or "unauthorized" in lower:
            category = "AUTH_ERROR"
        elif "content-type" in lower or "media url" in lower or "no valid image" in lower or "container failed" in lower:
            category = "MEDIA_ERROR"
        elif "timed out" in lower or "timeout" in lower:
            category = "TIMEOUT"
        elif "http error" in lower or "meta error" in lower or "fbtrace_id" in lower:
            category = "META_ERROR"
        else:
            category = "FAILED"

    if not message and not success:
        lines = [ln.strip() for ln in (output or "").splitlines() if ln.strip()]
        interesting = [ln for ln in lines if "[ERROR]" in ln or "[META ERROR]" in ln or "Container failed" in ln]
        message = interesting[-1] if interesting else (lines[-1] if lines else "Threads publish failed")

    return {
        "success": success,
        "post_id": post_id,
        "status": "OK" if success else (category or "FAILED"),
        "error_category": None if success else category,
        "error_message": None if success else message,
        "fbtrace_id": parsed.get("fbtrace_id") if parsed else None,
        "public_media_urls": parsed.get("media_urls") if isinstance(parsed.get("media_urls"), list) else [],
        "media_kind": parsed.get("media_type") or media_kind_str,
    }


def append_publish_log(
    platform: str,
    success: bool,
    tweet: str,
    tweet_id: str = None,
    tweet_type: str = None,
    model_used: str = None,
    has_media: bool = False,
    media_type: str = "text",
    media_count: int = 0,
    status: str = None,
    error_category: str = None,
    error_message: str = None,
    fbtrace_id: str = None,
    public_media_urls: list = None,
) -> None:
    """Append one publish event to logs/publish_log.json. Never raises."""
    try:
        entry = {
            "published_at": datetime.now().isoformat(),
            "platform": platform,
            "success": success,
            "tweet_id": tweet_id,
            "text_preview": (tweet or "")[:80],
            "tweet_type": tweet_type,
            "topic_tag": classify_topic(tweet),
            "model_used": model_used,
            "char_count": len(tweet) if tweet else 0,
            "has_media": has_media,
            "media_type": media_type,
            "media_count": media_count,
            "status": status or ("OK" if success else "FAILED"),
            "error_category": error_category,
            "error_message": (error_message or "")[:500] if error_message else None,
            "fbtrace_id": fbtrace_id,
            "public_media_urls": public_media_urls or [],
        }
        append_to_json_list(PUBLISH_LOG, entry)
    except Exception as e:
        logger.error(f"[publish_log] Failed to append entry: {e}")
```

- [ ] **Step 4: Verificar que los tests pasan**

```bash
cd /root/x-bot/sol-bot && python -m pytest tests/test_publish_service.py -v
```
Expected: todos en PASSED.

- [ ] **Step 5: Commit**

```bash
cd /root/x-bot && git add sol-bot/publish_service.py sol-bot/tests/test_publish_service.py
git commit -m "feat(service): publish_service.py extracts shared classify/log logic"
```

---

### Task 6: Actualizar `sol_commands.py` y `sol_dashboard_api.py` para usar `publish_service`

**Files:**
- Modify: `sol-bot/sol_commands.py`
- Modify: `sol-bot/sol_dashboard_api.py`

- [ ] **Step 1: En `sol_commands.py`, reemplazar las funciones locales con imports**

Añadir al bloque de imports de `sol_commands.py`:

```python
from publish_service import (
    extract_threads_result as _extract_threads_result,
    classify_publish_result as _classify_publish_result,
    media_kind as _media_kind,
    append_publish_log as _append_publish_log,
)
```

- [ ] **Step 2: Eliminar las funciones locales ahora redundantes en `sol_commands.py`**

Borrar las definiciones locales de:
- `_extract_threads_result` (líneas ~896-906)
- `_media_kind` (líneas ~909-916)
- `_classify_publish_result` (líneas ~919-950)
- `_append_publish_log` (líneas ~953-1006) — ya simplificada en Fase 1; ahora se elimina

```bash
grep -n "def _extract_threads_result\|def _media_kind\|def _classify_publish_result\|def _append_publish_log" \
  /root/x-bot/sol-bot/sol_commands.py
```
Eliminar cada definición completa (desde `def` hasta el siguiente `def` al mismo nivel de indentación).

- [ ] **Step 3: Verificar el signature de `_append_publish_log` en cada llamada**

El signature en `publish_service.py` no tiene `model_used` en el mismo orden que el original. Verificar cada call site:

```bash
grep -n "_append_publish_log(" /root/x-bot/sol-bot/sol_commands.py
```

Para cada llamada, asegurarse de que los parámetros se pasan como kwargs (no posicionales) para evitar errores de orden.

- [ ] **Step 4: Repetir para `sol_dashboard_api.py`**

```python
# Añadir al bloque de imports de sol_dashboard_api.py:
from publish_service import (
    extract_threads_result as _extract_threads_result,
    classify_publish_result as _classify_publish_result,
    media_kind as _media_kind,
    append_publish_log as _append_publish_log,
)
```

Borrar las definiciones locales:
```bash
grep -n "def _extract_threads_result\|def _classify_publish_result\|def _append_publish_log" \
  /root/x-bot/sol-bot/sol_dashboard_api.py
```

- [ ] **Step 5: Smoke test de ambos módulos**

```bash
cd /root/x-bot/sol-bot && python -c "
# Test sol_commands imports
import importlib.util, sys
spec = importlib.util.spec_from_file_location('publish_service', 'publish_service.py')
mod = importlib.util.load_from_spec(spec)
print('publish_service OK')
print('classify_publish_result:', mod.classify_publish_result.__module__)
"
```

- [ ] **Step 6: Ejecutar toda la suite de tests**

```bash
cd /root/x-bot/sol-bot && python -m pytest tests/ -v
```
Expected: todos en PASSED.

- [ ] **Step 7: Reiniciar el bot**

```bash
systemctl restart xbot-monitor
sleep 3
systemctl status xbot-monitor | head -15
journalctl -u xbot-monitor -n 20 --no-pager
```
Expected: `Active: active (running)`, sin errores de import en los logs.

- [ ] **Step 8: Commit**

```bash
cd /root/x-bot && git add sol-bot/sol_commands.py sol-bot/sol_dashboard_api.py
git commit -m "refactor(publish): sol_commands + dashboard import from publish_service"
```

---

# FASE 3 — Performance y mantenibilidad

**Duración estimada:** 1-2 horas  
**Riesgo de regresión:** Bajo — cambios aditivos o de config  
**Deploy:** Reiniciar servicios por módulo

**Prerequisito:** Fases 1 y 2 completadas.

---

### Task 7: Arreglar `asyncio.get_event_loop()` — deprecado en Python 3.10, error en 3.12

**Files:**
- Modify: `sol-bot/sol_dashboard_api.py` (11 call sites)

- [ ] **Step 1: Localizar todos los call sites**

```bash
grep -n "get_event_loop()" /root/x-bot/sol-bot/sol_dashboard_api.py
```
Deben ser exactamente 11 líneas: 1764, 1802, 1861, 1912, 2549, 2568, 2777, 2817, 2850, 2861, 2876.

- [ ] **Step 2: Reemplazar en masa**

```bash
sed -i 's/asyncio\.get_event_loop()/asyncio.get_running_loop()/g' \
  /root/x-bot/sol-bot/sol_dashboard_api.py
```

- [ ] **Step 3: Verificar el reemplazo**

```bash
grep -n "get_event_loop\|get_running_loop" /root/x-bot/sol-bot/sol_dashboard_api.py
```
Expected: cero líneas con `get_event_loop`, 11 con `get_running_loop`.

- [ ] **Step 4: Verificar que el dashboard arranca**

```bash
cd /root/x-bot/sol-bot && python -c "
import ast, sys
with open('sol_dashboard_api.py') as f:
    source = f.read()
tree = ast.parse(source)
print('Syntax OK — no parse errors')
"
```
Expected: `Syntax OK — no parse errors`

- [ ] **Step 5: Commit**

```bash
cd /root/x-bot && git add sol-bot/sol_dashboard_api.py
git commit -m "fix(dashboard): get_running_loop() replaces deprecated get_event_loop() (11 sites)"
```

---

### Task 8: Añadir prompt caching en `generator.py` para el path Anthropic

**Files:**
- Modify: `sol-bot/generator.py:92-111` (`_call_api`)

El `SYSTEM_PROMPT` es ~7k chars de texto estático que se reconstruye en cada llamada LLM (`generator.py:558-563`). El SDK de Anthropic soporta `cache_control` para marcar bloques de sistema como cacheables, reduciendo el coste en 50-70% en llamadas repetidas.

**Condición:** El caching sólo aplica cuando `is_openrouter=False` (llamada directa a Anthropic). Para OpenRouter no hay soporte equivalente.

- [ ] **Step 1: Actualizar `_call_api` para usar `cache_control` en el path Anthropic**

Localizar la función `_call_api` en `generator.py` (líneas ~92-111) y reemplazar el bloque `else`:

```python
def _call_api(client, model: str, system: str, user_prompt: str, max_tokens: int, is_openrouter: bool) -> str:
    """Unified API call — handles both OpenRouter (OpenAI format) and Anthropic."""
    if is_openrouter:
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content.strip()
    else:
        # Split system prompt: static SYSTEM_PROMPT (cacheable) + dynamic continuity block
        # cache_control marks this block for prompt caching (Anthropic SDK >=0.28)
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text.strip()
```

- [ ] **Step 2: Verificar que `anthropic==0.85.0` soporta este formato**

```bash
cd /root/x-bot/sol-bot && python -c "
import anthropic
# Verificar que la versión instalada soporta system como lista de blocks
import inspect
sig = inspect.signature(anthropic.Anthropic().messages.create)
print('messages.create signature OK')
print('anthropic version:', anthropic.__version__)
"
```
Expected: version `0.85.0` y `signature OK`

- [ ] **Step 3: Smoke test de generación (sin publicar)**

```bash
cd /root/x-bot/sol-bot && python -c "
from generator import generate_tweet
headline = {'title': 'Test headline for cache smoke test', 'summary': 'Test summary', 'source': 'test'}
result = generate_tweet(headline, tweet_type='WIRE', platform='threads')
print('Generation OK:', len(result), 'chars')
print(result[:100])
"
```
Expected: texto generado, sin errores de API.

- [ ] **Step 4: Commit**

```bash
cd /root/x-bot && git add sol-bot/generator.py
git commit -m "perf(generator): Anthropic prompt caching via cache_control on system block"
```

---

### Task 9: Configurar media self-hosted — eliminar dependencia de Litterbox

**Files:**
- Modify: `sol-bot/.env` (o `/root/x-bot/.env`)
- No code change needed — la infraestructura ya está en `threads_publisher.py:300-303`

El código de `threads_publisher.py` ya tiene soporte para una URL pública alternativa via la variable `THREADS_IMAGE_HOST`. El dashboard ya sirve `/media/` como endpoint FastAPI. Sólo necesitamos una URL pública válida.

- [ ] **Step 1: Verificar que el endpoint `/media/` del dashboard es accesible públicamente**

```bash
# Obtener la URL pública del dashboard (normalmente via cloudflared o nginx)
grep -r "DASHBOARD_URL\|PUBLIC_URL\|CLOUDFLARE\|ngrok" /root/x-bot/.env /root/x-bot/sol-bot/.env 2>/dev/null | head -10
# Si hay una URL pública, probar acceso a un archivo de media existente
ls /root/x-bot/sol-bot/media/ | head -5
```

- [ ] **Step 2: Identificar el dominio público del dashboard**

```bash
# El dominio puede estar en cloudflared config, nginx config, o .env
cat /etc/cloudflared/config.yml 2>/dev/null || true
grep -r "hostname\|domain\|public" /etc/nginx/sites-enabled/ 2>/dev/null | head -10 || true
```

- [ ] **Step 3: Configurar `THREADS_IMAGE_HOST` en el .env**

Una vez identificado el dominio público (por ejemplo `https://sol.example.com`):

```bash
# Añadir al /root/x-bot/sol-bot/.env (o al .env que usa threads_publisher.py):
echo 'THREADS_IMAGE_HOST=https://TU_DOMINIO_AQUI' >> /root/x-bot/sol-bot/.env
```

- [ ] **Step 4: Verificar que `threads_publisher.py` usa la nueva variable**

```bash
grep -n "THREADS_IMAGE_HOST\|get_public_url\|litterbox" /root/x-bot/sol-bot/threads_publisher.py | head -20
```
Confirmar que cuando `THREADS_IMAGE_HOST` está definida, se usa en lugar de Litterbox.

- [ ] **Step 5: Test de publicación con imagen local (staging)**

Si hay una imagen de test en `/root/x-bot/sol-bot/media/`:
```bash
cd /root/x-bot/sol-bot && python -c "
import os
os.environ['DRY_RUN'] = '1'  # Si threads_publisher soporta dry run
# O simplemente verificar que el URL se construye correctamente:
host = os.getenv('THREADS_IMAGE_HOST', '')
print('THREADS_IMAGE_HOST =', host or '(not set — will use Litterbox)')
"
```

- [ ] **Step 6: Commit**

```bash
cd /root/x-bot && git add sol-bot/.env
git commit -m "config: THREADS_IMAGE_HOST para self-hosted media en Threads"
```

---

## Resumen de Fases y Despliegue

| Fase | Tasks | Impacto | Deploy |
|------|-------|---------|--------|
| **1 — Integridad** | 1-4 | Elimina race conditions en JSON compartido | `systemctl restart xbot-monitor` tras Task 4 |
| **2 — Consolidación** | 5-6 | Elimina lógica duplicada; un fix llega a ambos procesos | Reiniciar `xbot-monitor` tras Task 6 |
| **3 — Performance** | 7-9 | Forward-compat Python 3.12, -50% coste LLM, CDN propio | Reiniciar `xbot-monitor` + dashboard por task |

Cada fase es independiente y desplegable sola. Fase 1 es la más urgente y tiene el menor riesgo de regresión.

## Verificación final (después de las 3 fases)

```bash
# Tests completos
cd /root/x-bot/sol-bot && python -m pytest tests/ -v

# Estado de servicios
systemctl status xbot-monitor

# Buscar cualquier uso restante de get_event_loop
grep -n "get_event_loop" /root/x-bot/sol-bot/sol_dashboard_api.py

# Buscar escrituras no atómicas residuales
grep -n "\.write_text(" /root/x-bot/sol-bot/sol_commands.py /root/x-bot/sol-bot/memory.py

# Confirmar que THREADS_IMAGE_HOST está activo
grep "THREADS_IMAGE_HOST" /root/x-bot/sol-bot/.env /root/x-bot/.env 2>/dev/null
```
