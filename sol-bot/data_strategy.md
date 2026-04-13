# Sol Bot Data Strategy
**Generated:** 2026-04-09 | **Data window:** 2026-03-21 → 2026-04-05 (15 days, 237 tweets)

---

## 1. EXECUTIVE SUMMARY

### Engineering Perspective
The current data foundation is solid at the tweet-metrics layer: analytics.db captures views, likes, retweets, replies, topic, and media type for every post, with a snapshots table for growth-over-time tracking. However, the database is blind to the *operational* context of each post — there is no record of which tweet format (WIRE/ANALISIS/DEBATE/CONEXION) was used, which Telegram source channel originated the alert, which AI model generated the text, or what quality score it received from the LLM evaluator. This metadata exists transiently (in context.json, brain_history.json, publish_log.json) but never lands in analytics.db, making content optimization queries impossible. The highest-value engineering work is a single schema migration that backfills these fields and ensures every new publish event writes them atomically.

### Marketing Perspective
The data tells a provocative story already: crypto content (8 posts, 3.4% of volume) generates 64 avg views — more than 4× the 15 avg views that geopolitics posts (62% of volume) produce. Meanwhile, 30% of recent posts are raw wire reposts ("JUST IN:") scoring 4/20 on quality and dragging the account average down. The account is running two completely different content strategies simultaneously — sharp analytical posts that perform (50% score A-tier) and reflex wire reposts that don't (30% score D-tier). The growth lever is simple: eliminate the D-tier and redirect those posting slots toward crypto/finance analysis. The account has no follower-growth tracking at all, which means there's no signal for whether any of this is working at the audience level.

---

## 2. TOP 10 DATA POINTS TO CAPTURE (ranked by ROI)

| Rank | Data Point | Business Question It Answers | Implementation Location | Effort |
|------|-----------|------------------------------|------------------------|--------|
| 1 | **tweet_type** (WIRE/ANALISIS/DEBATE/CONEXION) in analytics.db | Which format drives the most views and engagement? | `analytics_tracker.py` — join on publish_log.json at sync time; or add to tweets table via ALTER | S |
| 2 | **Follower count snapshot** (daily: followers, following, tweet_count) | Is the account actually growing? What's the net weekly trend? | New cron script hitting `GET /2/users/:id` X API v2; store in new `account_snapshots` table | M |
| 3 | **Source channel** per published tweet (human-readable name, not raw Telegram ID) | Which feed (BRICSNews, WatcherGuru, manual, etc.) produces the highest-performing posts? | `monitor.py` — add channel_name lookup map; write to alert and publish log | S |
| 4 | **Quality score + move_detected** in analytics.db | Does LLM-evaluated quality actually predict views? Which rhetorical move performs best? | `evaluate_posts.py` — write scores back to analytics.db after evaluation run | M |
| 5 | **model_used** per tweet in analytics.db | Does model choice (sonnet vs. haiku vs. opus) affect content quality or engagement? | `analytics_tracker.py` — publish_log.json already has model_used field; sync it | S |
| 6 | **hour_of_day** (derived, 0–23) in analytics.db | What time of day produces the most views for geopolitical content? | SQL migration: `ALTER TABLE tweets ADD COLUMN hour_of_day INTEGER` + one-time UPDATE | S |
| 7 | **Monitor alert → publish conversion rate** | What % of incoming alerts actually get published? Where does the funnel drop? | `sol_commands.py:cmd_ignore` and `cmd_generate_from_monitor` — write alert_received / alert_published events to a counter log | S |
| 8 | **Engagement rate** (likes+RT+replies / views) as stored column | Is the audience actively engaging or passively scrolling? Which content type earns engagement? | SQL migration: `ALTER TABLE tweets ADD COLUMN engagement_rate REAL` + UPDATE computed from existing fields | S |
| 9 | **Reply-generator usage log** (post_id replied to, follower_count of target, result) | Does replying to large accounts drive profile visits and new followers? | `sol_commands.py` reply handler — write structured log entry to `reply_log.json` | S |
| 10 | **Profile visits per post** (X API v2 organic metrics endpoint) | Which posts actually convert impressions into profile visits and follows? | `analytics_tracker.py` — requires X API v2 `article_metrics` or `organic_metrics`; rate-limited | L |

