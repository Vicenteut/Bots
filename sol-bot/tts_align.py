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


def _audio_duration_sec(path: Path) -> float:
    """ffprobe wrapper. Returns 0.0 if it fails (caller should treat as unknown)."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return 0.0


def _spread_evenly(words: list[AlignWord], duration: float) -> list[AlignWord]:
    """Distribute words uniformly across [0, duration]."""
    if not words or duration <= 0:
        return words
    per = duration / len(words)
    return [
        AlignWord(word=w.word, start=i * per, end=(i + 0.9) * per)
        for i, w in enumerate(words)
    ]


def _redistribute_collapsed_tail(
    words: list[AlignWord], audio_duration: float
) -> list[AlignWord]:
    """whisper.cpp --max-len 1 frequently misaligns the tail of dense
    transcriptions: it collapses many words onto identical timestamps near
    the audio end while the actual speech is much earlier.

    Strategy: detect any zero-duration word (collapse signature). When found,
    walk back to the last word with strictly increasing timestamps; redistribute
    everything from there onward across the remaining audio. If the resulting
    per-word slot would be too small (< 0.18s, i.e. faster than legible
    karaoke), fall back to even-spreading ALL words across audio_duration.
    """
    if len(words) < 3 or audio_duration <= 0:
        return words

    # Locate the first collapsed (zero-duration) word.
    first_zero = None
    for i, w in enumerate(words):
        if w.start == w.end:
            first_zero = i
            break
    if first_zero is None:
        return words

    # Walk back to find the last word whose end < collapse value (truly
    # distinct timestamp), since whisper often poisons a few words before the
    # collapse with timestamps near the audio end.
    collapse_value = words[first_zero].start
    real_head = first_zero - 1
    while real_head >= 0 and words[real_head].end >= collapse_value - 0.01:
        real_head -= 1

    if real_head < 0:
        # No reliable prefix — even-spread the whole thing.
        logger.info("alignment unreliable from word 0; spreading %d evenly across %.2fs",
                    len(words), audio_duration)
        return _spread_evenly(words, audio_duration)

    head = words[: real_head + 1]
    tail = words[real_head + 1:]
    last_good_end = head[-1].end
    span = max(audio_duration - last_good_end, 0.0)
    per_word = span / max(len(tail), 1)

    # If per-word slot is below legibility floor, even-spread everything.
    if per_word < 0.18:
        logger.info("collapsed-tail slot too small (%.3fs/word); spreading all %d evenly across %.2fs",
                    per_word, len(words), audio_duration)
        return _spread_evenly(words, audio_duration)

    new_tail = [
        AlignWord(
            word=w.word,
            start=last_good_end + i * per_word,
            end=last_good_end + (i + 0.85) * per_word,
        )
        for i, w in enumerate(tail)
    ]
    logger.info("redistributed %d collapsed-tail words across %.2fs (after %.2fs)",
                len(tail), span, last_good_end)
    return head + new_tail


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

    # Repair whisper.cpp's collapsed-tail bug (silent on dense second halves)
    duration = _audio_duration_sec(audio_path)
    words = _redistribute_collapsed_tail(words, duration)

    # --- Write cache ---
    try:
        cache_file.write_text(json.dumps([w.__dict__ for w in words]))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write alignment cache: %s", exc)

    return words
