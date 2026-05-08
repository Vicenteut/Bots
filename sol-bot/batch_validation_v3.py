#!/usr/bin/env python3
"""
batch_validation_v3.py — Generate 3 v3 reels with diverse news for validation.

Tests:
  - LLM stability across topic types (economic, military, political-domestic)
  - Different bg videos (grok_01/02/03)
  - DB rows with format_version='v3_hyperframes'
"""

import json
import os
import sys
import time

sys.path.insert(0, ".")

# Load .env
with open(".env") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

os.environ["REELS_COPY_GENERATOR"] = "v3"
os.environ["REELS_RENDERER"] = "v3"

import news_to_reel  # noqa: E402

NEWS_BATCH = [
    {
        "id": "trump_china_tariffs",
        "headline": {
            "title": "Trump signs executive order doubling tariffs on Chinese imports to 60%, effective immediately",
            "summary": "The order targets electronics, EVs, semiconductors and steel. Beijing pledges immediate retaliation. Markets sell off pre-bell.",
            "source": "Reuters",
        },
        "bg": "grok_01.mp4",
        "label": "BREAKING",
    },
    {
        "id": "putin_mobilization",
        "headline": {
            "title": "Putin orders partial mobilization of 250,000 reservists as Ukraine offensive stalls in eastern Donbas",
            "summary": "Largest call-up since the invasion began. Stock of military-age men in Russia falls. Russian assets hit fresh lows on London exchange.",
            "source": "AP",
        },
        "bg": "grok_02.mp4",
        "label": "BREAKING",
    },
    {
        "id": "netanyahu_coalition",
        "headline": {
            "title": "Netanyahu's coalition collapses as Defense Minister Gallant resigns over Gaza policy disputes",
            "summary": "Israel could face snap elections within 90 days. Shekel weakens. Likud internal vote scheduled for Tuesday.",
            "source": "Times of Israel",
        },
        "bg": "grok_03.mp4",
        "label": "BREAKING",
    },
]


def run_one(item: dict) -> dict:
    print(f"\n{'='*70}\n📰 {item['id']} — bg={item['bg']}\n{'='*70}")
    print(f"  Title: {item['headline']['title'][:80]}")
    t0 = time.time()
    copy = news_to_reel.generate_reel_copy(item["headline"], label=item["label"])
    t_copy = time.time() - t0

    print(f"  ⏱  Copy: {t_copy:.1f}s")
    print(f"  Hook: {copy.get('hook', '')}")
    print(f"  stat1: {copy.get('stat1', '')}")
    print(f"  stat2: {copy.get('stat2', '')}")
    print(f"  stat3: {copy.get('stat3', '')}")
    print(f"  topic: {copy.get('topic_tag', '')}")
    print(f"  TTS chars: {len(copy.get('tts_text', ''))}")

    print("  Rendering ...")
    t1 = time.time()
    result = news_to_reel.render_reel(
        copy,
        alert_id=f"validation_{item['id']}",
        background_filename=item["bg"],
    )
    t_render = time.time() - t1
    print(f"  ⏱  Render: {t_render:.1f}s")
    print(f"  ✅ MP4: {result['local_path']}")
    print(f"  📦 format_version: {result.get('format_version')}")

    return {
        "id": item["id"],
        "reel_id": result["reel_id"],
        "mp4": result["local_path"],
        "thumbnail": result.get("thumbnail_path"),
        "copy_seconds": round(t_copy, 1),
        "render_seconds": round(t_render, 1),
        "topic_tag": copy.get("topic_tag"),
        "hook": copy.get("hook"),
    }


if __name__ == "__main__":
    print(f"REELS_COPY_GENERATOR={news_to_reel.REELS_COPY_GENERATOR}")
    print(f"REELS_RENDERER={news_to_reel.REELS_RENDERER}")
    print(f"Batch size: {len(NEWS_BATCH)}")

    results = []
    overall_t0 = time.time()
    for item in NEWS_BATCH:
        try:
            results.append(run_one(item))
        except Exception as e:
            print(f"  ❌ FAILED: {e}")
            results.append({"id": item["id"], "error": str(e)})

    overall = time.time() - overall_t0
    print(f"\n\n{'='*70}\n📊 SUMMARY ({overall:.0f}s total)\n{'='*70}")
    for r in results:
        if "error" in r:
            print(f"  ❌ {r['id']}: {r['error']}")
        else:
            print(f"  ✅ {r['id']}: {r['mp4']}  ({r['render_seconds']}s, topic={r['topic_tag']})")

    print(f"\n📁 Pull MP4s with:")
    for r in results:
        if "mp4" in r:
            print(f"  scp -P 443 root@89.167.109.62:{r['mp4']} ./")
