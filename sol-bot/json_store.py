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

_LOCK_TIMEOUT = 10  # seconds


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
