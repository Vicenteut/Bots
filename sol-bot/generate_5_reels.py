#!/usr/bin/env python3
"""Phase 1.6 batch — 5 Clam Letter reels, all on tpl_markets at 20s.

Why this batch is different from Phase 1.5:
- Single template (`tpl_markets`) for visual consistency across the feed.
- 20s duration so Mark voice can deliver ≤44 words at natural pace
  without the auto-fit speedup that was desync'ing karaoke in Phase 1.5.
- Per-reel BRAND_TAG / BIG_NUM / TICKER / sub-hook keep each story
  visually distinct inside the same template.

Script structure rules (also captured in gen_tts_sol.py docstring):
  Total 38–44 words, ≤270 chars including CTA.
    1. Opener   (5–8 words)   one declarative
    2. Fact     (8–12 words)  the news
    3. Contrast (8–12 words)  the twist
    4. So-what  (6–10 words)  implication
    5. CTA      (5 words)     "Follow The Clam Letter."
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv("/root/x-bot/.env")
load_dotenv("/root/x-bot/sol-bot/.env")

import render_reel_hf as rrhf  # noqa: E402

DRIVE_FOLDER = "gdrive:Reels para subir"

# Beat positions tuned for the stack-up animation (Phase 1.6.2):
# stamp-1 enters at 4.5, stamp-2 at 9.0 (stamp-1 slides up), stamp-3 at 13.0
# (both prior stamps slide further up). All three visible 13.4–17.0,
# then fade together to make room for the CTA stamp at ~17.5.
BEAT_TS = (4.5, 9.0, 13.0)

NEWS = [
    # 1. Trump · ultimátum tarifario UE  ── markets 20s · grok_01 · ANALYSIS
    {
        "slug": "01_trump_eu_tariffs",
        "spec": {
            "label": "ANALYSIS",
            "brand_tag": "ANALYSIS",
            "template_variant": "markets",
            "duration_sec": 20,
            "background": "grok_01.mp4",
            "topic_tag": "politics",
            "hook": "TRUMP'S DEAL THE COURTS KILLED",
            "gold_word": "KILLED",
            "keyword_words": ["Trump", "Europe", "Supreme", "Court", "tariffs"],
            "rehook": {"text": "SCOTUS GUTTED IEEPA IN FEBRUARY"},
            "numeric_highlights": ["10%"],
            "beats": [
                {"text": "JULY 4 ULTIMATUM",        "t": BEAT_TS[0], "emphasis_words": ["July"]},
                {"text": "EU OFFERED ZERO-FOR-ZERO", "t": BEAT_TS[1], "emphasis_words": ["zero"]},
                {"text": "10% IS THE REAL FLOOR",   "t": BEAT_TS[2], "emphasis_words": ["10"]},
            ],
            # 38 words
            "tts_text": (
                "Trump just told Europe: drop tariffs to zero by July fourth, "
                "or watch them spike. He won't mention this — the Supreme Court "
                "already gutted his tariff authority. The deadline is theater. "
                "Leverage, or show? Follow The Clam Letter."
            ),
        },
        # Markets-template specific overrides used by _build_payload via spec
        "extra_payload": {
            "BIG_NUM": "10%",
            "TICKER_TEXT": "ANALYSIS  •  TRUMP  •  EU TARIFFS  •  THE CLAM LETTER  •  ",
        },
        "social_txt": """=================================================================
  TITLE
=================================================================

Trump's EU Tariff Ultimatum Has a Problem (SCOTUS Already Killed It)

=================================================================
  X / TWITTER
=================================================================

Trump's July 4th tariff ultimatum to the EU has a problem. SCOTUS already gutted his IEEPA authority in February. The EU offered zero-for-zero. Washington refused to drop the 10% floor. Leverage, or theater?

#tariffs #trump

=================================================================
  THREADS
=================================================================

Trump told the EU: drop tariffs to zero by July 4 or face a spike. What he won't mention — the Supreme Court already gutted his IEEPA authority in February. The EU already offered zero-for-zero on manufacturing. Washington wouldn't budge from the 10% baseline. The deadline isn't the deal. It's the show.

— The Clam Letter

=================================================================
  TIKTOK
=================================================================

Trump's tariff ultimatum has one detail he won't mention 👀 SCOTUS already killed it.

#trump #tariffs #eu #scotus #fyp

