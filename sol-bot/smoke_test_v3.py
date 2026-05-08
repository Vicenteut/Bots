#!/usr/bin/env python3
"""Smoke test for the v3 reel pipeline (dispatcher + generator + Hyperframes + DB)."""
import json
import os
import sys

sys.path.insert(0, ".")

# Load .env
with open(".env") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

# Force v3 path
os.environ["REELS_COPY_GENERATOR"] = "v3"
os.environ["REELS_RENDERER"] = "v3"

import news_to_reel  # noqa: E402

print(f"REELS_COPY_GENERATOR = {news_to_reel.REELS_COPY_GENERATOR}")
print(f"REELS_RENDERER       = {news_to_reel.REELS_RENDERER}")
print()

print("=== STEP 1: Generate copy via dispatcher ===")
copy = news_to_reel.generate_reel_copy({
    "title": "US Central Command requests deployment of hypersonic missiles to Middle East for possible use against Iran",
    "summary": "CENTCOM made a formal request for the most advanced US missile system to be deployed in the region",
    "source": "Reuters",
})
preview = {k: v for k, v in copy.items() if k != "caption"}
print(json.dumps(preview, indent=2, ensure_ascii=False))
print(f"\ncaption length: {len(copy.get('caption') or '')} chars")

print("\n=== STEP 2: Render reel (this will take 2-4 min) ===")
result = news_to_reel.render_reel(
    copy, alert_id="test_v3_smoke", background_filename="grok_01.mp4"
)
print(json.dumps(result, indent=2))

print("\n=== STEP 3: Verify DB row ===")
import sqlite3
con = sqlite3.connect("threads_analytics.db")
con.row_factory = sqlite3.Row
row = con.execute(
    "SELECT reel_id, format_version, hook, stat1, stat2, stat3, tts_path "
    "FROM reels WHERE reel_id = ?",
    (result["reel_id"],),
).fetchone()
con.close()
if row:
    print({k: row[k] for k in row.keys()})
else:
    print("⚠️  No DB row found")
print("\n✅ Smoke test complete.")
