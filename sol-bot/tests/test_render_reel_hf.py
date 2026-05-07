"""Tests for render_reel_hf template selection + payload prep."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import render_reel_hf as rrhf
from tts_align import AlignWord


@pytest.fixture
def fixture_spec() -> dict:
    p = Path(__file__).parent / "fixtures" / "reel_spec_phase1.json"
    return json.loads(p.read_text())


def test_select_template_uses_template_variant(fixture_spec):
    assert rrhf._select_template(fixture_spec) == "tpl_shock.html"

    s = dict(fixture_spec, template_variant="character")
    assert rrhf._select_template(s) == "tpl_character.html"

    s = dict(fixture_spec, template_variant="markets")
    assert rrhf._select_template(s) == "tpl_markets.html"

    s = dict(fixture_spec, template_variant="analysis")
    assert rrhf._select_template(s) == "tpl_analysis.html"


def test_select_template_falls_back_for_unknown(fixture_spec):
    s = dict(fixture_spec); s.pop("template_variant", None)
    assert rrhf._select_template(s) == rrhf.LEGACY_TEMPLATE

    s = dict(fixture_spec, template_variant="bogus_value")
    assert rrhf._select_template(s) == rrhf.LEGACY_TEMPLATE


def test_emphasis_times_matches_aligned_words(fixture_spec):
    """Emphasis word time = the start of the matching aligned word (case-insensitive)."""
    words = [
        AlignWord("Twenty", 1.0, 1.3),
        AlignWord("percent", 1.3, 1.7),
        AlignWord("17", 4.0, 4.3),
        AlignWord("million", 4.3, 4.8),
        AlignWord("barrels", 4.8, 5.3),
    ]
    times = rrhf._emphasis_times(fixture_spec, words)
    # spec emphasis_words = ["17", "million", "no", "blockade", "40"]
    # only "17" and "million" present in this aligned set
    assert 4.0 in times
    assert 4.3 in times
    assert all(isinstance(t, float) for t in times)
    assert len(times) == 2


def test_karaoke_html_chunked_renders_chunks():
    """Words render as <div class='kchunk'> blocks of chunkSize words each."""
    words = [
        AlignWord("Hello", 0.1, 0.4),
        AlignWord("world", 0.5, 0.9),
        AlignWord("again", 1.0, 1.4),
    ]
    html = rrhf._karaoke_html_chunked(words, chunk_size=2)
    assert html.count('class="kchunk"') == 2  # 3 words → 2 chunks
    assert 'data-c="0"' in html and 'data-c="1"' in html
    assert 'class="kw" data-i="0"' in html and "Hello" in html
    assert 'class="kw" data-i="2"' in html and "again" in html


def test_karaoke_html_chunked_empty_for_empty_list():
    assert rrhf._karaoke_html_chunked([]) == ""


def test_split_cta_tail_finds_phrase():
    """The trailing 'Follow The Clam Letter' run is split out as cta_words."""
    words = [
        AlignWord("Threat", 0.0, 0.4),
        AlignWord("with", 0.4, 0.6),
        AlignWord("teeth.", 0.6, 1.0),
        AlignWord("Follow", 10.0, 10.3),
        AlignWord("The", 10.3, 10.5),
        AlignWord("Clam", 10.5, 10.9),
        AlignWord("Letter.", 10.9, 11.4),
    ]
    body, cta = rrhf._split_cta_tail(words)
    assert len(body) == 3
    assert len(cta) == 4
    assert cta[0].word == "Follow"
    assert cta[0].start == 10.0


def test_split_cta_tail_no_match_returns_full_body():
    words = [
        AlignWord("Hello", 0.0, 0.4),
        AlignWord("world", 0.4, 0.8),
    ]
    body, cta = rrhf._split_cta_tail(words)
    assert body == words
    assert cta == []


def test_build_payload_substitutes_all_placeholders(fixture_spec):
    words = [AlignWord("Hello", 0.1, 0.4), AlignWord("world", 0.5, 0.9)]
    payload = rrhf._build_payload(fixture_spec, words=words, tts_filename="tts_x.mp3")
    assert payload["LABEL"] == "BREAKING"
    assert "OIL JUMPS" in payload["HOOK"]
    assert payload["BG"] == "grok_01.mp4"
    assert payload["TTS"] == "tts_x.mp3"
    assert payload["REHOOK"].startswith("20%")
    assert 'class="kw" data-i="0"' in payload["KARAOKE_HTML"]
    assert "kchunk" in payload["KARAOKE_HTML"]
    assert isinstance(json.loads(payload["EMPHASIS_TIMES_JSON"]), list)
    parsed_words = json.loads(payload["KARAOKE_WORDS_JSON"])
    assert parsed_words[0]["word"] == "Hello"
    # CTA fields exist; CTA_TIME is "null" when no CTA in words
    assert payload["CTA_TIME"] == "null"
    assert payload["CTA_TEXT"] == ""


def test_build_payload_extracts_cta_time_when_phrase_present():
    spec = {"label": "BREAKING", "hook": "X", "background": "grok_01.mp4",
            "beats": [], "topic_tag": "x", "numeric_highlights": []}
    words = [
        AlignWord("Hello", 0.1, 0.4),
        AlignWord("world", 0.5, 0.9),
        AlignWord("Follow", 10.0, 10.3),
        AlignWord("The", 10.3, 10.5),
        AlignWord("Clam", 10.5, 10.9),
        AlignWord("Letter.", 10.9, 11.4),
    ]
    payload = rrhf._build_payload(spec, words=words, tts_filename="x.mp3")
    assert payload["CTA_TIME"] == "10.000"
    assert payload["CTA_TEXT"] == "Follow The Clam Letter"
    # Body karaoke excludes the CTA tail
    body_words = json.loads(payload["KARAOKE_WORDS_JSON"])
    assert len(body_words) == 2
    assert all(w["word"] != "Follow" for w in body_words)


def test_build_payload_handles_string_hook():
    """Backwards compat: hook may be a plain string instead of dict."""
    spec = {
        "label": "BREAKING",
        "hook": "PLAIN STRING HOOK",
        "rehook": {"text": "rehook here"},
        "background": "grok_01.mp4",
        "beats": [],
        "topic_tag": "iran",
        "numeric_highlights": [],
    }
    payload = rrhf._build_payload(spec, words=[], tts_filename="x.mp3")
    assert payload["HOOK"] == "PLAIN STRING HOOK"


def test_render_template_substitutes_into_file(fixture_spec, tmp_path, monkeypatch):
    """_render_template reads tpl_shock.html, substitutes placeholders, writes output."""
    # Use the actual on-disk template
    payload = rrhf._build_payload(fixture_spec, words=[], tts_filename="x.mp3")
    out = tmp_path / "out.html"
    rrhf._render_template("tpl_shock.html", payload, out)
    text = out.read_text(encoding="utf-8")
    assert "{{" not in text or "{{HOOK}}" not in text  # no leftover hook placeholders
    assert "OIL JUMPS" in text
    assert "BREAKING" in text