=================================================================
  INSTAGRAM REELS
=================================================================

Trump's July 4 ultimatum to the EU has a problem: the Supreme Court already nullified his IEEPA tariffs in February. The EU offered zero-for-zero. Washington wouldn't drop the 10% floor. The deadline is theater.

#trump #tariffs #eu #scotus #ieepa #politics #breakingnews #news #commentary #theclamletter

=================================================================
  YOUTUBE SHORTS
=================================================================

Title:    Trump's EU Tariff Ultimatum Has a Problem (SCOTUS Already Killed It)
Tags:     trump, tariffs, eu, ieepa, scotus, politics, breaking news, the clam letter

Description:
Trump told the EU to drop tariffs to zero by July 4 — or face a spike. What's missing from the announcement: the Supreme Court already gutted his IEEPA authority in February, forcing him onto narrower Section 122 grounds. The EU has already offered zero-for-zero on manufacturing; Washington refused to drop the 10% baseline. The deadline isn't the deal. It's the show.

— The Clam Letter
""",
    },

    # 2. US strikes Iran ── markets 20s · khamenei · BREAKING
    {
        "slug": "02_us_strikes_iran",
        "spec": {
            "label": "BREAKING",
            "brand_tag": "BREAKING",
            "template_variant": "markets",
            "duration_sec": 20,
            "background": "khamenei.mp4",
            "topic_tag": "geopolitics",
            "hook": "US BOMBS SOUTHERN IRAN",
            "gold_word": "IRAN",
            "keyword_words": ["US", "Iran", "Bandar", "Qeshm", "ceasefire"],
            "rehook": {"text": "CEASEFIRE IS UNWINDING"},
            "numeric_highlights": ["2"],
            "beats": [
                {"text": "TARGETS STRUCK",          "t": BEAT_TS[0], "emphasis_words": ["struck"]},
                {"text": "BOTH SIDES FIRING AGAIN", "t": BEAT_TS[1], "emphasis_words": ["firing"]},
                {"text": "CEASEFIRE OVER",          "t": BEAT_TS[2], "emphasis_words": ["ceasefire"]},
            ],
            # 36 words
            "tts_text": (
                "Breaking. The US military just struck targets in southern Iran — "
                "Bandar Abbas and Qeshm Port. Both sides are firing again. "
                "The ceasefire that held for weeks is unwinding. "
                "Where does this stop? Follow The Clam Letter."
            ),
        },
        "extra_payload": {
            "BIG_NUM": "HIT",
            "TICKER_TEXT": "BREAKING  •  IRAN  •  HORMUZ  •  THE CLAM LETTER  •  ",
        },
        "social_txt": """=================================================================
  TITLE
=================================================================

US Strikes Southern Iran — Ceasefire Is Unwinding

=================================================================
  X / TWITTER
=================================================================

BREAKING: US military strikes targets in southern Iran — Bandar Abbas and Qeshm Port hit, per Fox News. Both sides have resumed fire. The ceasefire that held for weeks is unwinding.

#iran #breakingnews

=================================================================
  THREADS
=================================================================

The US military just conducted strikes on targets in southern Iran — Bandar Abbas and Iran's Qeshm Port, per Fox News. The US-Iran ceasefire that held for weeks is unwinding after renewed strikes from both sides. Each side is testing how far it can push before the other escalates harder. Where does this stop?

— The Clam Letter

=================================================================
  TIKTOK
=================================================================

The US just bombed southern Iran — and the ceasefire is over.

#iran #usa #breakingnews #geopolitics #fyp

=================================================================
  INSTAGRAM REELS
=================================================================

BREAKING — US military strikes Bandar Abbas and Qeshm Port in southern Iran. The ceasefire that held for weeks is unwinding. Both sides are firing again. Where does this stop?

#iran #usa #bandarabbas #qeshm #breakingnews #geopolitics #middleeast #news #commentary #theclamletter

=================================================================
  YOUTUBE SHORTS
=================================================================

Title:    BREAKING — US Strikes Southern Iran, Ceasefire Is Over
Tags:     iran, usa, breaking news, bandar abbas, qeshm, geopolitics, middle east

Description:
The US military just conducted strikes on Bandar Abbas and Qeshm Port in southern Iran, per Fox News. The US-Iran ceasefire that held for weeks is unwinding after renewed strikes from both sides. Each side is now testing how far it can push the other.

