"""Tests for tts_align.py — whisper.cpp wrapper for word-level timestamps."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from tts_align import align_words, AlignWord


@pytest.fixture
def fake_whisper_json(tmp_path: Path) -> Path:
    """Mimic whisper.cpp --output-json --max-len 1 output."""
    payload = {
        "transcription": [
            {"timestamps": {"from": "00:00:00,100", "to": "00:00:00,420"},
             "offsets": {"from": 100, "to": 420}, "text": " Breaking"},
            {"timestamps": {"from": "00:00:00,440", "to": "00:00:00,720"},
             "offsets": {"from": 440, "to": 720}, "text": " news"},
            {"timestamps": {"from": "00:00:00,800", "to": "00:00:01,150"},
             "offsets": {"from": 800, "to": 1150}, "text": " today."},
        ]
    }
    p = tmp_path / "whisper.json"
    p.write_text(json.dumps(payload))
    return p


def test_align_words_parses_whisper_output(fake_whisper_json, tmp_path, monkeypatch):
    """align_words should parse whisper.cpp JSON into AlignWord rows."""
    audio = tmp_path / "fake.mp3"
    audio.write_bytes(b"\x00")  # presence is enough; we mock the subprocess

    def fake_run(*args, **kwargs):
        # Pretend whisper wrote the JSON next to the requested -of prefix.
        argv = args[0] if args else kwargs.get("args", [])
        prefix = None
        for i, a in enumerate(argv):
            if a == "-of":
                prefix = argv[i + 1]
        assert prefix, "tts_align must pass -of <prefix>"
        Path(prefix + ".json").write_text(fake_whisper_json.read_text())
        return mock.Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("tts_align.subprocess.run", fake_run)
    monkeypatch.setenv("WHISPER_CPP_MAIN", "/fake/main")
    monkeypatch.setenv("WHISPER_CPP_MODEL", "/fake/model")
    # Bypass binary/model existence checks for the unit test
    monkeypatch.setattr("tts_align._binary_ok", lambda: True)

    words = align_words(audio)

    assert len(words) == 3
    assert words[0] == AlignWord(word="Breaking", start=0.100, end=0.420)
    assert words[1].word == "news"
    assert words[2].start == pytest.approx(0.800)
    assert words[2].end == pytest.approx(1.150)


def test_align_words_falls_back_when_whisper_missing(monkeypatch, tmp_path):
    """If WHISPER_CPP_MAIN is unset/missing, return empty list and log."""
    monkeypatch.delenv("WHISPER_CPP_MAIN", raising=False)
    audio = tmp_path / "fake.mp3"
    audio.write_bytes(b"\x00")
    assert align_words(audio) == []


def test_redistribute_collapsed_tail_spreads_words():
    """When whisper.cpp collapses the tail to identical timestamps, redistribute."""
    from tts_align import _redistribute_collapsed_tail
    words = [
        AlignWord("Hello", 0.0, 0.5),
        AlignWord("world", 0.5, 1.0),
        AlignWord("the", 1.0, 1.5),
        # collapsed tail: all at 2.0
        AlignWord("rest", 2.0, 2.0),
        AlignWord("of", 2.0, 2.0),
        AlignWord("this", 2.0, 2.0),
        AlignWord("sentence", 2.0, 2.0),
    ]
    fixed = _redistribute_collapsed_tail(words, audio_duration=10.0)
    assert len(fixed) == 7
    # Head is preserved
    assert fixed[0] == words[0]
    assert fixed[2] == words[2]
    # Tail is spread between last_good_end (1.5) and audio_duration (10.0)
    tail = fixed[3:]
    assert tail[0].start >= 1.5
    assert tail[-1].end <= 10.0 + 0.01
    # Strictly increasing starts
    for a, b in zip(tail, tail[1:]):
        assert b.start > a.start


def test_redistribute_no_collapse_passes_through():
    """If timestamps are healthy, redistribute should be a no-op."""
    from tts_align import _redistribute_collapsed_tail
    words = [
        AlignWord("a", 0.0, 0.4),
        AlignWord("b", 0.4, 0.8),
        AlignWord("c", 0.8, 1.2),
    ]
    assert _redistribute_collapsed_tail(words, audio_duration=2.0) == words


def test_merge_subword_splits_concatenates_continuations():
    """Tokens without a leading space concatenate onto the previous word."""
    from tts_align import _merge_subword_splits
    parsed = [
        (AlignWord("H", 0.0, 0.10), True),     # ` H` — word start
        (AlignWord("orm", 0.10, 0.18), False), # `orm` — continuation
        (AlignWord("uz", 0.18, 0.28), False),  # `uz` — continuation
        (AlignWord("is", 0.30, 0.45), True),   # ` is` — new word
    ]
    merged = _merge_subword_splits(parsed)
    assert len(merged) == 2
    assert merged[0].word == "Hormuz"
    assert merged[0].start == 0.0
    assert merged[0].end == 0.28
    assert merged[1].word == "is"


def test_merge_subword_splits_preserves_normal_words():
    """When every token has a leading space, nothing should merge."""
    from tts_align import _merge_subword_splits
    parsed = [
        (AlignWord("Hello", 0.0, 0.4), True),
        (AlignWord("world", 0.5, 0.9), True),
    ]
    merged = _merge_subword_splits(parsed)
    assert len(merged) == 2
    assert merged[0].word == "Hello"


def test_align_words_merges_subwords_end_to_end(tmp_path, monkeypatch):
    """Full pipeline: whisper.cpp emits subword splits → align_words returns merged."""
    payload = {
        "transcription": [
            {"offsets": {"from": 0, "to": 100}, "text": " H"},
            {"offsets": {"from": 100, "to": 180}, "text": "orm"},
            {"offsets": {"from": 180, "to": 280}, "text": "uz"},
            {"offsets": {"from": 300, "to": 450}, "text": " is"},
        ]
    }
    audio = tmp_path / "fake.mp3"
    audio.write_bytes(b"\x00")

    def fake_run(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args", [])
        if argv and argv[0] == "/fake/main":
            prefix = argv[argv.index("-of") + 1]
            Path(prefix + ".json").write_text(json.dumps(payload))
        return mock.Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("tts_align.subprocess.run", fake_run)
    monkeypatch.setenv("WHISPER_CPP_MAIN", "/fake/main")
    monkeypatch.setenv("WHISPER_CPP_MODEL", "/fake/model")
    monkeypatch.setattr("tts_align._binary_ok", lambda: True)
    monkeypatch.setenv("TTS_ALIGN_CACHE_DIR", str(tmp_path / "cache"))

    words = align_words(audio)
    assert len(words) == 2
    assert words[0].word == "Hormuz"
    assert words[1].word == "is"


def test_align_words_caches_by_audio_hash(fake_whisper_json, tmp_path, monkeypatch):
    """Second call on same audio must not invoke whisper a second time."""
    audio = tmp_path / "fake.mp3"
    audio.write_bytes(b"abc")
    whisper_calls = {"n": 0}

    def fake_run(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args", [])
        # Count only whisper invocations, not ffprobe duration probes.
        if argv and argv[0] == "/fake/main":
            whisper_calls["n"] += 1
            prefix = argv[argv.index("-of") + 1]
            Path(prefix + ".json").write_text(fake_whisper_json.read_text())
        return mock.Mock(returncode=0, stdout="0", stderr="")

    monkeypatch.setattr("tts_align.subprocess.run", fake_run)
    monkeypatch.setenv("WHISPER_CPP_MAIN", "/fake/main")
    monkeypatch.setenv("WHISPER_CPP_MODEL", "/fake/model")
    monkeypatch.setattr("tts_align._binary_ok", lambda: True)
    monkeypatch.setenv("TTS_ALIGN_CACHE_DIR", str(tmp_path / "cache"))

    align_words(audio)
    align_words(audio)

    assert whisper_calls["n"] == 1
