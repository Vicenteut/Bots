#!/usr/bin/env python3
"""
evaluate_posts.py — LLM-as-Judge evaluator for Sol bot posts.
Reads last N posts from analytics.db, scores each on 4 dimensions using
anthropic/claude-sonnet-4-6 via OpenRouter, saves results to evaluation_results.json.
"""

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------------ #
# Paths
# ------------------------------------------------------------------ #
BASE_DIR = Path(__file__).parent
DB_PATH = Path("/root/x-bot/analytics.db")
PROMPT_FILE = BASE_DIR / "sol_post_evaluator_prompt.txt"
OUTPUT_FILE = BASE_DIR / "evaluation_results.json"
HISTORY_FILE = BASE_DIR / "evaluation_history.jsonl"

# ------------------------------------------------------------------ #
# Client setup — mirrors generator.py pattern exactly
# ------------------------------------------------------------------ #
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
EVAL_MODEL = "anthropic/claude-sonnet-4-6"

try:
    from openai import OpenAI as _OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

import anthropic as _anthropic


def _get_client():
    """Returns (client, is_openrouter). Mirrors generator.py _get_client()."""
    or_key = os.getenv("OPENROUTER_API_KEY")
    if or_key and _OPENAI_AVAILABLE:
        client = _OpenAI(api_key=or_key, base_url=OPENROUTER_BASE)
        return client, True
    return _anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")), False


def _call_api(client, system: str, user_msg: str, is_openrouter: bool) -> str:
    """Single API call — handles both OpenRouter and direct Anthropic."""
    if is_openrouter:
        response = client.chat.completions.create(
            model=EVAL_MODEL,
            max_tokens=300,
            temperature=0.1,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
        )
        return response.choices[0].message.content.strip()
    else:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        return response.content[0].text.strip()


# ------------------------------------------------------------------ #
# JSON parsing — strips accidental markdown fences
# ------------------------------------------------------------------ #
def _parse_json(raw: str) -> dict:
    """Parse JSON from model output, stripping any markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # drop first line (```json or ```) and last line (```)
        inner = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
        text = inner.strip()
    return json.loads(text)


# ------------------------------------------------------------------ #
# Evaluate a single post
# ------------------------------------------------------------------ #
REQUIRED_KEYS = {
    "sol_voice", "angle_originality", "rhetorical_move", "closing_impact",
    "move_detected", "total_score", "max_score", "quality_tier", "one_line_verdict",
}
VALID_MOVES = {"Cold Fact Drop", "Buried Lede", "Nobody Noticed", "History Rhyme", "Math Check", "none"}
VALID_TIERS = {"A", "B", "C", "D"}


def _validate(data: dict) -> bool:
    if not REQUIRED_KEYS.issubset(data.keys()):
        return False
    if data.get("move_detected") not in VALID_MOVES:
        return False
    if data.get("quality_tier") not in VALID_TIERS:
        return False
    score = data.get("total_score", 0)
    if not (4 <= score <= 20):
        return False
    return True


def evaluate_post(client, is_or: bool, system_prompt: str, post_text: str) -> dict | None:
    """Evaluate one post. Retries once on failure. Returns None if both attempts fail."""
    for attempt in range(2):
        try:
            raw = _call_api(client, system_prompt, post_text, is_or)
            data = _parse_json(raw)
            if _validate(data):
                return data
            print(f"  [warn] attempt {attempt+1}: invalid structure — {list(data.keys())}")
        except json.JSONDecodeError as e:
            print(f"  [warn] attempt {attempt+1}: JSON parse error — {e}")
        except Exception as e:
            print(f"  [warn] attempt {attempt+1}: API error — {e}")
        if attempt == 0:
            time.sleep(2)
    return None


# ------------------------------------------------------------------ #
# Database
# ------------------------------------------------------------------ #
def fetch_posts(n: int) -> list[dict]:
    """Fetch last N posts ordered by rowid DESC."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT rowid, tweet_id, text FROM tweets WHERE text IS NOT NULL AND text != '' ORDER BY rowid DESC LIMIT ?",
        (n,),
    )
    rows = cur.fetchall()
    conn.close()
    return [{"rowid": r[0], "tweet_id": str(r[1]) if r[1] else None, "text": r[2]} for r in rows]


# ------------------------------------------------------------------ #
# Summary helpers
# ------------------------------------------------------------------ #
def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _distribution(tiers: list[str]) -> dict:
    d = {"A": 0, "B": 0, "C": 0, "D": 0}
    for t in tiers:
        if t in d:
            d[t] += 1
    return d


# ------------------------------------------------------------------ #
# Persistent storage helpers
# ------------------------------------------------------------------ #
def _append_to_history(results: list[dict], evaluated_at: str) -> None:
    """Append one JSON line per result to evaluation_history.jsonl."""
    with HISTORY_FILE.open("a", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps({**r, "evaluated_at": evaluated_at}, ensure_ascii=False) + "\n")