— The Clam Letter
""",
    },

    # 3. WHO hantavirus on cruise ── markets 20s · ancient_map · HEALTH
    {
        "slug": "03_who_hantavirus",
        "spec": {
            "label": "BREAKING",
            "brand_tag": "HEALTH",
            "template_variant": "markets",
            "duration_sec": 20,
            "background": "ancient_map.mp4",
            "topic_tag": "health",
            "hook": "5 SICK · 3 DEAD ON A CRUISE",
            "gold_word": "DEAD",
            "keyword_words": ["WHO", "five", "Three", "Andes", "Hondius"],
            "rehook": {"text": "ANDES STRAIN — RARE HUMAN-TO-HUMAN"},
            "numeric_highlights": ["3"],
            "beats": [
                {"text": "5 SICK · 3 DEAD",                       "t": BEAT_TS[0], "emphasis_words": ["3"]},
                {"text": "ONLY STRAIN THAT SPREADS BETWEEN PEOPLE", "t": BEAT_TS[1], "emphasis_words": ["only"]},
                {"text": "MORE CASES COMING",                      "t": BEAT_TS[2], "emphasis_words": ["more"]},
            ],
            # 36 words
            "tts_text": (
                "WHO confirms five hantavirus cases on the cruise ship Hondius. "
                "Three dead. The strain is Andes — the only one that spreads "
                "between people. More cases are coming. Should you trust the "
                "all-clear? Follow The Clam Letter."
            ),
        },
        "extra_payload": {
            "BIG_NUM": "3",
            "TICKER_TEXT": "HEALTH  •  WHO  •  HANTAVIRUS  •  THE CLAM LETTER  •  ",
        },
        "social_txt": """=================================================================
  TITLE
=================================================================

WHO Confirms Rare Human-to-Human Hantavirus Outbreak on Cruise Ship

=================================================================
  X / TWITTER
=================================================================

WHO confirms 5 hantavirus cases on cruise ship Hondius. 3 dead. The strain is Andes — the only hantavirus that transmits between humans. 6-week incubation means more cases are coming. WHO says risk is low.

#health #breakingnews

=================================================================
  THREADS
=================================================================

WHO just confirmed 5 hantavirus cases on the cruise ship Hondius. 3 are dead. The strain is Andes — the only hantavirus with documented human-to-human transmission. The ship left Argentina April 1 and the incubation period is up to 6 weeks. WHO calls overall risk low. The clock says otherwise.

— The Clam Letter

=================================================================
  TIKTOK
=================================================================

The WHO confirmed something rare on a cruise ship — and it spreads between people.

#hantavirus #cruise #health #news #fyp

=================================================================
  INSTAGRAM REELS
=================================================================

WHO confirms 5 hantavirus cases — 3 dead — on cruise ship Hondius. The strain is Andes, the ONLY hantavirus with documented human-to-human transmission. 6-week incubation. More cases expected.

#hantavirus #andesvirus #cruiseship #who #health #breakingnews #news #publichealth #commentary #theclamletter

=================================================================
  YOUTUBE SHORTS
=================================================================

Title:    WHO Confirms Rare Human-to-Human Hantavirus Outbreak on Cruise Ship
Tags:     hantavirus, who, cruise ship, andes virus, health, breaking news, public health

Description:
WHO confirmed 5 hantavirus cases — 3 dead — aboard the cruise ship MV Hondius. The strain is Andes, the only hantavirus with documented human-to-human transmission. The ship departed Argentina April 1 and the incubation period runs up to 6 weeks, so more cases are likely to surface. WHO calls overall public-health risk low.