---

## 3. SCHEMA ADDITIONS TO analytics.db

### 3a. Extend existing `tweets` table

```sql
-- Add content metadata columns (migrate existing 237 rows with NULL defaults)
ALTER TABLE tweets ADD COLUMN tweet_type      TEXT;    -- WIRE, ANALISIS, DEBATE, CONEXION, COMBINADA
ALTER TABLE tweets ADD COLUMN source_channel  TEXT;    -- BRICSNews, WatcherGuru, manual, etc.
ALTER TABLE tweets ADD COLUMN model_used      TEXT;    -- claude-sonnet-4-6, claude-haiku-4-5, etc.
ALTER TABLE tweets ADD COLUMN hour_of_day     INTEGER; -- 0-23, derived from created_at
ALTER TABLE tweets ADD COLUMN engagement_rate REAL;    -- (likes+retweets+replies) / NULLIF(views,0)
ALTER TABLE tweets ADD COLUMN quality_score   REAL;    -- LLM evaluator total_score (4-20)
ALTER TABLE tweets ADD COLUMN move_detected   TEXT;    -- Buried Lede, Math Check, etc.

-- Backfill derived columns for existing rows
UPDATE tweets SET
  hour_of_day     = CAST(strftime('%H', created_at) AS INTEGER),
  engagement_rate = ROUND((likes + retweets + replies) * 1.0 / NULLIF(views, 0), 4);

-- New indexes for common filter queries
CREATE INDEX IF NOT EXISTS idx_tweets_type    ON tweets(tweet_type);
CREATE INDEX IF NOT EXISTS idx_tweets_hour    ON tweets(hour_of_day);
CREATE INDEX IF NOT EXISTS idx_tweets_quality ON tweets(quality_score);
```

### 3b. New table: `account_snapshots`

```sql
CREATE TABLE IF NOT EXISTS account_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_at     TEXT NOT NULL,          -- ISO 8601 datetime
    followers       INTEGER DEFAULT 0,
    following       INTEGER DEFAULT 0,
    tweet_count     INTEGER DEFAULT 0,
    follower_delta  INTEGER DEFAULT 0,      -- vs. previous snapshot
    notes           TEXT                    -- optional tag (e.g. "after_viral_post")
);

CREATE INDEX IF NOT EXISTS idx_snapshots_at ON account_snapshots(snapshot_at);
```

### 3c. New table: `post_metadata`

```sql
-- Richer per-post metadata that may arrive after the tweet is created
CREATE TABLE IF NOT EXISTS post_metadata (
    tweet_id        TEXT PRIMARY KEY REFERENCES tweets(tweet_id),
    alert_id        TEXT,           -- UUID from monitor_queue.json
    source_channel  TEXT,           -- human-readable channel name
    tweet_type      TEXT,           -- format type
    model_used      TEXT,
    generation_ms   INTEGER,        -- how long generation took
    quality_score   REAL,           -- LLM evaluator score
    quality_tier    TEXT,           -- A/B/C/D
    move_detected   TEXT,
    sol_voice       REAL,
    angle_originality REAL,
    rhetorical_move REAL,
    closing_impact  REAL,
    one_line_verdict TEXT,
    evaluated_at    TEXT
);
```

### 3d. New table: `alert_funnel`

```sql
-- Tracks every monitor alert from arrival to outcome
CREATE TABLE IF NOT EXISTS alert_funnel (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id        TEXT UNIQUE,
    source_channel  TEXT,
    received_at     TEXT,
    has_media       INTEGER DEFAULT 0,
    outcome         TEXT,   -- 'published_x', 'published_threads', 'published_both', 'ignored', 'pending'
    tweet_id        TEXT,   -- FK to tweets if published
    decided_at      TEXT,
    latency_seconds INTEGER -- received_at → decided_at
);
```

