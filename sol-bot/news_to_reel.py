"""
news_to_reel.py — orchestrates the pipeline:
    headline (alert) → REEL copy (generator.generate_reel_copy)
                     → MP4 (gen_news_video.compose_video)
                     → DB row (reels)
                     → publish via network_adapters.{instagram,tiktok,youtube}

Used by:
    - FastAPI endpoints in sol_dashboard_api.py
    - CLI / cron / Telegram commands

Persisted in /root/x-bot/sol-bot/threads_analytics.db (tables: reels, reel_publishes).
Generated MP4s land in /root/x-bot/sol-bot/media/reel_<id>.mp4.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import os
import generator
import gen_news_video
import gen_news_video_v2

# Renderer selector: "v2" (default, Pillow+ffmpeg) | "v1" (legacy) | "v3" (Hyperframes)
REELS_RENDERER = os.getenv("REELS_RENDERER", "v2").lower()
# Copy generator selector: "v2" (default, generator.py: hook+body) | "v3" (reels_generator.py: hook+stats+tts)
REELS_COPY_GENERATOR = os.getenv("REELS_COPY_GENERATOR", "v2").lower()

# Per-platform render durations.
# TikTok algorithm sweet spot is 24-32s; X+IG+YT favour 15-18s. Render once,
# pick correct variant at publish time.
CANONICAL_DURATION_SEC = 18  # base variant; thumbnail and dashboard preview reference this
VARIANT_DURATIONS_BY_NETWORK = {
    "x": 18,
    "instagram": 18,
    "youtube": 18,
    "tiktok": 28,
    "threads": 18,
}
EXTRA_VARIANT_DURATIONS = sorted({d for d in VARIANT_DURATIONS_BY_NETWORK.values() if d != CANONICAL_DURATION_SEC})

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
DB_PATH = ROOT / "threads_analytics.db"
MEDIA_DIR = ROOT / "media"
MEDIA_DIR.mkdir(exist_ok=True)

FFMPEG = Path("/usr/bin/ffmpeg")

VALID_LABELS = {"BREAKING", "DEVELOPING", "ANALYSIS", "MARKETS"}
VALID_NETWORKS = {"instagram", "tiktok", "youtube"}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Copy + render
# ---------------------------------------------------------------------------

def generate_reel_copy(alert: dict, label: str = "BREAKING", format_version: str | None = None) -> dict:
    """
    Dispatcher: routes to v2 generator (hook+body) or v3 reels_generator (hook+stats+tts).

    Resolution order: explicit `format_version` arg > REELS_COPY_GENERATOR env var > "v2".

    Accepts either:
      - alert with 'headline' subdict (monitor_queue format)
      - alert that is itself a headline dict
    """
    headline = alert.get("headline") if isinstance(alert.get("headline"), dict) else alert
    label_norm = (label or "BREAKING").upper()
    if label_norm not in VALID_LABELS:
        label_norm = "BREAKING"

    gen_choice = (format_version or REELS_COPY_GENERATOR or "v2").lower()
    if gen_choice == "v3":
        # Lazy import: don't break v2 if reels_generator has issues
        import reels_generator
        return reels_generator.generate_reel_copy(headline, label=label_norm)
    return generator.generate_reel_copy(headline, label=label_norm)


def _make_thumbnail(video_path: Path, thumb_path: Path, at_seconds: float = 5.0) -> bool:
    cmd = [
        str(FFMPEG), "-y",
        "-ss", str(at_seconds),
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", "scale=540:960",
        str(thumb_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning("Thumbnail extraction failed: %s", result.stderr[-500:])
        return False
    return True


def render_reel(copy: dict, alert_id: str | None = None, duration: int = 18, background_filename: str | None = None, format_version: str | None = None) -> dict:
    """
    Render the MP4 + thumbnail and insert a row in `reels` with status='draft'.

    Renderer dispatched (priority): explicit `format_version` > REELS_RENDERER env > "v2".
      - "v2": gen_news_video_v2 (Pillow + ffmpeg, motion + staggered reveals)
      - "v1": gen_news_video legacy (text card)
      - "v3": render_reel_hf (Hyperframes — requires v3 copy with stat1/2/3/tts_text)
    """
    reel_id = uuid.uuid4().hex[:16]
    out_path = MEDIA_DIR / f"reel_{reel_id}.mp4"
    thumb_path = MEDIA_DIR / f"reel_{reel_id}.jpg"

    renderer_choice = (format_version or REELS_RENDERER or "v2").lower()

    if renderer_choice == "v3":
        # v3: Hyperframes. Requires copy from reels_generator (with stat1/2/3 + tts_text).
        # Force 15s duration — that's what the v3 template targets.
        import render_reel_hf
        bg = background_filename or "grok_01.mp4"
        v3_result = render_reel_hf.render_reel(copy, reel_id=reel_id, bg=bg)
        # render_reel_hf already wrote the MP4 to media/reel_<id>.mp4 so out_path matches.
        if v3_result.get("thumbnail_path"):
            # render_reel_hf already extracted a thumbnail; mirror to thumb_path.
            src_thumb = Path(v3_result["thumbnail_path"])
            if src_thumb.exists() and src_thumb != thumb_path:
                import shutil
                shutil.copy(src_thumb, thumb_path)
        duration = v3_result.get("duration_sec", 15)
    elif renderer_choice == "v2":
        gen_news_video_v2.render_reel_v2(copy, out_path, duration=duration, background_filename=background_filename)
        _make_thumbnail(out_path, thumb_path)
    else:
        card = gen_news_video.render_text_card(
            title=copy["hook"],
            body=copy.get("body", ""),
            label=copy.get("label", "BREAKING"),
        )
        gen_news_video.compose_video(card, out_path, duration=duration)
        _make_thumbnail(out_path, thumb_path)

    # Phase 4: track variants in JSON, but only render the canonical now.
    # Extra-duration variants (e.g. TikTok 28s) are rendered lazily at publish
    # time to avoid Cloudflare's 100s timeout on the synchronous /api/reels/generate call.
    variants = {f"d{duration}": {"path": str(out_path), "duration": duration}}

    # Determine format_version stamp for DB analytics
    format_version_stamp = (
        "v3_hyperframes" if renderer_choice == "v3"
        else "v2_pillow" if renderer_choice == "v2"
        else "v1_legacy"
    )

    # tts_path only exists for v3 reels
    tts_path_str = None
    if renderer_choice == "v3":
        tts_candidate = ROOT / "reels-hf" / "assets" / f"tts_{reel_id}.mp3"
        if tts_candidate.exists():
            tts_path_str = str(tts_candidate)

    with _conn() as c:
        c.execute(
            """
            INSERT INTO reels (
                reel_id, alert_id, hook, body, label, topic_tag, rhetorical_move,
                duration_sec, local_path, thumbnail_path, created_at, numeric_highlights,
                variants, caption, status,
                stat1, stat2, stat3, tts_text, tts_path, format_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?)
            """,
            (
                reel_id,
                alert_id,
                copy["hook"],
                copy.get("body", ""),
                copy.get("label", "BREAKING"),
                copy.get("topic_tag"),
                copy.get("rhetorical_move"),
                duration,
                str(out_path),
                str(thumb_path) if thumb_path.exists() else None,
                _now_iso(),
                json.dumps(copy.get("numeric_highlights") or []),
                json.dumps(variants),
                copy.get("caption") or "",
                copy.get("stat1"),
                copy.get("stat2"),
                copy.get("stat3"),
                copy.get("tts_text"),
                tts_path_str,
                format_version_stamp,
            ),
        )

    # v3-only: upload MP4 + auto-generated .txt to Google Drive (non-blocking).
    # If Drive is unreachable or rclone fails, the reel still exists locally + DB.
    drive_status = None
    if renderer_choice == "v3":
        try:
            from gdrive_upload import upload_reel_to_drive
            drive_status = upload_reel_to_drive(reel_id, out_path, copy, format_version=format_version_stamp)
            if drive_status.get("status") == "uploaded":
                logger.info("Drive upload OK: %s", drive_status["mp4_filename"])
            elif drive_status.get("status") not in {"disabled", "uploaded"}:
                logger.warning("Drive upload skipped/failed: %s", drive_status)
        except Exception as e:
            logger.warning("Drive upload module error (non-blocking): %s", e)

    return {
        "reel_id": reel_id,
        "local_path": str(out_path),
        "thumbnail_path": str(thumb_path) if thumb_path.exists() else None,
        "duration_sec": duration,
        "variants": variants,
        "format_version": format_version_stamp,
        "drive_upload": drive_status,
    }


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------

def _get_adapter(name: str):
    """Lazy-import adapters so missing creds don't break the module load."""
    if name == "instagram":
        from network_adapters.instagram import InstagramAdapter
        return InstagramAdapter()
    if name == "tiktok":
        from network_adapters.tiktok import TikTokAdapter
        return TikTokAdapter()
    if name == "youtube":
        from network_adapters.youtube import YouTubeAdapter
        return YouTubeAdapter()
    raise ValueError(f"Unknown network: {name}")


