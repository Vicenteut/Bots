# Reels Phase 1 — Trash-Edit Motor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single static "data-card" reel template with four trash-edit-style templates plus shared pattern interrupts (microcuts, zoom punches, freeze stamps, color flashes, karaoke captions, loop bridge). Same input copy + same TTS, visually distinct output.

**Architecture:** Four HTML templates under `reels-hf/templates/` selected by `template_variant` field. Shared GSAP timeline include (`_interrupts.js`) implements pattern interrupts. New `tts_align.py` produces word-level timestamps via local whisper.cpp for karaoke captions. `render_reel_hf.py` picks the template and injects the karaoke JSON. `reels_generator.py` gets the minimum fields needed for selection (`template_variant`, `hook.variant`, `cta.text`) with backwards-compatible defaults; the full ReelSpec is filled in Phase 2.

**Tech Stack:** Python 3.10+, Hyperframes (npx CLI + GSAP 3.14 in HTML), whisper.cpp (local, no network), ffmpeg, pytest. Production branch: `main`. Working branch: `feat/reels-engagement-overhaul`.

**Reference spec:** `docs/superpowers/specs/2026-05-06-reels-engagement-overhaul-design.md` (sections 4 and 5).

---

## File map

**New:**
- `reels-hf/templates/_shared.css` — common styles (overlay, brand block, alarm strips, karaoke caption layer)
- `reels-hf/templates/_interrupts.js` — shared GSAP helpers (`microcut`, `rehookPunch`, `freezeStamp`, `colorFlash`, `karaoke`, `loopBridge`)
- `reels-hf/templates/tpl_shock.html`
- `reels-hf/templates/tpl_character.html`
- `reels-hf/templates/tpl_markets.html`
- `reels-hf/templates/tpl_analysis.html`
- `tts_align.py` — whisper.cpp wrapper, returns `[{word, start, end}]`
- `tests/test_tts_align.py`
- `tests/test_render_reel_hf.py`
- `tests/fixtures/reel_spec_phase1.json` — minimum ReelSpec used in tests

**Modified:**
- `render_reel_hf.py` — template selection by `template_variant`, alignment call, karaoke JSON injection, lock semantics preserved
- `reels_generator.py` — emit `template_variant`, `hook` dict, `cta` dict, `rehook` dict (with sensible defaults; full LLM choice is Phase 2)
- `reels-hf/CLAUDE.md` — document the four-template selection rule and the interrupts library

**Untouched on purpose:** `gen_tts_sol.py` (voice-profile changes are Phase 2), the dashboard (`sol_dashboard_api.py`), the publish flow (`publish_service.py`, `news_to_reel.py`).

**Existing template kept as fallback:** `reels-hf/templates/reel.html` stays in place. If `template_variant` is missing/unknown, the renderer falls back to it. This avoids breaking any in-flight reel that's already in the publish queue.

---

## Task 1 — Branch hygiene + whisper.cpp install

**Files:**
- Create: `vendor/whisper.cpp/` (build output directory)

- [ ] **Step 1: Confirm working branch is clean and based on main**

Run: `git -C /root/x-bot status -sb && git -C /root/x-bot log --oneline -3`
Expected: branch `feat/reels-engagement-overhaul` ahead of main by 1 commit (the spec).

- [ ] **Step 2: Install whisper.cpp**

Run:
```bash
cd /root && git clone https://github.com/ggerganov/whisper.cpp.git vendor-whisper-cpp
cd vendor-whisper-cpp && make -j4
bash ./models/download-ggml-model.sh small.en
```
Expected: builds `./main` binary at `/root/vendor-whisper-cpp/main`. Model file `models/ggml-small.en.bin` downloads (~466 MB).

- [ ] **Step 3: Smoke-test whisper.cpp on an existing TTS asset**

Run:
```bash
cd /root/vendor-whisper-cpp && ./main -m models/ggml-small.en.bin \
  -f /root/x-bot/sol-bot/reels-hf/assets/tts_trump_test.mp3 \
  --output-json --max-len 1 -of /tmp/whisper-smoke 2>&1 | tail -5
ls -la /tmp/whisper-smoke.json && python3 -c "import json; d=json.load(open('/tmp/whisper-smoke.json')); print('segments:', len(d.get('transcription', [])))"
```
Expected: writes `/tmp/whisper-smoke.json` with at least 5 segments, each containing `offsets` (start_ms, end_ms) and `text`. `--max-len 1` forces one-word-per-segment output.

- [ ] **Step 4: Record the install paths in `.env.example`** (if present)

If `.env.example` exists, append:
```
# Phase 1 — Trash-edit reels
WHISPER_CPP_MAIN=/root/vendor-whisper-cpp/main
WHISPER_CPP_MODEL=/root/vendor-whisper-cpp/models/ggml-small.en.bin
```
If no `.env.example` is committed, skip (the actual `.env` is configured in Task 7).

- [ ] **Step 5: Commit**

