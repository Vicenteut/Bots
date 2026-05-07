"""tts_align — whisper.cpp wrapper for word-level timestamp alignment.

Drives karaoke captions in trash-edit reel templates (Phase 1).
Caches results by audio content hash so re-renders are free.
Returns [] when whisper.cpp is unavailable so the renderer falls back gracefully.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlignWord:
    word: str
    start: float  # seconds
    end: float    # seconds


def _cache_dir() -> Path:
    """Return (and create) the cache directory for alignment results."""
    env_val = os.environ.get("TTS_ALIGN_CACHE_DIR")
    if env_val:
        d = Path(env_val)
    else:
        d = Path(__file__).parent / ".tts_align_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _audio_hash(path: Path) -> str:
    """SHA-256 of file contents; first 16 hex chars."""
    h = hashlib.sha256(path.read_bytes())
    return h.hexdigest()[:16]


def _binary_ok() -> bool:
    """True iff both env vars are set and the paths actually exist on disk."""
    main = os.environ.get("WHISPER_CPP_MAIN", "")
    model = os.environ.get("WHISPER_CPP_MODEL", "")
    return bool(main and model and Path(main).exists() and Path(model).exists())


def _parse_whisper_json(payload: dict) -> list[AlignWord]:
    """Walk whisper.cpp JSON transcription segments into AlignWord list."""
    words: list[AlignWord] = []
    for seg in payload.get("transcription", []):
        offsets = seg.get("offsets", {})
        start_ms = offsets.get("from", 0)
        end_ms = offsets.get("to", 0)
        raw_text = seg.get("text", "")
        word = raw_text.strip().rstrip(".,;:!?")
        if not word:
            continue
        words.append(AlignWord(word=word, start=start_ms / 1000.0, end=end_ms / 1000.0))
    return words


def align_words(audio_path: Path) -> list[AlignWord]:
    """Return word-level timestamps for *audio_path* via whisper.cpp.

    Returns an empty list if whisper.cpp is not configured, the binary/model
    is missing, or the audio file doesn't exist — so callers can degrade
    gracefully without raising.
    """
    if not os.environ.get("WHISPER_CPP_MAIN"):
        logger.info("WHISPER_CPP_MAIN not set; skipping alignment")
        return []

    if not _binary_ok():
        logger.warning("whisper.cpp binary or model not found; skipping alignment")
        return []

    if not audio_path.exists():
        logger.warning("Audio file not found: %s", audio_path)
        return []

    # --- Cache lookup ---
    cache_key = _audio_hash(audio_path)
    cache_file = _cache_dir() / f"{cache_key}.json"
    if cache_file.exists():
        try:
            raw = json.loads(cache_file.read_text())
            return [AlignWord(**entry) for entry in raw]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache read failed (%s); re-running whisper", exc)

    # --- Run whisper.cpp ---
    binary = os.environ["WHISPER_CPP_MAIN"]
    model = os.environ["WHISPER_CPP_MODEL"]

    with tempfile.TemporaryDirectory() as tmpdir:
        prefix = str(Path(tmpdir) / "out")
        cmd = [
            binary,
            "-m", model,
            "-f", str(audio_path),
            "--output-json",
            "--max-len", "1",
            "-of", prefix,
            "-l", "en",
            "-nt",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            logger.warning(
                "whisper.cpp exited %d. stderr tail: %s",
                result.returncode,
                result.stderr[-300:],
            )
            return []

        json_file = Path(prefix + ".json")
        if not json_file.exists():
            logger.warning("whisper.cpp did not produce %s", json_file)
            return []

        payload = json.loads(json_file.read_text())

    words = _parse_whisper_json(payload)

    # --- Write cache ---
    try:
        cache_file.write_text(json.dumps([w.__dict__ for w in words]))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write alignment cache: %s", exc)

    return words