**Capacity estimate:** At 15 posts/day × 365 days = ~5,500 rows/year in `tweets`. With snapshots at 5×/day = ~1,800 rows/year. Total DB stays well under 50MB for 24 months with no partitioning needed.

---

## 4. MARKETING KPI DASHBOARD

7 KPIs to add to the Sol Dashboard analytics panel:

| # | KPI | How to Calculate | Target | What It Signals |
|---|-----|-----------------|--------|-----------------|
| 1 | **Avg Views / Post (7d)** | `AVG(views) WHERE created_at >= now-7d` | >25 views | Baseline content reach; compare to prior week |
| 2 | **Engagement Rate (7d)** | `AVG((likes+retweets+replies)*1.0/NULLIF(views,0))` | >3.0% | Active vs. passive audience; <1% = wrong topics |
| 3 | **Quality Score Avg (30d)** | `AVG(quality_score) FROM post_metadata` | >14.0 / 20 | Content health; dropping score = regression in voice |
| 4 | **Wire-Repost Ratio (7d)** | `COUNT(*) WHERE tweet_type='WIRE' OR move_detected='none'` / `COUNT(*)` | <15% | Operational discipline; >30% = reflex posting problem |
| 5 | **Follower Delta (weekly)** | `followers_now - followers_7d_ago FROM account_snapshots` | Positive | Growth signal; flat = content not converting |
| 6 | **Top Rhetorical Move (7d)** | `move_detected WHERE quality_score>14 ORDER BY AVG(views) DESC LIMIT 1` | — | Tells operator which move to instruct Sol to use more |
| 7 | **Source Channel Win Rate** | `AVG(views) GROUP BY source_channel ORDER BY AVG(views) DESC LIMIT 1` | — | Tells operator which feed to prioritize; hide underperformers |

---

## 5. CONTENT STRATEGY INSIGHTS

**Based on analytics.db (237 tweets) + evaluation_results.json (20 posts scored)**

### What Sol is doing well
- **Buried Lede execution is sharp**: 8/20 evaluated posts use it; A-tier posts average ~18/20 quality score, indicating the voice and structure are distinctive when Sol is in full analytical mode.
- **Closing impact is the strongest metric** (avg 3.5/5): Sol consistently lands the final line. The last-line-as-knife pattern ("That's not a rescue. That's a forward operating posture.") is working.
- **Thread format drives disproportionate engagement**: The #1 post (414 views, 29 likes, 3 RT, 5 replies) was a 🧵 thread on infrastructure targeting. Threads generate reply depth that single posts don't.

### What Sol should do MORE of
- **Crypto + macro analysis**: Crypto posts (8 total) produce 64 avg views vs. 15 for geopolitics posts despite geopolitics being 62% of volume. The topic mismatch is the single largest performance gap. A 20% shift toward crypto/finance analysis with the same rhetorical structure would dramatically improve account averages.
- **Math Check and Nobody Noticed moves**: These are underused (3 and 1 occurrences respectively) but well-suited to the crypto/macro topic areas. Example: "X country's GDP is smaller than Apple's cash reserves" → Math Check = automatic engagement.
- **Structured two-part format**: Fact drop → blank line → analysis. The highest-performing posts follow this precisely. Single-paragraph posts without the structural break perform worse.

### What Sol should stop doing
- **Raw wire reposts**: 30% of evaluated posts scored 4/20 (D-tier). These are "JUST IN: 🇮🇷🇮🇱..." style reposts with zero analysis. They degrade the account's brand (it looks like another news relay), contribute nothing to follower growth, and dilute the analytical identity that makes the account distinctive.
- **Moralizing and soft hedges**: Sol voice scores 3.45/5 (weakest dimension). The LLM evaluator repeatedly flags phrases like "this signals" or "observers note" as generic softeners. Harder, drier, more declarative language consistently scores higher.
- **Breaking news speed-posting**: The evidence suggests operator posts JUST IN alerts during breaking events for FOMO reasons. The data shows these get average views (no edge over the slower, analytical posts) and actively damage the quality average.

---

## 6. QUICK WINS (implement this week, ranked by impact/effort)

