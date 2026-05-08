#!/usr/bin/env python3
"""Fix Sprint 5 patch: move the network filter from `_normalize_post` (wrong)
to right before `get_analytics()` return (correct, line ~659).
"""

PATH = "/root/x-bot/sol-bot/threads_analytics.py"

with open(PATH) as f:
    src = f.read()

WRONG = """    has_media = 1 if bool(meta.get("has_media") or media_count or media_type.upper() != "TEXT") else 0
    # Sprint 5 — filter recent_posts by network if requested
    if network and network != "all":
        try:
            recent_posts = [p for p in (recent_posts or []) if (p.get("network_name") or "threads") == network]
        except Exception:
            pass

    return {
        "post_id": post_id,"""
RESTORED = """    has_media = 1 if bool(meta.get("has_media") or media_count or media_type.upper() != "TEXT") else 0

    return {
        "post_id": post_id,"""
if WRONG not in src:
    print("ERROR: misplaced filter block not found — maybe already fixed?")
else:
    src = src.replace(WRONG, RESTORED, 1)
    print("OK: removed misplaced block from _normalize_post")

# Now insert the correct filter just before the `get_analytics` return
TARGET = """        except Exception:
            by_source = []


    return {
        "error": last_sync.get("error") if last_sync and last_sync.get("status") != "OK" else None,
        "days": days,"""
NEW_TARGET = """        except Exception:
            by_source = []

    # Sprint 5 — filter recent_posts by network if requested (post-aggregation MVP)
    if network and network != "all":
        try:
            recent_posts = [p for p in (recent_posts or []) if (p.get("network_name") or "threads") == network]
        except Exception:
            pass

    return {
        "error": last_sync.get("error") if last_sync and last_sync.get("status") != "OK" else None,
        "days": days,"""
if TARGET not in src:
    print("ERROR: get_analytics return marker not found")
elif "Sprint 5 — filter recent_posts by network if requested (post-aggregation MVP)" in src:
    print("OK: filter already at correct location")
else:
    src = src.replace(TARGET, NEW_TARGET, 1)
    print("OK: inserted filter at correct location (just before get_analytics return)")

with open(PATH, "w") as f:
    f.write(src)
