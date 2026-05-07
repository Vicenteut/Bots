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


def test_align_words_caches_by_audio_hash(fake_whisper_json, tmp_path, monkeypatch):
    """Second call on same audio must not invoke whisper a second time."""
    audio = tmp_path / "fake.mp3"
    audio.write_bytes(b"abc")
    calls = {"n": 0}

    def fake_run(*args, **kwargs):
        calls["n"] += 1
        argv = args[0]
        prefix = argv[argv.index("-of") + 1]
        Path(prefix + ".json").write_text(fake_whisper_json.read_text())
        return mock.Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("tts_align.subprocess.run", fake_run)
    monkeypatch.setenv("WHISPER_CPP_MAIN", "/fake/main")
    monkeypatch.setenv("WHISPER_CPP_MODEL", "/fake/model")
    monkeypatch.setattr("tts_align._binary_ok", lambda: True)
    monkeypatch.setenv("TTS_ALIGN_CACHE_DIR", str(tmp_path / "cache"))

    align_words(audio)
    align_words(audio)

    assert calls["n"] == 1