— The Clam Letter
""",
    },

    # 4. Iran missile claim vs CENTCOM ── markets 20s · grok_01 · BREAKING
    {
        "slug": "04_iran_missile_centcom",
        "spec": {
            "label": "BREAKING",
            "brand_tag": "BREAKING",
            "template_variant": "markets",
            "duration_sec": 20,
            "background": "grok_01.mp4",
            "topic_tag": "geopolitics",
            "hook": "IRAN: WE HIT A US DESTROYER",
            "gold_word": "DESTROYER",
            "keyword_words": ["Iran", "destroyer", "CENTCOM", "Six", "boats"],
            "rehook": {"text": "CENTCOM: NO US SHIP HAS BEEN STRUCK"},
            "numeric_highlights": ["0"],
            "beats": [
                {"text": "IRAN: WE HIT A DESTROYER",  "t": BEAT_TS[0], "emphasis_words": ["destroyer"]},
                {"text": "CENTCOM: ZERO SHIPS HIT",   "t": BEAT_TS[1], "emphasis_words": ["zero"]},
                {"text": "REAL: 6 IRANIAN BOATS SUNK", "t": BEAT_TS[2], "emphasis_words": ["six"]},
            ],
            # 38 words
            "tts_text": (
                "Iran says it hit a US destroyer in Hormuz. CENTCOM says no Navy "
                "ship was struck. The intercepts were real. The destroyer hit "
                "was not. Six Iranian boats already sunk. "
                "Who do you believe? Follow The Clam Letter."
            ),
        },
        "extra_payload": {
            "BIG_NUM": "0",
            "TICKER_TEXT": "IRAN  •  CENTCOM  •  HORMUZ  •  THE CLAM LETTER  •  ",
        },
        "social_txt": """=================================================================
  TITLE
=================================================================

Iran Claims It Hit a US Destroyer — CENTCOM Says That Never Happened

=================================================================
  X / TWITTER
=================================================================

Iran claims it hit a US destroyer in Hormuz. CENTCOM says no US Navy ship has been struck. The intercepts were real — the destroyer hit was not. 6 Iranian boats sunk by US helicopters during Project Freedom.

#iran #centcom

=================================================================
  THREADS
=================================================================

Iran says it hit a US destroyer in the Strait of Hormuz. CENTCOM denies it — "no US Navy ship has been hit." What's real: cruise missiles, drones, and fast boats fired by Iran during Project Freedom, plus 6 Iranian boats sunk by US Apache helicopters. What's propaganda: the destroyer claim. Read the difference.

— The Clam Letter

=================================================================
  TIKTOK
=================================================================

Iran said it hit a US destroyer. CENTCOM said something different.

#iran #centcom #hormuz #navy #fyp

=================================================================
  INSTAGRAM REELS
=================================================================

Iran claims it hit a US destroyer in Hormuz. CENTCOM denies the strike — no US Navy ship has been struck. The intercepts during Project Freedom WERE real: missiles, drones, fast boats. 6 Iranian boats sunk by US helicopters.

#iran #centcom #hormuz #usnavy #middleeast #breakingnews #geopolitics #news #commentary #theclamletter

=================================================================
  YOUTUBE SHORTS
=================================================================

Title:    Iran Claims It Hit a US Destroyer — CENTCOM Says That Never Happened
Tags:     iran, centcom, hormuz, us navy, breaking news, geopolitics

Description:
Iran says it struck a US destroyer in the Strait of Hormuz. CENTCOM publicly denied any US Navy ship has been hit. What's verified: cruise missiles, drones, and fast boats fired during Project Freedom, plus 6 Iranian boats sunk by US Apache helicopters. The destroyer hit is not.

— The Clam Letter
""",
    },

    # 5. Rubio · $25.8B Middle East arms deal ── markets 20s · rubio · MARKETS
    {
        "slug": "05_rubio_arms_deal",
        "spec": {
            "label": "MARKETS",
            "brand_tag": "MARKETS",
            "template_variant": "markets",
            "duration_sec": 20,
            "background": "rubio.mp4",
            "topic_tag": "politics",
            "hook": "BYPASSED CONGRESS ON ARMS",
            "gold_word": "CONGRESS",
            "keyword_words": ["Rubio", "billion", "Israel", "Congress", "emergency"],
            "rehook": {"text": "THIRD EMERGENCY BYPASS THIS WAR"},
            "numeric_highlights": ["$25.8B"],
            "beats": [
                {"text": "EMERGENCY AUTHORITY INVOKED",  "t": BEAT_TS[0], "emphasis_words": ["emergency"]},
                {"text": "ISRAEL · KUWAIT · QATAR · UAE", "t": BEAT_TS[1], "emphasis_words": ["Israel"]},
                {"text": "ALL FOUR HIT BY IRAN",          "t": BEAT_TS[2], "emphasis_words": ["all"]},
            ],
            # 36 words
            "tts_text": (
                "Rubio just approved twenty-five point eight billion dollars in "
                "Middle East arms sales — bypassing Congress under emergency "
                "authority. Israel. Kuwait. Qatar. UAE. All four hit by Iran "
                "since February. Emergency, or workaround? Follow The Clam Letter."
            ),
        },
        "extra_payload": {
            "BIG_NUM": "$25.8B",
            "TICKER_TEXT": "POLITICS  •  RUBIO  •  ARMS DEAL  •  THE CLAM LETTER  •  ",
        },
        "social_txt": """=================================================================
  TITLE
