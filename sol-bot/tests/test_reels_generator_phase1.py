"""Phase 1 generator additions: template_variant, hook_block, rehook, cta, beats."""
from __future__ import annotations

from unittest import mock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

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

    # Backwards compat fields preserved (top-level hook stays a string)
    assert spec["hook"] == "OIL JUMPS"
    assert spec["stat1"] == "x"
    assert spec["caption"]

    # New Phase 1 fields present
    assert "template_variant" in spec
    assert spec["template_variant"] in {"shock", "character", "markets", "analysis"}

    assert "hook_block" in spec and isinstance(spec["hook_block"], dict)
    assert spec["hook_block"]["text"] == "OIL JUMPS"
    assert spec["hook_block"]["variant"] == "shock"

    assert "rehook" in spec and isinstance(spec["rehook"], dict)
    assert "text" in spec["rehook"]
    assert spec["rehook"]["interrupt_kind"] == "zoom_punch"

    assert "cta" in spec and isinstance(spec["cta"], dict)
    assert spec["cta"]["variant"] == "comment_bait"

    # beats list mirrors stats for backwards compat (3 entries)
    assert isinstance(spec.get("beats"), list)
    assert len(spec["beats"]) == 3
    assert spec["beats"][0]["text"] == "x"
    assert spec["beats"][1]["text"] == "y"
    assert spec["beats"][2]["text"] == "z"
    assert spec["beats"][0]["t"] == 2.0
    assert spec["beats"][1]["t"] == 5.0
    assert spec["beats"][2]["t"] == 9.0


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


@mock.patch("reels_generator._call_api")
@mock.patch("reels_generator._get_client")
def test_template_variant_for_markets(get_client, call_api):
    get_client.return_value = (mock.Mock(), False)
    call_api.return_value = (
        '{"label":"MARKETS","hook":"x","stat1":"a","stat2":"b","stat3":"c",'
        '"tts_text":"y","caption":"' + ("z" * 600) + '","numeric_highlights":[]}'
    )

    spec = rg.generate_reel_copy({"title": "t", "summary": "", "source": ""}, label="MARKETS")
    assert spec["template_variant"] == "markets"


@mock.patch("reels_generator._call_api")
@mock.patch("reels_generator._get_client")
def test_rehook_falls_back_to_stat1_if_stat2_empty(get_client, call_api):
    """rehook.text uses stat2 if present, else stat1."""
    get_client.return_value = (mock.Mock(), False)
    call_api.return_value = (
        '{"label":"BREAKING","hook":"H","stat1":"first stat","stat2":"","stat3":"third",'
        '"tts_text":"y","caption":"' + ("z" * 600) + '","numeric_highlights":[]}'
    )

    spec = rg.generate_reel_copy({"title": "t", "summary": "", "source": ""}, label="BREAKING")
    assert spec["rehook"]["text"] == "first stat"