def save_to_db(results: list[dict], evaluated_at: str) -> int:
    """Create post_evaluations table if needed, insert one row per result."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS post_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id TEXT,
            post_text TEXT,
            sol_voice INTEGER,
            angle_originality INTEGER,
            rhetorical_move INTEGER,
            closing_impact INTEGER,
            total_score INTEGER,
            quality_tier TEXT,
            move_detected TEXT,
            one_line_verdict TEXT,
            evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    rows = [
        (
            r.get("tweet_id"),
            r.get("text"),
            r.get("sol_voice"),
            r.get("angle_originality"),
            r.get("rhetorical_move"),
            r.get("closing_impact"),
            r.get("total_score"),
            r.get("quality_tier"),
            r.get("move_detected"),
            r.get("one_line_verdict"),
            evaluated_at,
        )
        for r in results
    ]
    cur.executemany(
        """
        INSERT INTO post_evaluations
          (post_id, post_text, sol_voice, angle_originality, rhetorical_move,
           closing_impact, total_score, quality_tier, move_detected,
           one_line_verdict, evaluated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()
    inserted = cur.rowcount
    conn.close()
    return inserted


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #
def main():
    parser = argparse.ArgumentParser(description="Evaluate Sol bot posts with LLM judge")
    parser.add_argument("--n", type=int, default=20, help="Number of recent posts to evaluate (default: 20)")
    args = parser.parse_args()

    system_prompt = PROMPT_FILE.read_text()
    client, is_or = _get_client()
    backend = "OpenRouter" if is_or else "Anthropic direct"
    print(f"[evaluate_posts] backend={backend} model={EVAL_MODEL} n={args.n}")
    print(f"[evaluate_posts] db={DB_PATH}")

    posts = fetch_posts(args.n)
    print(f"[evaluate_posts] fetched {len(posts)} posts\n")

    results = []
    skipped = 0

    for i, post in enumerate(posts, 1):
        text_preview = post["text"][:60].replace("\n", " ")
        print(f"  [{i:02d}/{len(posts)}] {text_preview}...")
        result = evaluate_post(client, is_or, system_prompt, post["text"])
        if result is None:
            print(f"  [skip] post {i} failed after 2 attempts")
            skipped += 1
            continue
        result["tweet_id"] = post["tweet_id"]
        result["text"] = post["text"]
        results.append(result)
        tier = result["quality_tier"]
        score = result["total_score"]
        move = result["move_detected"]
        print(f"         score={score}/20 tier={tier} move={move}")

    if not results:
        print("\n[error] No posts successfully evaluated.")
        return

    # Aggregate stats
    dim_keys = ["sol_voice", "angle_originality", "rhetorical_move", "closing_impact", "total_score"]
    avg_scores = {k: _avg([r[k] for r in results]) for k in dim_keys}
    quality_dist = _distribution([r["quality_tier"] for r in results])

    # Best / worst by total_score
    best = max(results, key=lambda r: r["total_score"])
    worst = min(results, key=lambda r: r["total_score"])

    # Most common move
    move_counts: dict[str, int] = {}
    for r in results:
        m = r["move_detected"]
        move_counts[m] = move_counts.get(m, 0) + 1
    most_common_move = max(move_counts, key=lambda k: move_counts[k])

    output = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "total_posts": len(results),
        "skipped": skipped,
        "model": EVAL_MODEL,
        "avg_scores": avg_scores,
        "quality_distribution": quality_dist,
        "move_frequency": move_counts,
        "posts": results,
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\n[evaluate_posts] saved {len(results)} results to {OUTPUT_FILE}")

    ts = output["evaluated_at"]
    _append_to_history(results, ts)
    print(f"[evaluate_posts] appended {len(results)} lines to {HISTORY_FILE}")

    inserted = save_to_db(results, ts)
    print(f"[evaluate_posts] inserted {inserted} rows into analytics.db post_evaluations")

    # ----------------------------------------------------------------
    # Stdout summary
    # ----------------------------------------------------------------
    print("\n" + "=" * 60)
    print("SOL POST QUALITY EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Posts evaluated : {len(results)}  |  skipped: {skipped}")
    print(f"Model           : {EVAL_MODEL} via {backend}")
    print()
    print("AVG SCORES PER DIMENSION")
    print(f"  SOL_VOICE          : {avg_scores['sol_voice']:.2f} / 5")
    print(f"  ANGLE_ORIGINALITY  : {avg_scores['angle_originality']:.2f} / 5")
    print(f"  RHETORICAL_MOVE    : {avg_scores['rhetorical_move']:.2f} / 5")
    print(f"  CLOSING_IMPACT     : {avg_scores['closing_impact']:.2f} / 5")
    print(f"  TOTAL              : {avg_scores['total_score']:.2f} / 20")
    print()
    print("QUALITY DISTRIBUTION")
    total_eval = len(results)
    for tier in ["A", "B", "C", "D"]:
        count = quality_dist[tier]
        pct = round(count / total_eval * 100) if total_eval else 0
        bar = "#" * count
        print(f"  {tier}: {count:3d} ({pct:3d}%) {bar}")
    print()
    print("MOST COMMON RHETORICAL MOVE")
    for move, count in sorted(move_counts.items(), key=lambda x: -x[1]):
        print(f"  {move}: {count}")
    print()
    print("BEST POST")
    print(f"  Score: {best['total_score']}/20  Tier: {best['quality_tier']}")
    print(f"  Move: {best['move_detected']}")
    print(f"  Verdict: {best['one_line_verdict']}")
    print(f"  Text: {best['text'][:200]}")
    print()
    print("WORST POST")
    print(f"  Score: {worst['total_score']}/20  Tier: {worst['quality_tier']}")
    print(f"  Move: {worst['move_detected']}")
    print(f"  Verdict: {worst['one_line_verdict']}")
    print(f"  Text: {worst['text'][:200]}")
    print("=" * 60)


if __name__ == "__main__":
    main()