=================================================================

Rubio Just Bypassed Congress on a $25.8B Middle East Arms Deal

=================================================================
  X / TWITTER
=================================================================

Rubio just approved $25.8B in Middle East arms sales — bypassing Congress under emergency authority. Buyers: Israel, Kuwait, Qatar, UAE. All four hit by Iranian strikes since Feb. Third bypass since the war started.

#rubio #armsdeal

=================================================================
  THREADS
=================================================================

Rubio just approved $25.8 billion in arms sales to the Middle East — bypassing Congress by invoking emergency authority. The buyers: Israel, Kuwait, Qatar, UAE. Each has been hit by Iranian strikes since February. This is the third time the State Department has used the emergency clause for arms in this region since the war started. Emergency, or workaround?

— The Clam Letter

=================================================================
  TIKTOK
=================================================================

$25.8 billion in arms sales — and Congress didn't get a vote.

#rubio #armsdeal #middleeast #congress #fyp

=================================================================
  INSTAGRAM REELS
=================================================================

Rubio just approved $25.8 BILLION in Middle East arms sales — bypassing Congress under emergency authority. Buyers: Israel, Kuwait, Qatar, UAE. All four hit by Iranian strikes since February. Third bypass this war.

#rubio #statedepartment #armsdeal #middleeast #israel #congress #breakingnews #geopolitics #commentary #theclamletter

=================================================================
  YOUTUBE SHORTS
=================================================================

Title:    Rubio Just Bypassed Congress on a $25.8B Middle East Arms Deal
Tags:     rubio, state department, arms deal, middle east, congress, breaking news

Description:
Marco Rubio just approved $25.8 billion in arms sales to Israel, Kuwait, Qatar, and the UAE — bypassing the standard congressional review by invoking emergency authority. All four buyers have been hit by Iranian strikes since February. This is the third time the State Department has used the emergency clause for Middle East arms since the war began.

— The Clam Letter
""",
    },

    # 6. Federal Court of International Trade vacates Trump's 10% Section 122 tariffs
    #    — markets 20s · grok_01 · BREAKING
    {
        "slug": "06_court_kills_tariffs",
        "spec": {
            "label": "BREAKING",
            "brand_tag": "BREAKING",
            "template_variant": "markets",
            "duration_sec": 20,
            "background": "grok_01.mp4",
            "topic_tag": "politics",
            "hook": "TRUMP JUST LOST HIS TARIFFS",
            "gold_word": "LOST",
            "keyword_words": ["Trump", "Court", "struck", "Twenty-four", "Supreme"],
            "rehook": {"text": "24 STATES FILED THE CASE"},
            "numeric_highlights": ["VOID"],
            "beats": [
                {"text": "STRUCK DOWN BY US TRADE COURT", "t": BEAT_TS[0], "emphasis_words": ["struck"]},
                {"text": "FIRST IEEPA · NOW SECTION 122", "t": BEAT_TS[1], "emphasis_words": ["both"]},
                {"text": "BOTH LEGAL LEVERS GONE",        "t": BEAT_TS[2], "emphasis_words": ["gone"]},
            ],
            # 44 words exactly
            "tts_text": (
                "Breaking. The Federal Court of International Trade just struck down "
                "Trump's ten percent global tariffs. Twenty-four states filed the case. "
                "First the Supreme Court killed the IEEPA basis. Now Section 122 is "
                "dead too. Both legal levers gone. What's left? Follow The Clam Letter."
            ),
        },
        "extra_payload": {
            "BIG_NUM": "VOID",
            "TICKER_TEXT": "BREAKING  •  TRUMP  •  COURT RULING  •  THE CLAM LETTER  •  ",
        },
        "social_txt": """=================================================================
  TITLE
=================================================================

BREAKING — Federal Court Strikes Down Trump's 10% Global Tariffs

=================================================================
  X / TWITTER
=================================================================

