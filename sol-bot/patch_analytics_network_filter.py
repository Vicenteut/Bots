#!/usr/bin/env python3
"""Sprint 5 patch — add `network` param to get_analytics + endpoint.

Steps:
1. Add `network: str = "all"` kwarg to get_analytics() signature
2. Add `p.network_name` column to recent_posts SELECT
3. Inject post-filter on recent_posts when network != 'all'
4. Patch /api/threads/analytics FastAPI endpoint to accept `network` query param
   and pass it to get_analytics()
"""

import sys

ANALYTICS_PATH = "/root/x-bot/sol-bot/threads_analytics.py"
API_PATH = "/root/x-bot/sol-bot/sol_dashboard_api.py"

# ── 1) threads_analytics.py ──
with open(ANALYTICS_PATH) as f:
    asrc = f.read()

did_anything = False

if 'network: str = "all"' not in asrc:
    OLD_SIG = '''def get_analytics(
    days: int = 7,
    limit: int = 20,
    db_path: Path = DB_PATH,
    sort: str = "date",
    format: str | None = None,
    topic: str | None = None,
    media: str | None = None,
) -> dict[str, Any]:'''
    NEW_SIG = '''def get_analytics(
    days: int = 7,
    limit: int = 20,
    db_path: Path = DB_PATH,
    sort: str = "date",
    format: str | None = None,
    topic: str | None = None,
    media: str | None = None,
    network: str = "all",
) -> dict[str, Any]:'''
    if OLD_SIG not in asrc:
        print("ERROR: signature marker not found in threads_analytics.py")
        sys.exit(1)
    asrc = asrc.replace(OLD_SIG, NEW_SIG, 1)
    did_anything = True

# Add network_name column to recent_posts SELECT
OLD_SELECT = """                SELECT
                    p.post_id AS id, p.text, p.permalink, p.timestamp, p.media_type,
                    p.tweet_type, p.topic_tag, p.char_count, p.has_media, p.media_count,
                    latest.views, latest.likes, latest.replies, latest.reposts, latest.quotes,"""
NEW_SELECT = """                SELECT
                    p.post_id AS id, p.text, p.permalink, p.timestamp, p.media_type,
                    p.tweet_type, p.topic_tag, p.char_count, p.has_media, p.media_count,
                    p.network_name,
                    latest.views, latest.likes, latest.replies, latest.reposts, latest.quotes,"""
if OLD_SELECT in asrc and "p.network_name," not in asrc.split("recent_posts = [")[1][:1500]:
    asrc = asrc.replace(OLD_SELECT, NEW_SELECT, 1)
    did_anything = True

# Inject post-filter just before the function's return statement
if "# Sprint 5 — filter recent_posts by network" not in asrc:
    import re
    m = re.search(r'\n    return \{\n', asrc)
    if not m:
        print("ERROR: no `return {` line in get_analytics")
        sys.exit(1)
    pos = m.start()
    INJECT = """
    # Sprint 5 — filter recent_posts by network if requested
    if network and network != "all":
        try:
            recent_posts = [p for p in (recent_posts or []) if (p.get("network_name") or "threads") == network]
        except Exception:
            pass
"""
    asrc = asrc[:pos] + INJECT + asrc[pos:]
    did_anything = True

if did_anything:
    with open(ANALYTICS_PATH, "w") as f:
        f.write(asrc)
    print("OK: threads_analytics.py patched")
else:
    print("OK: threads_analytics.py already patched")

# ── 2) sol_dashboard_api.py ──
with open(API_PATH) as f:
    api_src = f.read()

if "network: Optional[str] = " in api_src:
    print("OK: sol_dashboard_api.py already patched")
    sys.exit(0)

OLD_EP = '''@app.get("/api/threads/analytics")
async def api_threads_analytics(
    days: int = 7,
    limit: int = 20,
    sort: str = "date",
    format: Optional[str] = None,
    topic: Optional[str] = None,
    media: Optional[str] = None,
):
    days = max(1, min(days, 90))
    limit = max(1, min(limit, 50))
    sort = (sort or "date").strip().lower()
    if sort not in {"views", "likes", "replies", "comments", "engagement", "date", "total_engagement"}:
        sort = "date"
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "threads_analytics", BOT_DIR / "threads_analytics.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        data = mod.get_analytics(days=days, limit=limit, sort=sort, format=format, topic=topic, media=media)'''

NEW_EP = '''@app.get("/api/threads/analytics")
async def api_threads_analytics(
    days: int = 7,
    limit: int = 20,
    sort: str = "date",
    format: Optional[str] = None,
    topic: Optional[str] = None,
    media: Optional[str] = None,
    network: Optional[str] = "all",
):
    days = max(1, min(days, 90))
    limit = max(1, min(limit, 50))
    sort = (sort or "date").strip().lower()
    if sort not in {"views", "likes", "replies", "comments", "engagement", "date", "total_engagement"}:
        sort = "date"
    net = (network or "all").strip().lower()
    if net not in {"all", "threads", "x", "bluesky", "linkedin"}:
        net = "all"
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "threads_analytics", BOT_DIR / "threads_analytics.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        data = mod.get_analytics(days=days, limit=limit, sort=sort, format=format, topic=topic, media=media, network=net)'''

if OLD_EP not in api_src:
    print("ERROR: endpoint marker not found in sol_dashboard_api.py")
    sys.exit(1)

api_src = api_src.replace(OLD_EP, NEW_EP, 1)
with open(API_PATH, "w") as f:
    f.write(api_src)
print("OK: sol_dashboard_api.py patched")