def _set_status(reel_id: str, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE reels SET status = ? WHERE reel_id = ?", (status, reel_id))


def _record_publish(
    reel_id: str,
    network: str,
    *,
    remote_post_id: str | None,
    permalink: str | None,
    error: str | None,
) -> None:
    with _conn() as c:
        c.execute(
            """
            INSERT INTO reel_publishes
                (reel_id, network_name, remote_post_id, permalink, published_at, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (reel_id, network, remote_post_id, permalink, _now_iso() if remote_post_id else None, error),
        )


def _lazy_render_variant(reel_row, duration: int, background_filename: str | None = None) -> str:
    """Render an on-demand variant if missing. Returns the path to the variant MP4.

    Used by publish_reel when the network target needs a duration that wasn't
    rendered upfront (e.g. TikTok 28s when only 18s was rendered initially).
    """
    reel_id = reel_row["reel_id"]
    extra_path = MEDIA_DIR / f"reel_{reel_id}_{duration}s.mp4"

    if extra_path.exists():
        return str(extra_path)

    # Check variants JSON first — maybe it was pre-rendered with a different name.
    raw = reel_row["variants"] if "variants" in reel_row.keys() else None
    if raw:
        try:
            variants = json.loads(raw) if isinstance(raw, str) else (raw or {})
            existing = (variants.get(f"d{duration}") or {}).get("path")
            if existing and Path(existing).exists():
                return existing
        except Exception:
            variants = {}
    else:
        variants = {}

    logger.info(f"[reels] lazy-rendering {duration}s variant for reel {reel_id}")
    copy = {
        "hook": reel_row["hook"],
        "body": reel_row["body"],
        "label": reel_row["label"],
    }
    try:
        gen_news_video_v2.render_reel_v2(
            copy, extra_path, duration=duration,
            background_filename=background_filename,
        )
    except Exception as exc:
        logger.warning(f"[reels] lazy variant {duration}s failed: {exc}")
        return reel_row["local_path"]  # fallback to canonical

    # Persist updated variants JSON
    variants[f"d{duration}"] = {"path": str(extra_path), "duration": duration}
    try:
        with _conn() as c:
            c.execute(
                "UPDATE reels SET variants = ? WHERE reel_id = ?",
                (json.dumps(variants), reel_id),
            )
    except Exception:
        pass

    return str(extra_path)




def _pick_variant_path(row, network: str) -> str:
    """Return the MP4 path appropriate for the target network.

    If the required duration variant doesn't exist yet, lazily renders it
    (Phase 4 deferred-variant). Falls back to row['local_path'] on any error.
    """
    fallback = row["local_path"]
    target_dur = VARIANT_DURATIONS_BY_NETWORK.get(network, CANONICAL_DURATION_SEC)

    raw = row["variants"] if "variants" in row.keys() else None
    variants = {}
    if raw:
        try:
            variants = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            variants = {}

    key = f"d{target_dur}"
    existing = (variants.get(key) or {}).get("path")
    if existing and Path(existing).exists():
        return existing

    # Variant not yet rendered. If it matches the canonical duration, fallback.
    if target_dur == CANONICAL_DURATION_SEC:
        return fallback

    # Otherwise lazy-render it now.
    return _lazy_render_variant(row, target_dur)



def _caption_for_network(reel, network: str, caption_override: str | None = None) -> str:
    """Return the right text payload per platform.

    YouTube Shorts gets the full caption (5000 char limit, but we cap at 4900).
    Instagram Reels and TikTok get up to 2200 chars.
    X is hook-only (280 chars).
    Threads is hook + body, capped to 500 chars.

    The caller can pass `caption_override` (from UI textarea edits).
    """
    caption = (caption_override or reel.get("caption") or "").strip()
    hook = reel.get("hook", "")
    body = reel.get("body", "")
    if not caption:
        # Backwards compat for reels without LLM-generated caption
        caption = f"{hook}\n\n{body}\n\n#News #Geopolitics #Shorts"

    network = (network or "").lower()
    if network == "x":
        return hook[:280]
    if network == "threads":
        combo = f"{hook}\n\n{body}".strip()
        return combo[:500]
    if network in {"instagram", "tiktok"}:
        return caption[:2200]
    if network == "youtube":
        return caption[:4900]
    return caption[:2200]



def publish_reel(reel_id: str, networks: list[str], caption_override: str | None = None) -> dict:
    """
    Publish a rendered reel to the requested networks.
    Returns {network: {ok, remote_post_id, permalink, error}}.
    """
    networks = [n.lower() for n in networks if n.lower() in VALID_NETWORKS]
    if not networks:
        return {"error": "no valid networks selected"}

    reel = get_reel(reel_id)
    if not reel:
        return {"error": "reel not found"}

    _set_status(reel_id, "publishing")
    # Per-network caption is computed inside the loop now (each network has its own format).

    results: dict[str, dict] = {}
    any_success = False

    for net in networks:
        try:
            adapter = _get_adapter(net)
            variant_path = _pick_variant_path(reel, net)
            net_caption = _caption_for_network(reel, net, caption_override=caption_override)
            res = adapter.publish(text=net_caption, media=[variant_path])
        except Exception as exc:
            logger.exception("Adapter %s failed", net)
            res = {"ok": False, "error": str(exc), "network_post_id": None, "permalink": None}

        ok = bool(res.get("ok"))
        if ok:
            any_success = True

        _record_publish(
            reel_id,
            net,
            remote_post_id=res.get("network_post_id"),
            permalink=res.get("permalink"),
            error=res.get("error"),
        )

        results[net] = {
            "ok": ok,
            "remote_post_id": res.get("network_post_id"),
            "permalink": res.get("permalink"),
            "error": res.get("error"),
        }

    _set_status(reel_id, "published" if any_success else "failed")
    return results


# ---------------------------------------------------------------------------
# Read API
# ---------------------------------------------------------------------------

def get_reel(reel_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM reels WHERE reel_id = ?", (reel_id,)).fetchone()
        if not row:
            return None
        reel = dict(row)
        pubs = c.execute(
            "SELECT network_name, remote_post_id, permalink, published_at, error_message "
            "FROM reel_publishes WHERE reel_id = ? ORDER BY id",
            (reel_id,),
        ).fetchall()
        reel["publishes"] = [dict(p) for p in pubs]
    return reel


def list_reels(limit: int = 50, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM reels"
    params: list = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            pubs = c.execute(
                "SELECT network_name, remote_post_id, permalink, error_message "
                "FROM reel_publishes WHERE reel_id = ?",
                (d["reel_id"],),
            ).fetchall()
            d["publishes"] = [dict(p) for p in pubs]
            out.append(d)
    return out


# ---------------------------------------------------------------------------
# CLI for ad-hoc testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--summary", default="")
    ap.add_argument("--source", default="manual")
    ap.add_argument("--label", default="BREAKING")
    ap.add_argument("--publish", help="comma-separated networks")
    args = ap.parse_args()

    alert = {"headline": {"title": args.title, "summary": args.summary, "source": args.source}}
    print(">>> Generating copy...")
    copy = generate_reel_copy(alert, label=args.label)
    print(json.dumps(copy, indent=2))

    print(">>> Rendering reel...")
    rendered = render_reel(copy)
    print(json.dumps(rendered, indent=2))

    if args.publish:
        nets = [n.strip() for n in args.publish.split(",") if n.strip()]
        print(f">>> Publishing to {nets}...")
        print(json.dumps(publish_reel(rendered["reel_id"], nets), indent=2))