```bash
cd /root/x-bot && git add -A
git commit -m "chore(reels): install whisper.cpp for word alignment

Phase 1 prep: install whisper.cpp to /root/vendor-whisper-cpp with the
small.en model. Smoke-tested against an existing TTS asset; produces
word-level timestamps via --max-len 1 + --output-json.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

Note: whisper.cpp builds outside the repo (`/root/vendor-whisper-cpp`), so this commit is paths/docs only. Adjust `git add` accordingly if `.env.example` was modified.

---

## Task 2 — `tts_align.py` (TDD)

**Files:**
- Create: `tts_align.py`
- Test: `tests/test_tts_align.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tts_align.py`:
```python
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
        prefix = None
        argv = args[0] if args else kwargs.get("args", [])
        for i, a in enumerate(argv):
            if a == "-of":
                prefix = argv[i + 1]
        assert prefix, "tts_align must pass -of <prefix>"
        Path(prefix + ".json").write_text(fake_whisper_json.read_text())
        return mock.Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("tts_align.subprocess.run", fake_run)
    monkeypatch.setenv("WHISPER_CPP_MAIN", "/fake/main")
    monkeypatch.setenv("WHISPER_CPP_MODEL", "/fake/model")

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
    monkeypatch.setenv("TTS_ALIGN_CACHE_DIR", str(tmp_path / "cache"))

    align_words(audio)
    align_words(audio)

    assert calls["n"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/x-bot/sol-bot && python3 -m pytest tests/test_tts_align.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tts_align'`.

- [ ] **Step 3: Implement `tts_align.py`**

Create `tts_align.py`:
```python
"""tts_align.py — word-level timestamps from a TTS audio file.

Wraps whisper.cpp (local). Returns a list of AlignWord(word, start, end).
Caches results by audio file hash so re-renders are free.

Used by render_reel_hf to drive karaoke captions in the trash-edit templates.
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
    start: float  # seconds from start of audio
    end: float


def _cache_dir() -> Path:
    custom = os.environ.get("TTS_ALIGN_CACHE_DIR")
    if custom:
        d = Path(custom)
    else:
        d = Path(__file__).resolve().parent / ".tts_align_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _audio_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _parse_whisper_json(payload: dict) -> list[AlignWord]:
    out: list[AlignWord] = []
    for seg in payload.get("transcription", []):
        offsets = seg.get("offsets") or {}
        word = (seg.get("text") or "").strip()
        if not word:
            continue
        start_ms = offsets.get("from")
        end_ms = offsets.get("to")
        if start_ms is None or end_ms is None:
            continue
        # Strip trailing punctuation but keep the rendered word readable.
        word_clean = word.strip().strip(".,;:!?")
        if not word_clean:
            continue
        out.append(AlignWord(
            word=word_clean,
            start=float(start_ms) / 1000.0,
            end=float(end_ms) / 1000.0,
        ))
    return out


def align_words(audio_path: Path) -> list[AlignWord]:
    """Return word-level timestamps for audio_path, or [] if whisper unavailable."""
    main = os.environ.get("WHISPER_CPP_MAIN")
    model = os.environ.get("WHISPER_CPP_MODEL")
    if not main or not model:
        logger.info("WHISPER_CPP_MAIN/MODEL not set; skipping alignment")
        return []
    if not Path(main).exists() or not Path(model).exists():
        logger.warning("whisper.cpp binary or model missing; skipping alignment")
        return []
    if not audio_path.exists():
        logger.warning("Audio missing: %s", audio_path)
        return []

    cache_key = _audio_hash(audio_path)
    cache_file = _cache_dir() / f"{cache_key}.json"
    if cache_file.exists():
        try:
            return [AlignWord(**w) for w in json.loads(cache_file.read_text())]
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("align cache corrupt (%s); re-running whisper", e)

    with tempfile.TemporaryDirectory() as tmpd:
        prefix = str(Path(tmpd) / "whisper")
        cmd = [
            main, "-m", model, "-f", str(audio_path),
            "--output-json", "--max-len", "1", "-of", prefix,
            "-l", "en", "-nt",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.warning("whisper.cpp failed (%d): %s", result.returncode,
                           result.stderr[-300:])
            return []
        json_path = Path(prefix + ".json")
        if not json_path.exists():
            logger.warning("whisper.cpp wrote no JSON")
            return []
        words = _parse_whisper_json(json.loads(json_path.read_text()))

    cache_file.write_text(json.dumps([w.__dict__ for w in words]))
    return words
```

- [ ] **Step 4: Run tests**

Run: `cd /root/x-bot/sol-bot && python3 -m pytest tests/test_tts_align.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tts_align.py tests/test_tts_align.py
git commit -m "feat(reels): add tts_align — whisper.cpp word-level alignment

Phase 1: drives karaoke captions. Caches by audio hash so re-renders are
free. Returns [] when whisper.cpp is unavailable so the renderer can fall
back gracefully.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3 — Test fixture: minimum ReelSpec

**Files:**
- Create: `tests/fixtures/reel_spec_phase1.json`

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures/reel_spec_phase1.json`:
```json
{
  "reel_id": "fixture_phase1",
  "label": "BREAKING",
  "hook": {
    "variant": "shock",
    "text": "OIL JUMPS TO $120 OVERNIGHT",
    "tts_lead": "Oil prices jumped to one hundred twenty dollars overnight."
  },
  "rehook": {
    "text": "20% of the world's oil flows through one strait.",
    "interrupt_kind": "zoom_punch"
  },
  "beats": [
    {"t": 2.0, "type": "stat", "text": "17 million barrels per day pass through Hormuz",
     "emphasis_words": ["17", "million"]},
    {"t": 7.5, "type": "contradiction", "text": "There is no formal blockade in place",
     "emphasis_words": ["no", "blockade"]},
    {"t": 11.0, "type": "twist", "text": "Iran has threatened this for 40+ years",
     "emphasis_words": ["40"]}
  ],
  "cta": {
    "variant": "comment_bait",
    "text": "Real blockade or political theater?",
    "tts_close": "Real blockade or political theater?"
  },
  "voice_profile": "urgent",
  "tts_text": "Oil prices jumped to one hundred twenty dollars overnight. Twenty percent of the world's oil flows through one strait. Real blockade or political theater?",
  "template_variant": "shock",
  "background": "grok_01.mp4",
  "stat1": "17M barrels/day pass through Hormuz",
  "stat2": "No formal US blockade in place",
  "stat3": "Iran threatened this for 40+ years",
  "body": "17M barrels/day pass through Hormuz · No formal US blockade in place",
  "rhetorical_move": "data_card_5beat",
  "topic_tag": "iran",
  "numeric_highlights": ["$120", "20%"],
  "suggested_bg": "grok_01.mp4",
  "suggested_bg_score": 0,
  "caption": "Test fixture caption."
}
```

- [ ] **Step 2: Verify the JSON parses**

Run: `cd /root/x-bot/sol-bot && python3 -c "import json; json.load(open('tests/fixtures/reel_spec_phase1.json')); print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/reel_spec_phase1.json
git commit -m "test(reels): add Phase 1 ReelSpec fixture

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4 — Shared interrupt library (`_interrupts.js`)

**Files:**
- Create: `reels-hf/templates/_interrupts.js`

- [ ] **Step 1: Write `_interrupts.js`**

Create `reels-hf/templates/_interrupts.js`:
```javascript
/**
 * _interrupts.js — shared trash-edit pattern interrupts for Phase 1 templates.
 *
 * Templates include this via a <script src="_interrupts.js"></script> after GSAP
 * is loaded. Functions add tweens to a passed-in GSAP timeline.
 *
 * Hyperframes constraint: deterministic only. No Date.now(), no Math.random().
 */
(function (global) {
  /** Microcut: 60ms black flash + tiny scale punch on #bg at time t. */
  function microcut(tl, t, opts = {}) {
    const flash = opts.flashSelector || "#cut-flash";
    const bg = opts.bgSelector || "#bg";
    const scaleFrom = opts.scaleFrom ?? 1.0;
    const scaleTo = opts.scaleTo ?? 1.06;
    tl.to(flash, { opacity: 1, duration: 0.04, ease: "power1.out" }, t);
    tl.to(flash, { opacity: 0, duration: 0.06, ease: "power1.in" }, t + 0.04);
    tl.to(
      bg,
      { scale: scaleTo, duration: 0.08, yoyo: true, repeat: 1,
        ease: "power2.inOut", overwrite: "auto" },
      t,
    );
    void scaleFrom; // referenced for opts shape; default applied via gsap.set in template
  }

  /** Rehook punch at second 5: bg zooms, rehook stamp slides up. */
  function rehookPunch(tl, t, opts = {}) {
    const bg = opts.bgSelector || "#bg";
    const stamp = opts.stampSelector || "#rehook-stamp";
    tl.to(bg, { scale: 1.18, duration: 0.4, ease: "back.out(2)" }, t);
    tl.to(bg, { scale: 1.05, duration: 0.4, ease: "power2.inOut" }, t + 0.4);
    tl.fromTo(
      stamp,
      { y: 200, opacity: 0 },
      { y: 0, opacity: 1, duration: 0.35, ease: "back.out(2.4)" },
      t + 0.05,
    );
    tl.to(stamp, { opacity: 0, duration: 0.3, ease: "power2.in" }, t + 2.6);
  }

  /** Freeze stamp: pause #bg video for `hold` seconds with a text overlay. */
  function freezeStamp(tl, t, hold, stampSelector) {
    tl.call(() => {
      const v = document.querySelector("#bg");
      if (v && typeof v.pause === "function") v.pause();
    }, [], t);
    tl.to(stampSelector, { opacity: 1, scale: 1.0, duration: 0.12 }, t);
    tl.to(stampSelector, { opacity: 0, duration: 0.2 }, t + hold);
    tl.call(() => {
      const v = document.querySelector("#bg");
      if (v && typeof v.play === "function") v.play();
    }, [], t + hold);
  }

  /** Color flash: full-screen colored div fades in/out at peak. */
  function colorFlash(tl, t, color = "rgba(255,40,40,0.55)") {
    const flash = "#color-flash";
    tl.set(flash, { backgroundColor: color }, t);
    tl.to(flash, { opacity: 0.55, duration: 0.06, ease: "power1.out" }, t);
    tl.to(flash, { opacity: 0, duration: 0.18, ease: "power1.in" }, t + 0.06);
  }

  /**
   * Karaoke captions: scale + color the active word.
   * words = [{word, start, end}, ...]
   * Container #karaoke holds <span data-i="N">word</span> elements (rendered server-side).
   */
  function karaoke(tl, words) {
    if (!words || !words.length) return;
    words.forEach((w, i) => {
      const sel = `#karaoke span[data-i="${i}"]`;
      tl.set(sel, { color: "#ffd500", scale: 1.15, opacity: 1.0 }, w.start);
      tl.set(sel, { color: "#ffffff", scale: 1.0, opacity: 0.55 }, w.end);
    });
  }

  /**
   * Loop bridge: cross-fade last frame's hook block and the first frame's badge
   * during the final 1s, so the loop reads as continuous.
   */
  function loopBridge(tl, durationSec, opts = {}) {
    const tStart = durationSec - 1.0;
    const hook = opts.hookSelector || "#hook";
    const badge = opts.badgeSelector || "#badge";
    tl.to(hook, { opacity: 0.15, duration: 0.6, ease: "power2.in" }, tStart);
    tl.fromTo(
      badge,
      { scale: 1, opacity: 1 },
      { scale: 0.55, opacity: 0.0, duration: 0.4, ease: "power2.in" },
      tStart + 0.4,
    );
  }

  global.SolInterrupts = { microcut, rehookPunch, freezeStamp, colorFlash, karaoke, loopBridge };
})(window);
```

- [ ] **Step 2: Verify the file is syntactically valid JS**

Run: `node --check /root/x-bot/sol-bot/reels-hf/templates/_interrupts.js && echo OK`
Expected: prints `OK`.

- [ ] **Step 3: Commit**

```bash
git add reels-hf/templates/_interrupts.js
git commit -m "feat(reels): add shared trash-edit interrupt library

microcut, rehookPunch, freezeStamp, colorFlash, karaoke, loopBridge — used
by all four Phase 1 templates. All deterministic per Hyperframes constraint.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5 — Shared CSS (`_shared.css`)

**Files:**
- Create: `reels-hf/templates/_shared.css`

- [ ] **Step 1: Write `_shared.css`**

Create `reels-hf/templates/_shared.css`:
```css
/* _shared.css — common chrome for Phase 1 trash-edit templates. */

@font-face {
  font-family: "Bebas Neue";
  src: url("../assets/BebasNeue-Regular.ttf") format("truetype");
  font-display: block;
}
@font-face {
  font-family: "DM Serif Display";
  src: url("../assets/DMSerifDisplay-Regular.ttf") format("truetype");
  font-display: block;
}

* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { width: 1080px; height: 1920px; overflow: hidden; background: #000; }

#root { position: relative; width: 1080px; height: 1920px; overflow: hidden; }

#bg {
  position: absolute; inset: 0; width: 100%; height: 100%;
  object-fit: cover; transform-origin: center center; z-index: 1;
}

.overlay {
  position: absolute; inset: 0; z-index: 2;
  background: linear-gradient(to bottom,
    rgba(0,0,0,0.25) 0%, rgba(0,0,0,0.55) 45%, rgba(0,0,0,0.7) 100%);
}

#cut-flash, #color-flash {
  position: absolute; inset: 0; z-index: 90;
  pointer-events: none; opacity: 0;
  background: #000;
}

.badge {
  position: absolute; top: 220px; left: 50%; transform: translateX(-50%);
  background: #b41e1e; color: #fff;
  font-family: "Bebas Neue", sans-serif; font-size: 40px; letter-spacing: 4px;
  padding: 14px 32px; border-radius: 4px;
  display: flex; align-items: center; gap: 14px; z-index: 20;
}
.badge::before {
  content: ""; width: 14px; height: 14px; border-radius: 50%; background: #fff;
}

#rehook-stamp {
  position: absolute; left: 60px; right: 60px; top: 920px;
  background: rgba(0,0,0,0.78); padding: 22px 28px; border-left: 6px solid #ffd500;
  font-family: "Bebas Neue", sans-serif; font-size: 56px; line-height: 1.05;
  color: #ffd500; letter-spacing: 1px; opacity: 0; z-index: 25;
  text-shadow: 2px 2px 8px rgba(0,0,0,0.85);
}

#karaoke {
  position: absolute; left: 60px; right: 60px; bottom: 320px;
  font-family: "Bebas Neue", sans-serif; font-size: 64px; line-height: 1.1;
  text-align: center; letter-spacing: 1.5px; z-index: 30;
  text-shadow: 3px 3px 10px rgba(0,0,0,0.85);
}
#karaoke span {
  display: inline-block; margin: 0 8px; color: #ffffff; opacity: 0.55;
  transform-origin: center center;
}

.brand {
  position: absolute; top: 1740px; left: 50%; transform: translateX(-50%);
  text-align: center; font-family: "Bebas Neue", sans-serif;
  color: #ffffff; letter-spacing: 4px; z-index: 20;
}
.brand-name { font-size: 38px; line-height: 1.1; }
.brand-tag { font-size: 20px; opacity: 0.7; margin-top: 6px; letter-spacing: 6px; }

.alarm-strip {
  position: absolute; pointer-events: none; z-index: 100;
}
.alarm-strip-top {
  top: 0; left: 0; right: 0; height: 12px;
  background: linear-gradient(to bottom, #ff0020 0%, #c80018 100%);
  box-shadow: 0 0 28px rgba(255,0,30,0.8);
}
.alarm-strip-bottom {
  bottom: 0; left: 0; right: 0; height: 12px;
  background: linear-gradient(to top, #ff0020 0%, #c80018 100%);
  box-shadow: 0 0 28px rgba(255,0,30,0.8);
}
```

- [ ] **Step 2: Commit**

```bash
git add reels-hf/templates/_shared.css
git commit -m "feat(reels): add shared CSS for Phase 1 templates

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6 — Template `tpl_shock.html`

**Files:**
- Create: `reels-hf/templates/tpl_shock.html`

- [ ] **Step 1: Write `tpl_shock.html`**

Create `reels-hf/templates/tpl_shock.html`:
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <link rel="stylesheet" href="_shared.css" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <script src="_interrupts.js"></script>
    <style>
      .hook-shock {
        position: absolute; left: 60px; right: 60px; top: 600px;
        font-family: "Bebas Neue", sans-serif; font-size: 140px;
        line-height: 0.95; color: #ffffff; letter-spacing: 1px;
        text-align: center; z-index: 22;
        text-shadow: 6px 6px 18px rgba(0,0,0,0.95);
      }
      .hook-shock .num {
        color: #ffd500; font-size: 200px; display: block; margin-top: 12px;
      }
    </style>
  </head>
  <body>
    <div id="root"
      data-composition-id="ReelShock"
      data-start="0" data-duration="15" data-fps="30"
      data-width="1080" data-height="1920">

      <video id="bg" class="clip"
        data-start="0" data-duration="15" data-track-index="0"
        src="../assets/{{BG}}" muted playsinline></video>

      <div class="overlay"></div>

      <div class="alarm-strip alarm-strip-top"></div>
      <div class="alarm-strip alarm-strip-bottom"></div>

      <div class="badge" id="badge">{{LABEL}}</div>
      <div class="hook-shock" id="hook">{{HOOK_HTML}}</div>
      <div id="rehook-stamp">{{REHOOK}}</div>
      <div id="karaoke">{{KARAOKE_HTML}}</div>

      <div id="cut-flash"></div>
      <div id="color-flash"></div>

      <div class="brand">
        <div class="brand-name">THE CLAM LETTER</div>
        <div class="brand-tag">POLITICAL COMMENTARY</div>
      </div>

      <audio id="tts" class="clip"
        data-start="0.4" data-duration="14.5" data-track-index="9"
        data-volume="1.0" src="../assets/{{TTS}}"></audio>
      <audio id="music" class="clip"
        data-start="0" data-duration="15" data-track-index="10"
        data-volume="0.25" src="../assets/this_is_news_baked.mp3"></audio>
      <audio id="sfx-open" class="clip"
        data-start="0" data-duration="2" data-track-index="11"
        data-volume="1.0" src="../assets/sfx/open_impact.wav"></audio>
      <audio id="sfx-loop" class="clip"
        data-start="14.5" data-duration="0.5" data-track-index="12"
        data-volume="0.8" src="../assets/sfx/loop_thump.wav"></audio>
    </div>

    <script>
      window.__timelines = window.__timelines || {};
      const tl = gsap.timeline({ paused: true });
      const I = window.SolInterrupts;

      gsap.set("#bg", { scale: 1.05 });
      gsap.set("#badge", { scale: 0.4, opacity: 0 });
      gsap.set("#hook", { opacity: 0, y: 60 });
      gsap.set("#cut-flash", { opacity: 0 });
      gsap.set("#color-flash", { opacity: 0, backgroundColor: "rgba(255,40,40,0.5)" });

      // Entrance 0–1.2s
      tl.to("#badge", { scale: 1, opacity: 1, duration: 0.4, ease: "back.out(2.5)" }, 0);
      tl.to("#hook", { opacity: 1, y: 0, duration: 0.5, ease: "power3.out" }, 0.25);

      // Trash-edit interrupts
      [2.0, 4.0, 6.0, 9.0, 12.0].forEach((t) => I.microcut(tl, t));
      I.rehookPunch(tl, 5.0);

      // Color flash on each emphasis word time (server fills array)
      const EMPHASIS_TIMES = {{EMPHASIS_TIMES_JSON}};
      EMPHASIS_TIMES.forEach((t) => I.colorFlash(tl, t));

      // Karaoke
      const WORDS = {{KARAOKE_WORDS_JSON}};
      I.karaoke(tl, WORDS);

      // Loop bridge
      I.loopBridge(tl, 15.0);

      window.__timelines["ReelShock"] = tl;
    </script>
  </body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add reels-hf/templates/tpl_shock.html
git commit -m "feat(reels): add tpl_shock — giant centered hook + screen-flash

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7 — Template `tpl_character.html`

**Files:**
- Create: `reels-hf/templates/tpl_character.html`

- [ ] **Step 1: Write `tpl_character.html`**

Create `reels-hf/templates/tpl_character.html`:
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <link rel="stylesheet" href="_shared.css" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <script src="_interrupts.js"></script>
    <style>
      #freeze-stamp {
        position: absolute; left: 50%; top: 600px; transform: translateX(-50%);
        font-family: "Bebas Neue", sans-serif; font-size: 80px; color: #ff3b3b;
        background: rgba(0,0,0,0.85); padding: 18px 36px; border: 4px solid #ff3b3b;
        letter-spacing: 4px; opacity: 0; z-index: 30;
        text-shadow: 2px 2px 8px rgba(0,0,0,0.9);
      }
      .quote {
        position: absolute; left: 60px; right: 60px; top: 1100px;
        font-family: "DM Serif Display", serif; font-size: 78px; line-height: 1.1;
        color: #ffffff; z-index: 22;
        text-shadow: 4px 4px 14px rgba(0,0,0,0.9);
      }
      .quote::before { content: "\""; font-size: 110px; color: #ffd500; line-height: 0; vertical-align: -0.4em; }
    </style>
  </head>
  <body>
    <div id="root"
      data-composition-id="ReelCharacter"
      data-start="0" data-duration="15" data-fps="30"
      data-width="1080" data-height="1920">

      <video id="bg" class="clip"
        data-start="0" data-duration="15" data-track-index="0"
        src="../assets/{{BG}}" muted playsinline></video>

      <div class="overlay"></div>
      <div class="alarm-strip alarm-strip-top"></div>
      <div class="alarm-strip alarm-strip-bottom"></div>

      <div class="badge" id="badge">{{LABEL}}</div>
      <div id="freeze-stamp">WHAT HE SAID:</div>
      <div class="quote" id="hook">{{HOOK}}</div>
      <div id="rehook-stamp">{{REHOOK}}</div>
      <div id="karaoke">{{KARAOKE_HTML}}</div>

      <div id="cut-flash"></div>
      <div id="color-flash"></div>

      <div class="brand">
        <div class="brand-name">THE CLAM LETTER</div>
        <div class="brand-tag">POLITICAL COMMENTARY</div>
      </div>

      <audio id="tts" class="clip"
        data-start="0.4" data-duration="14.5" data-track-index="9"
        data-volume="1.0" src="../assets/{{TTS}}"></audio>
      <audio id="music" class="clip"
        data-start="0" data-duration="15" data-track-index="10"
        data-volume="0.22" src="../assets/this_is_news_baked.mp3"></audio>
      <audio id="sfx-loop" class="clip"
        data-start="14.5" data-duration="0.5" data-track-index="12"
        data-volume="0.8" src="../assets/sfx/loop_thump.wav"></audio>
    </div>

    <script>
      window.__timelines = window.__timelines || {};
      const tl = gsap.timeline({ paused: true });
      const I = window.SolInterrupts;

      gsap.set("#bg", { scale: 1.0 });
      gsap.set("#badge", { scale: 0.4, opacity: 0 });
      gsap.set("#hook", { opacity: 0, x: -100 });
      gsap.set("#freeze-stamp", { opacity: 0, scale: 0.8 });
      gsap.set("#cut-flash", { opacity: 0 });
      gsap.set("#color-flash", { opacity: 0, backgroundColor: "rgba(255,40,40,0.5)" });

      tl.to("#badge", { scale: 1, opacity: 1, duration: 0.4, ease: "back.out(2.5)" }, 0);
      I.freezeStamp(tl, 1.8, 0.45, "#freeze-stamp");
      tl.to("#hook", { opacity: 1, x: 0, duration: 0.5, ease: "power3.out" }, 2.3);

      [3.5, 5.0, 7.5, 10.5, 13.0].forEach((t) => I.microcut(tl, t));
      I.rehookPunch(tl, 5.0);

      const EMPHASIS_TIMES = {{EMPHASIS_TIMES_JSON}};
      EMPHASIS_TIMES.forEach((t) => I.colorFlash(tl, t, "rgba(255,213,0,0.45)"));

      const WORDS = {{KARAOKE_WORDS_JSON}};
      I.karaoke(tl, WORDS);

      I.loopBridge(tl, 15.0);

      window.__timelines["ReelCharacter"] = tl;
    </script>
  </body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add reels-hf/templates/tpl_character.html
git commit -m "feat(reels): add tpl_character — freeze-frame + quote layout

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8 — Template `tpl_markets.html`

**Files:**
- Create: `reels-hf/templates/tpl_markets.html`

- [ ] **Step 1: Write `tpl_markets.html`**

Create `reels-hf/templates/tpl_markets.html`:
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <link rel="stylesheet" href="_shared.css" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <script src="_interrupts.js"></script>
    <style>
      .ticker {
        position: absolute; left: 0; right: 0; bottom: 60px;
        background: #000; color: #00ff88;
        font-family: "Bebas Neue", sans-serif; font-size: 44px;
        padding: 12px 40px; letter-spacing: 3px; z-index: 24;
        white-space: nowrap; overflow: hidden;
      }
      .big-num {
        position: absolute; left: 60px; right: 60px; top: 700px;
        font-family: "Bebas Neue", sans-serif;
        font-size: 320px; line-height: 0.9; color: #ffd500;
        text-align: center; z-index: 23;
        text-shadow: 6px 6px 24px rgba(0,0,0,0.95);
      }
      .hook-line {
        position: absolute; left: 60px; right: 60px; top: 1080px;
        font-family: "Bebas Neue", sans-serif; font-size: 70px; line-height: 1.05;
        color: #ffffff; text-align: center; z-index: 22;
        text-shadow: 4px 4px 14px rgba(0,0,0,0.9);
      }
    </style>
  </head>
  <body>
    <div id="root"
      data-composition-id="ReelMarkets"
      data-start="0" data-duration="15" data-fps="30"
      data-width="1080" data-height="1920">

      <video id="bg" class="clip"
        data-start="0" data-duration="15" data-track-index="0"
        src="../assets/{{BG}}" muted playsinline></video>

      <div class="overlay"></div>
      <div class="alarm-strip alarm-strip-top"></div>
      <div class="alarm-strip alarm-strip-bottom"></div>

      <div class="badge" id="badge">{{LABEL}}</div>
      <div class="big-num" id="bignum">{{BIG_NUM}}</div>
      <div class="hook-line" id="hook">{{HOOK}}</div>
      <div id="rehook-stamp">{{REHOOK}}</div>
      <div id="karaoke">{{KARAOKE_HTML}}</div>
      <div class="ticker" id="ticker">{{TICKER_TEXT}}</div>

      <div id="cut-flash"></div>
      <div id="color-flash"></div>

      <div class="brand">
        <div class="brand-name">THE CLAM LETTER</div>
        <div class="brand-tag">MARKETS</div>
      </div>

      <audio id="tts" class="clip"
        data-start="0.4" data-duration="14.5" data-track-index="9"
        data-volume="1.0" src="../assets/{{TTS}}"></audio>
      <audio id="music" class="clip"
        data-start="0" data-duration="15" data-track-index="10"
        data-volume="0.22" src="../assets/this_is_news_baked.mp3"></audio>
      <audio id="sfx-loop" class="clip"
        data-start="14.5" data-duration="0.5" data-track-index="12"
        data-volume="0.8" src="../assets/sfx/loop_thump.wav"></audio>
    </div>

    <script>
      window.__timelines = window.__timelines || {};
      const tl = gsap.timeline({ paused: true });
      const I = window.SolInterrupts;

      gsap.set("#bg", { scale: 1.0 });
      gsap.set("#badge", { scale: 0.4, opacity: 0 });
      gsap.set("#bignum", { opacity: 0, scale: 0.4 });
      gsap.set("#hook", { opacity: 0, y: 40 });
      gsap.set("#ticker", { x: 1080 });
      gsap.set("#cut-flash", { opacity: 0 });
      gsap.set("#color-flash", { opacity: 0, backgroundColor: "rgba(0,255,136,0.4)" });

      tl.to("#badge", { scale: 1, opacity: 1, duration: 0.4, ease: "back.out(2.5)" }, 0);
      tl.to("#bignum", { opacity: 1, scale: 1, duration: 0.55, ease: "back.out(2.2)" }, 0.6);
      tl.to("#hook", { opacity: 1, y: 0, duration: 0.45, ease: "power3.out" }, 1.0);
      tl.to("#ticker", { x: -1080, duration: 14, ease: "linear" }, 1.0);

      [3.0, 5.0, 8.0, 11.0, 13.5].forEach((t) => I.microcut(tl, t));
      I.rehookPunch(tl, 5.0);

      const EMPHASIS_TIMES = {{EMPHASIS_TIMES_JSON}};
      EMPHASIS_TIMES.forEach((t) => I.colorFlash(tl, t, "rgba(0,255,136,0.4)"));

      const WORDS = {{KARAOKE_WORDS_JSON}};
      I.karaoke(tl, WORDS);

      I.loopBridge(tl, 15.0);

      window.__timelines["ReelMarkets"] = tl;
    </script>
  </body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add reels-hf/templates/tpl_markets.html
git commit -m "feat(reels): add tpl_markets — big number + ticker layout

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9 — Template `tpl_analysis.html`

**Files:**
- Create: `reels-hf/templates/tpl_analysis.html`

- [ ] **Step 1: Write `tpl_analysis.html`**

Create `reels-hf/templates/tpl_analysis.html`:
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <link rel="stylesheet" href="_shared.css" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <script src="_interrupts.js"></script>
    <style>
      .top-half {
        position: absolute; top: 0; left: 0; right: 0; height: 960px;
        overflow: hidden; z-index: 1;
      }
      #bg { /* re-target to top-half */
        position: absolute; inset: 0; width: 100%; height: 100%;
        object-fit: cover;
      }
      .bottom-half {
        position: absolute; top: 960px; left: 0; right: 0; height: 960px;
        background: #0a0a0a; z-index: 5;
      }
      .takeaway {
        position: absolute; left: 60px; right: 60px; top: 1080px;
        font-family: "Bebas Neue", sans-serif; font-size: 92px; line-height: 1.0;
        color: #ffffff; letter-spacing: 1px; z-index: 22;
      }
      .divider {
        position: absolute; left: 60px; right: 60px; top: 1000px;
        height: 4px; background: #ffd500; z-index: 22;
      }
    </style>
  </head>
  <body>
    <div id="root"
      data-composition-id="ReelAnalysis"
      data-start="0" data-duration="15" data-fps="30"
      data-width="1080" data-height="1920">

      <div class="top-half">
        <video id="bg" class="clip"
          data-start="0" data-duration="15" data-track-index="0"
          src="../assets/{{BG}}" muted playsinline></video>
        <div class="overlay"></div>
      </div>
      <div class="bottom-half"></div>

      <div class="alarm-strip alarm-strip-top"></div>
      <div class="alarm-strip alarm-strip-bottom"></div>

      <div class="badge" id="badge">{{LABEL}}</div>
      <div class="divider"></div>
      <div class="takeaway" id="hook">{{HOOK}}</div>
      <div id="rehook-stamp">{{REHOOK}}</div>
      <div id="karaoke">{{KARAOKE_HTML}}</div>

      <div id="cut-flash"></div>
      <div id="color-flash"></div>

      <div class="brand">
        <div class="brand-name">THE CLAM LETTER</div>
        <div class="brand-tag">ANALYSIS</div>
      </div>

      <audio id="tts" class="clip"
        data-start="0.4" data-duration="14.5" data-track-index="9"
        data-volume="1.0" src="../assets/{{TTS}}"></audio>
      <audio id="music" class="clip"
        data-start="0" data-duration="15" data-track-index="10"
        data-volume="0.20" src="../assets/this_is_news_baked.mp3"></audio>
      <audio id="sfx-loop" class="clip"
        data-start="14.5" data-duration="0.5" data-track-index="12"
        data-volume="0.7" src="../assets/sfx/loop_thump.wav"></audio>
    </div>

    <script>
      window.__timelines = window.__timelines || {};
      const tl = gsap.timeline({ paused: true });
      const I = window.SolInterrupts;

      gsap.set("#bg", { scale: 1.0 });
      gsap.set("#badge", { scale: 0.4, opacity: 0 });
      gsap.set("#hook", { opacity: 0, y: 50 });
      gsap.set("#cut-flash", { opacity: 0 });
      gsap.set("#color-flash", { opacity: 0, backgroundColor: "rgba(255,213,0,0.35)" });

      tl.to("#badge", { scale: 1, opacity: 1, duration: 0.4, ease: "back.out(2.5)" }, 0);
      tl.to("#hook", { opacity: 1, y: 0, duration: 0.55, ease: "power3.out" }, 0.5);

      // Analysis is more restrained — fewer cuts, gentler scale
      [4.0, 8.0, 12.0].forEach((t) =>
        I.microcut(tl, t, { scaleTo: 1.04 })
      );
      I.rehookPunch(tl, 5.0);

      const EMPHASIS_TIMES = {{EMPHASIS_TIMES_JSON}};
      EMPHASIS_TIMES.forEach((t) => I.colorFlash(tl, t, "rgba(255,213,0,0.35)"));

      const WORDS = {{KARAOKE_WORDS_JSON}};
      I.karaoke(tl, WORDS);

      I.loopBridge(tl, 15.0);

      window.__timelines["ReelAnalysis"] = tl;
    </script>
  </body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add reels-hf/templates/tpl_analysis.html
git commit -m "feat(reels): add tpl_analysis — split-screen restrained layout

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10 — Renderer integration in `render_reel_hf.py` (TDD)

**Files:**
- Modify: `render_reel_hf.py`
- Test: `tests/test_render_reel_hf.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_render_reel_hf.py`:
```python
"""Tests for render_reel_hf template selection + payload prep.

Subprocess invocations are mocked; we verify the inputs sent to the
Hyperframes renderer, not the actual ffmpeg output.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

import render_reel_hf as rrhf
from tts_align import AlignWord


@pytest.fixture
def fixture_spec() -> dict:
    p = Path(__file__).parent / "fixtures" / "reel_spec_phase1.json"
    return json.loads(p.read_text())


def test_select_template_uses_template_variant(fixture_spec):
    """Template variant 'shock' → tpl_shock.html."""
    assert rrhf._select_template(fixture_spec) == "tpl_shock.html"

    s = dict(fixture_spec, template_variant="character")
    assert rrhf._select_template(s) == "tpl_character.html"

    s = dict(fixture_spec, template_variant="markets")
    assert rrhf._select_template(s) == "tpl_markets.html"

    s = dict(fixture_spec, template_variant="analysis")
    assert rrhf._select_template(s) == "tpl_analysis.html"


def test_select_template_falls_back_to_legacy(fixture_spec):
    """Unknown / missing variant → legacy reel.html."""
    s = dict(fixture_spec); s.pop("template_variant", None)
    assert rrhf._select_template(s) == "reel.html"

    s = dict(fixture_spec, template_variant="bogus_value")
    assert rrhf._select_template(s) == "reel.html"


def test_emphasis_times_from_words(fixture_spec):
    """Emphasis word time = the start of the matching aligned word."""
    words = [
        AlignWord("Twenty", 1.0, 1.3),
        AlignWord("percent", 1.3, 1.7),
        AlignWord("of", 1.7, 1.85),
        AlignWord("the", 1.85, 1.95),
        AlignWord("worlds", 1.95, 2.2),
        AlignWord("oil", 2.2, 2.4),
        AlignWord("17", 4.0, 4.3),
        AlignWord("million", 4.3, 4.8),
        AlignWord("barrels", 4.8, 5.3),
    ]
    times = rrhf._emphasis_times(fixture_spec, words)
    # spec emphasis_words include "17", "million", "no", "blockade", "40"
    # only "17" and "million" are present in this aligned set
    assert 4.0 in times
    assert 4.3 in times
    assert all(isinstance(t, float) for t in times)


def test_render_payload_substitutions(fixture_spec, tmp_path, monkeypatch):
    """_build_payload must render {{HOOK}}, {{LABEL}}, {{TTS}}, {{BG}},
    {{REHOOK}}, {{KARAOKE_HTML}}, {{EMPHASIS_TIMES_JSON}}, {{KARAOKE_WORDS_JSON}}."""
    words = [AlignWord("Hello", 0.1, 0.4), AlignWord("world", 0.5, 0.9)]
    payload = rrhf._build_payload(fixture_spec, words=words, tts_filename="tts_x.mp3")
    assert payload["LABEL"] == "BREAKING"
    assert "OIL JUMPS" in payload["HOOK"]
    assert payload["BG"] == "grok_01.mp4"
    assert payload["TTS"] == "tts_x.mp3"
    assert payload["REHOOK"].startswith("20%")
    karaoke_html = payload["KARAOKE_HTML"]
    assert 'data-i="0"' in karaoke_html and "Hello" in karaoke_html
    times = json.loads(payload["EMPHASIS_TIMES_JSON"])
    assert isinstance(times, list)
    words_json = json.loads(payload["KARAOKE_WORDS_JSON"])
    assert words_json[0]["word"] == "Hello"
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd /root/x-bot/sol-bot && python3 -m pytest tests/test_render_reel_hf.py -v`
Expected: FAIL with `AttributeError` on `_select_template` / `_build_payload` / `_emphasis_times`.

- [ ] **Step 3: Modify `render_reel_hf.py`**

Add the helper functions and integrate them. Open `render_reel_hf.py` and:

(a) Add to imports (top of file):
```python
from tts_align import AlignWord, align_words
```

(b) After `DEFAULT_BG = "grok_01.mp4"`, add:
```python
TEMPLATE_BY_VARIANT = {
    "shock": "tpl_shock.html",
    "character": "tpl_character.html",
    "markets": "tpl_markets.html",
    "analysis": "tpl_analysis.html",
}
LEGACY_TEMPLATE = "reel.html"
TEMPLATES_DIR = REELS_HF_DIR / "templates"


def _select_template(spec: dict) -> str:
    variant = (spec.get("template_variant") or "").lower()
    return TEMPLATE_BY_VARIANT.get(variant, LEGACY_TEMPLATE)


def _emphasis_times(spec: dict, words: list[AlignWord]) -> list[float]:
    """For each emphasis_word in any beat, find the first aligned word that
    matches (case-insensitive, punctuation-stripped) and emit its start time."""
    targets: list[str] = []
    for beat in spec.get("beats") or []:
        for w in beat.get("emphasis_words") or []:
            if isinstance(w, str) and w.strip():
                targets.append(w.strip().lower())
    times: list[float] = []
    for tgt in targets:
        for aw in words:
            if aw.word.lower() == tgt:
                times.append(aw.start)
                break
    return times


def _karaoke_html(words: list[AlignWord]) -> str:
    if not words:
        return ""
    spans = []
    for i, w in enumerate(words):
        # Escape minimally — words are short and from our own TTS text.
        safe = (w.word or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        spans.append(f'<span data-i="{i}">{safe}</span>')
    return " ".join(spans)


def _build_payload(spec: dict, words: list[AlignWord], tts_filename: str) -> dict:
    hook = spec.get("hook")
    if isinstance(hook, dict):
        hook_text = hook.get("text", "")
    else:
        hook_text = str(hook or "")

    rehook = spec.get("rehook")
    if isinstance(rehook, dict):
        rehook_text = rehook.get("text", "")
    else:
        rehook_text = ""

    return {
        "LABEL": spec.get("label", "BREAKING"),
        "HOOK": hook_text,
        "HOOK_HTML": hook_text,
        "REHOOK": rehook_text,
        "BG": spec.get("background") or DEFAULT_BG,
        "TTS": tts_filename,
        "BIG_NUM": (spec.get("numeric_highlights") or [""])[0],
        "TICKER_TEXT": spec.get("topic_tag", "").upper() + "  •  THE CLAM LETTER  •  ",
        "KARAOKE_HTML": _karaoke_html(words),
        "EMPHASIS_TIMES_JSON": json.dumps(_emphasis_times(spec, words)),
        "KARAOKE_WORDS_JSON": json.dumps([w.__dict__ for w in words]),
    }


def _render_template(template_name: str, payload: dict, output_path: Path) -> None:
    src = TEMPLATES_DIR / template_name
    if not src.exists():
        # Fall back to legacy index.html / template if templates dir doesn't have it
        src = REELS_HF_DIR / template_name
    if not src.exists():
        raise FileNotFoundError(f"Template not found: {template_name}")
    text = src.read_text(encoding="utf-8")
    for k, v in payload.items():
        text = text.replace("{{" + k + "}}", str(v))
    output_path.write_text(text, encoding="utf-8")
```

(c) Modify the body of `render_reel(...)`. Replace the existing block from `# 1. Write the JSON the renderer reads` through `# 3. Render via Hyperframes` with:

```python
        # 1. Generate TTS narration
        tts_text = copy_data.get("tts_text", "").strip()
        if not tts_text:
            logger.warning("No tts_text in copy_data; reel will have no narration")
            tts_path = None
        else:
            tts_path = generate_tts_for_reel(reel_id, tts_text)
            logger.info("Generated TTS: %s", tts_path.name)

        # 2. Word-level alignment for karaoke captions (best-effort)
        words: list[AlignWord] = []
        if tts_path is not None:
            try:
                words = align_words(tts_path)
            except Exception as e:
                logger.warning("align_words failed (continuing without karaoke): %s", e)
                words = []

        # 3. Pick template + render index.html for Hyperframes to consume
        template_name = _select_template(copy_data)
        payload = _build_payload(
            copy_data,
            words=words,
            tts_filename=tts_path.name if tts_path else "",
        )
        index_path = REELS_HF_DIR / "index.html"
        _render_template(template_name, payload, index_path)
        logger.info("Rendered template %s → index.html (%d words aligned)",
                    template_name, len(words))

        # 4. Render via Hyperframes (subprocess to keep the npx process isolated)
        logger.info("Starting Hyperframes render for reel %s ...", reel_id)
        start = time.time()
        result = subprocess.run(
            ["npx", "hyperframes", "render", "-o", str(output_mp4)],
            cwd=REELS_HF_DIR,
            capture_output=True, text=True, timeout=600,
        )
        elapsed = time.time() - start
```

Note: this swaps from the previous `python render_reel.py <json>` subprocess to `npx hyperframes render` since templates now live in `templates/` and we render `index.html` directly. If the existing repo uses a Python wrapper, keep that wrapper but point it at `index.html` — the key is that `_render_template` produces the file Hyperframes consumes.

(d) Remove the now-unused helper `_write_news_json` (delete it) — JSON-payload approach is replaced by template substitution.

(e) Add `import json` at the top if not already present (`json` is already imported in the existing file).

- [ ] **Step 4: Run tests until they pass**

Run: `cd /root/x-bot/sol-bot && python3 -m pytest tests/test_render_reel_hf.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `cd /root/x-bot/sol-bot && python3 -m pytest tests/ -v`
Expected: existing 21 tests still pass + new tests pass.

- [ ] **Step 6: Commit**

```bash
git add render_reel_hf.py tests/test_render_reel_hf.py
git commit -m "feat(reels): wire trash-edit templates into render_reel_hf

- _select_template picks from template_variant, falls back to legacy reel.html
- _build_payload substitutes hook/rehook/bg/tts/karaoke/emphasis vars
- align_words integration runs whisper.cpp once per render, cached by audio hash
- legacy _write_news_json removed (templates use {{VAR}} substitution)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11 — Generator: emit minimum Phase 1 fields

**Files:**
- Modify: `reels_generator.py`
- Test: extend existing test or add `tests/test_reels_generator_phase1.py`

- [ ] **Step 1: Write the test**

Create `tests/test_reels_generator_phase1.py`:
```python
"""Phase 1 generator additions: template_variant + hook dict + rehook + cta."""
from __future__ import annotations

from unittest import mock

import reels_generator as rg


@mock.patch("reels_generator._call_api")
@mock.patch("reels_generator._get_client")
def test_generate_emits_phase1_fields(get_client, call_api):
    get_client.return_value = (mock.Mock(), False)
    call_api.return_value = (
        '{"label":"BREAKING","hook":"OIL JUMPS","stat1":"x","stat2":"y","stat3":"z",'
        '"tts_text":"Breaking. Oil jumped.",'
        '"caption":"' + ("a" * 600) + '",'
        '"numeric_highlights":["$120"]}'
    )

    spec = rg.generate_reel_copy(
        {"title": "Oil jumps to 120", "summary": "stuff", "source": "wire"},
        label="BREAKING",
    )

    # Backwards compat fields preserved
    assert spec["hook"] == "OIL JUMPS" or isinstance(spec["hook"], dict)
    assert spec["stat1"] == "x"
    assert spec["caption"]

    # New Phase 1 fields present (with defaults if LLM didn't supply)
    assert "template_variant" in spec
    assert spec["template_variant"] in {"shock", "character", "markets", "analysis"}
    assert "rehook" in spec and isinstance(spec["rehook"], dict)
    assert "cta" in spec and isinstance(spec["cta"], dict)
    # beats list mirrors stats for backwards compat
    assert isinstance(spec.get("beats"), list)
    assert len(spec["beats"]) == 3


@mock.patch("reels_generator._call_api")
@mock.patch("reels_generator._get_client")
def test_template_variant_defaults_by_label(get_client, call_api):
    get_client.return_value = (mock.Mock(), False)
    call_api.return_value = (
        '{"label":"ANALYSIS","hook":"x","stat1":"a","stat2":"b","stat3":"c",'
        '"tts_text":"y","caption":"' + ("z" * 600) + '","numeric_highlights":[]}'
    )

    spec = rg.generate_reel_copy({"title": "t", "summary": "", "source": ""}, label="ANALYSIS")
    assert spec["template_variant"] == "analysis"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /root/x-bot/sol-bot && python3 -m pytest tests/test_reels_generator_phase1.py -v`
Expected: FAIL — `template_variant` / `rehook` / `cta` / `beats` not in result.

- [ ] **Step 3: Modify `reels_generator.py`**

In `reels_generator.py`, after the existing `result = {...}` dictionary build (around line 257) and before the `suggested_bg` lines, add:

```python
    # === Phase 1: minimum trash-edit fields with safe defaults ===
    # template_variant — Phase 1 picks by label; Phase 2 will let the LLM choose.
    label_to_template = {
        "BREAKING": "shock",
        "DEVELOPING": "shock",
        "ANALYSIS": "analysis",
        "MARKETS": "markets",
    }
    result["template_variant"] = label_to_template.get(label_norm, "shock")

    # hook dict (Phase 1: derived from existing hook string)
    result["hook_block"] = {
        "variant": "shock",
        "text": hook,
        "tts_lead": tts_text.split(".")[0] + "." if "." in tts_text else tts_text,
    }
    # NOTE: keep top-level "hook" as a string for v2-dashboard compat. Render
    # uses spec["hook"] OR spec["hook_block"]["text"] — see render_reel_hf._build_payload.

    # rehook (Phase 1: stat2 doubles as rehook text; Phase 2 generates dedicated copy)
    result["rehook"] = {
        "text": stat2 or stat1 or "",
        "interrupt_kind": "zoom_punch",
    }

    # cta (Phase 1 placeholder — Phase 2 generates real comment-bait/share-trigger)
    result["cta"] = {
        "variant": "comment_bait",
        "text": "",
        "tts_close": "",
    }

    # beats list — Phase 1 mirrors stat1/2/3 with default timings
    result["beats"] = [
        {"t": 2.0, "type": "stat", "text": stat1, "emphasis_words": []},
        {"t": 5.0, "type": "stat", "text": stat2, "emphasis_words": []},
        {"t": 9.0, "type": "stat", "text": stat3, "emphasis_words": []},
    ]
```

Also: in `_build_payload` in `render_reel_hf.py`, allow either `spec["hook"]` (string) or `spec["hook_block"]["text"]`. The existing code already handles dict-or-string; verify no change needed there — if `spec["hook"]` stays a string, `_build_payload` reads it correctly.

- [ ] **Step 4: Run tests**

Run: `cd /root/x-bot/sol-bot && python3 -m pytest tests/test_reels_generator_phase1.py tests/test_render_reel_hf.py -v`
Expected: all pass.

- [ ] **Step 5: Run full suite**

Run: `cd /root/x-bot/sol-bot && python3 -m pytest tests/ -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add reels_generator.py tests/test_reels_generator_phase1.py
git commit -m "feat(reels): generator emits Phase 1 ReelSpec fields

template_variant / rehook / cta / beats — defaults derived from existing
copy fields. Phase 2 will replace defaults with LLM-produced content.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12 — Hyperframes lint + manual smoke render

**Files:** none (verification only)

- [ ] **Step 1: Lint each new template**

Run:
```bash
cd /root/x-bot/sol-bot/reels-hf && \
  for tpl in templates/tpl_*.html; do
    echo "=== $tpl ==="
    cp "$tpl" index.html.lint-tmp && mv index.html.lint-tmp index.html.lint
    # Hyperframes lint reads index.html — substitute placeholders with neutral values first
    sed -e 's/{{LABEL}}/BREAKING/g' \
        -e 's/{{HOOK}}/Test hook/g' \
        -e 's/{{HOOK_HTML}}/Test hook/g' \
        -e 's/{{REHOOK}}/Test rehook/g' \
        -e 's/{{BG}}/grok_01.mp4/g' \
        -e 's/{{TTS}}/tts_trump_test.mp3/g' \
        -e 's/{{BIG_NUM}}/$120/g' \
        -e 's/{{TICKER_TEXT}}/IRAN \xe2\x80\xa2 OIL/g' \
        -e 's|{{KARAOKE_HTML}}|<span data-i="0">Test</span>|g' \
        -e 's/{{EMPHASIS_TIMES_JSON}}/[]/g' \
        -e 's/{{KARAOKE_WORDS_JSON}}/[]/g' \
        index.html.lint > index.html
    npx hyperframes lint || echo "LINT FAILED for $tpl"
  done
rm -f index.html.lint
```
Expected: zero errors per template. Warnings about unused `data-track-index` are OK.

- [ ] **Step 2: Manual smoke render of one template using the fixture**

Run:
```bash
cd /root/x-bot/sol-bot && python3 -c "
import json, logging
logging.basicConfig(level=logging.INFO)
from render_reel_hf import render_reel
spec = json.load(open('tests/fixtures/reel_spec_phase1.json'))
# Force a real-ish bg the assets dir actually has
spec['background'] = 'grok_01.mp4'
spec['template_variant'] = 'shock'
spec['tts_text'] = 'Breaking. Oil prices jumped to one hundred twenty dollars overnight. Twenty percent of the worlds oil flows through one strait. Real blockade or political theater?'
out = render_reel(spec, reel_id='smoke_phase1', bg='grok_01.mp4')
print(out)
" 2>&1 | tail -20
ls -la /root/x-bot/sol-bot/media/reel_smoke_phase1.mp4
```
Expected: MP4 exists, ≥ 1 MB, ≤ 90s wall-clock.

- [ ] **Step 3: Verify the MP4 is valid**

Run: `ffprobe -v error -show_entries stream=codec_name,width,height,duration -of default=nw=1 /root/x-bot/sol-bot/media/reel_smoke_phase1.mp4`
Expected: `codec_name=h264`, `width=1080`, `height=1920`, `duration≈15`.

- [ ] **Step 4: Commit (no code changes; document the smoke render)**

```bash
# Append a note to reels-hf/CLAUDE.md
```

Modify `reels-hf/CLAUDE.md` and add a new section before "## Linting":
```markdown
## Phase 1 templates (trash-edit motor)

Four templates live in `templates/`:

| Variant     | File                  | When the generator picks it |
|-------------|-----------------------|------------------------------|
| `shock`     | `tpl_shock.html`      | BREAKING / DEVELOPING (default) |
| `character` | `tpl_character.html`  | Quote-driven pieces          |
| `markets`   | `tpl_markets.html`    | MARKETS label                |
| `analysis`  | `tpl_analysis.html`   | ANALYSIS label               |

`render_reel_hf._select_template` reads `spec["template_variant"]` and falls
back to legacy `reel.html` if the value is missing or unknown.

Shared: `templates/_shared.css` and `templates/_interrupts.js`. The interrupts
library exposes `microcut`, `rehookPunch`, `freezeStamp`, `colorFlash`,
`karaoke`, `loopBridge` on `window.SolInterrupts`.

Karaoke captions need `tts_align.align_words(tts_path)` to return non-empty.
That requires whisper.cpp at `$WHISPER_CPP_MAIN` with model `$WHISPER_CPP_MODEL`.
If unavailable, captions just don't animate (graceful degradation).
```

Commit:
```bash
git add reels-hf/CLAUDE.md
git commit -m "docs(reels): document Phase 1 template selection rules

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13 — Ship: open PR

**Files:** none

- [ ] **Step 1: Push branch**

Run: `cd /root/x-bot && git push -u origin feat/reels-engagement-overhaul`
Expected: branch pushed.

- [ ] **Step 2: Open PR against main**

Run:
```bash
gh pr create --base main --head feat/reels-engagement-overhaul \
  --title "feat(reels): Phase 1 — trash-edit motor" \
  --body "$(cat <<'EOF'
## Summary
- Replaces single static reel template with four trash-edit variants (`shock`, `character`, `markets`, `analysis`).
- Adds shared `_interrupts.js` GSAP library: microcuts, rehook punch at 5s, freeze stamps, color flashes, karaoke captions, loop bridge.
- Adds `tts_align.py` (whisper.cpp wrapper) for word-level karaoke timing — cached by audio hash.
- Generator now emits Phase 1 ReelSpec fields (`template_variant`, `rehook`, `cta`, `beats`) with backwards-compatible defaults.
- Legacy `reel.html` kept as fallback for unknown / missing `template_variant`.

Spec: `docs/superpowers/specs/2026-05-06-reels-engagement-overhaul-design.md`
Plan: `docs/superpowers/plans/2026-05-06-reels-phase1-trash-edit-motor.md`

## Test plan
- [ ] `pytest tests/ -v` → all pass
- [ ] `npx hyperframes lint` → zero errors on each `tpl_*.html`
- [ ] Smoke render via `tests/fixtures/reel_spec_phase1.json` → valid 15s 1080x1920 H.264 MP4 in ≤ 90s
- [ ] Side-by-side comparison: same headline through current pipeline (legacy `reel.html`) and new pipeline (`tpl_shock`)
- [ ] Confirm whisper.cpp installed at `/root/vendor-whisper-cpp/main` with `models/ggml-small.en.bin`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
Expected: PR URL printed.

---

## Self-review notes

**Spec coverage check:**
- §5.1 (Templates): Tasks 6-9 — ✅
- §5.2 (Pattern interrupts): Task 4 (`_interrupts.js`) — ✅
- §5.3 (Karaoke alignment): Tasks 1, 2 — ✅
- §5.4 (Files touched): Tasks 4-11 cover all NEW + MODIFIED entries — ✅
- §5.5 (Acceptance): Task 12 covers lint + smoke render + render time + lock semantics (preserved by leaving `_acquire_lock`/`_release_lock` calls intact) — ✅
- DELETE of `.bak` files — DEFERRED: spec says "after phase 1 ships and we have one good week of metrics". Not part of Phase 1 plan. ✅

**Type consistency check:** `AlignWord` is `dataclass(frozen=True)` with `word/start/end` — used the same way in tests, `_emphasis_times`, `_karaoke_html`, `_build_payload`. `_select_template` always returns a string. `template_variant` values are the four strings: `shock | character | markets | analysis`. Consistent throughout.

**Placeholder scan:** no TBD/TODO. Every step has concrete code or commands.