BREAKING: The Federal Court of International Trade just struck down Trump's 10% global tariffs. 24 states filed the case. First IEEPA, now Section 122 — both legal levers gone.

#trump #tariffs

=================================================================
  THREADS
=================================================================

Breaking — the U.S. Court of International Trade in Manhattan just vacated Trump's 10% global tariffs. 24 mostly Democrat-led states plus a coalition of small businesses brought the case. The court ruled across-the-board duties weren't justified under Section 122 of the 1974 Trade Act, never before used as a tariff basis. This comes months after SCOTUS struck down the IEEPA basis 6-3 in February. Both legal levers — gone. What's left?

— The Clam Letter

=================================================================
  TIKTOK
=================================================================

Trump just lost his 10% tariffs in court — for the second time.

#trump #tariffs #scotus #breakingnews #fyp

=================================================================
  INSTAGRAM REELS
=================================================================

BREAKING — Federal Court of International Trade just struck down Trump's 10% global tariffs. 24 states filed. First IEEPA, now Section 122 — both legal pillars gone.

#trump #tariffs #cit #section122 #ieepa #scotus #politics #breakingnews #news #theclamletter

=================================================================
  YOUTUBE SHORTS
=================================================================

Title:    BREAKING — Federal Court Strikes Down Trump's 10% Global Tariffs
Tags:     trump, tariffs, court of international trade, section 122, ieepa, breaking news

Description:
The U.S. Court of International Trade just vacated Trump's 10% global tariffs after a coalition of 24 mostly Democrat-led states and small businesses sued. The court found across-the-board duties weren't justified under Section 122 of the 1974 Trade Act. This is Trump's second tariff defeat — SCOTUS already struck down his IEEPA basis 6-3 in February.

Sources: Bloomberg, US News, Bloomberg Law, PBS, CIT Slip Op. 25-66.

— The Clam Letter
""",
    },
]


def main():
    Path("media").mkdir(exist_ok=True)
    summary = []

    for i, item in enumerate(NEWS, 1):
        slug = item["slug"]
        # Markets template uses BIG_NUM (the spec field) and TICKER_TEXT (built
        # in _build_payload from spec.topic_tag). We override both via spec
        # before render so each reel reads distinct.
        spec = dict(item["spec"])
        # numeric_highlights[0] becomes BIG_NUM in _build_payload — already set.
        # TICKER_TEXT is built from topic_tag; override by stuffing a custom
        # topic_tag so the rendered ticker matches what we want.
        spec["numeric_highlights"] = [item["extra_payload"]["BIG_NUM"]]
        # TICKER_TEXT is composed as f"{topic_tag.upper()}  •  THE CLAM LETTER  •  "
        # Provide a multi-segment topic_tag string so the ticker reads the
        # full breadcrumb.
        spec["topic_tag"] = item["extra_payload"]["TICKER_TEXT"].replace("  •  THE CLAM LETTER  •  ", "")

        print(f"\n=== {i}/{len(NEWS)}  {slug} ===", flush=True)
        t0 = time.time()
        try:
            result = rrhf.render_reel(spec, reel_id=slug, bg=spec["background"])
        except Exception as e:
            print(f"!! {slug} FAILED: {e}", flush=True)
            summary.append((slug, "FAILED", str(e)))
            continue
        elapsed = time.time() - t0
        mp4 = Path(result["local_path"])
        size_mb = mp4.stat().st_size / 1024 / 1024

        # Companion .txt with platform copy
        txt = mp4.with_suffix(".txt")
        txt.write_text(item["social_txt"], encoding="utf-8")

        # Upload both to Drive
        for src, dest_name in [(mp4, f"clamletter_{slug}.mp4"),
                               (txt, f"clamletter_{slug}.txt")]:
            r = subprocess.run(
                ["rclone", "copyto", str(src), f"{DRIVE_FOLDER}/{dest_name}"],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                print(f"  !! upload failed for {dest_name}: {r.stderr[-200:]}", flush=True)

        print(f"DONE {i}/{len(NEWS)}  {slug}  ({size_mb:.1f}MB, {elapsed:.0f}s)", flush=True)
        summary.append((slug, "OK", f"{size_mb:.1f}MB"))

    print("\n=== summary ===", flush=True)
    for s, status, info in summary:
        print(f"  {status:8s}  {s}  {info}", flush=True)


if __name__ == "__main__":
    main()