| Rank | What | Where in Code | Expected Analytical Value |
|------|------|--------------|--------------------------|
| **1** | Add `tweet_type` sync to analytics.db at publish time | `sol_commands.py:_append_publish_log()` already logs tweet_type; `analytics_tracker.py` should read it and write to tweets.tweet_type column during sync | Unlocks the most important query: format × views performance. Currently impossible. |
| **2** | Migrate analytics.db: add `hour_of_day` + `engagement_rate` derived columns | One-time SQL migration (ALTER TABLE + UPDATE). Zero API cost. | Enables timing analysis and engagement depth queries immediately on existing 237 rows. |
| **3** | Map Telegram channel IDs to human-readable names in monitor.py | Add a `CHANNEL_NAMES` dict in `monitor.py` mapping raw IDs (e.g., `-1002006131201`) to names (e.g., `BRICSNews`); write `source_channel` to alert and publish_log | Enables source channel ROI analysis. Currently all alerts look identical in analytics. |
| **4** | Schedule weekly evaluate_posts.py + write scores to analytics.db | Add cron: `0 8 * * 1 python3 evaluate_posts.py --n 50 --write-db`; add `--write-db` flag to script | Populates quality_score and move_detected in analytics.db, enabling quality→views correlation queries. |
| **5** | Add "JUST IN:" pattern warning in sol_commands.py before publishing | In `_publish_both()` / `_publish_x()`: if `tweet.startswith("JUST IN")`, send Telegram warning: "⚠️ Wire repost detected — consider adding analysis layer before publishing." | Behavioral nudge to reduce D-tier rate without blocking the operator. Non-intrusive. |

---

## 7. SAMPLE QUERIES

**Run these weekly to monitor Sol's performance:**

```sql
-- Query 1: Format performance (requires tweet_type populated)
SELECT
    tweet_type,
    COUNT(*) AS posts,
    ROUND(AVG(views), 1) AS avg_views,
    ROUND(AVG(likes), 2) AS avg_likes,
    ROUND(AVG(engagement_rate) * 100, 2) AS eng_rate_pct
FROM tweets
WHERE tweet_type IS NOT NULL
GROUP BY tweet_type
ORDER BY avg_views DESC;

-- Query 2: Source channel ROI (requires source_channel populated)
SELECT
    source_channel,
    COUNT(*) AS posts,
    ROUND(AVG(views), 1) AS avg_views,
    ROUND(AVG(likes), 2) AS avg_likes,
    MAX(views) AS best_post_views
FROM tweets
WHERE source_channel IS NOT NULL
GROUP BY source_channel
ORDER BY avg_views DESC;

-- Query 3: Weekly view trend
SELECT
    DATE(created_at) AS day,
    COUNT(*) AS posts,
    SUM(views) AS total_views,
    ROUND(AVG(views), 1) AS avg_views,
    ROUND(AVG(engagement_rate) * 100, 2) AS eng_rate_pct
FROM tweets
WHERE created_at >= DATE('now', '-30 days')
GROUP BY day
ORDER BY day DESC;

-- Query 4: Quality score vs. views correlation (requires quality_score populated)
SELECT
    quality_tier,
    COUNT(*) AS posts,
    ROUND(AVG(views), 1) AS avg_views,
    ROUND(AVG(likes), 2) AS avg_likes,
    ROUND(AVG(quality_score), 1) AS avg_score
FROM tweets
JOIN post_metadata USING (tweet_id)
GROUP BY quality_tier
ORDER BY avg_views DESC;

-- Query 5: Best rhetorical move by engagement
SELECT
    move_detected,
    COUNT(*) AS uses,
    ROUND(AVG(views), 1) AS avg_views,
    ROUND(AVG(engagement_rate) * 100, 2) AS eng_rate_pct,
    MAX(views) AS peak_views
FROM tweets
JOIN post_metadata USING (tweet_id)
WHERE move_detected IS NOT NULL AND move_detected != 'none'
GROUP BY move_detected
ORDER BY avg_views DESC;
```

---

*Document generated from live data on 2026-04-09. Re-run evaluate_posts.py and refresh analytics.db before next review.*
