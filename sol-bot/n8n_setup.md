# n8n Workflow Setup Guide — Sol Bot

## Workflows

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| Engagement Tracker | Every 4 hours | Fetches X API metrics → updates analytics.db → alerts on traction |
| GDELT Escalation Alert | Every 30 minutes | Monitors geopolitical keyword spikes → Telegram alert |

---

## Step 1 — Set n8n Environment Variables

The Telegram nodes read `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` via `$env.*`.
You need to expose them to n8n at startup.

**Option A — restart n8n with env vars loaded:**
```bash
# Kill current n8n
pkill -f "node /usr/bin/n8n"

# Restart with env from .env file
set -a && source /root/x-bot/.env && set +a
nohup n8n start > /var/log/n8n.log 2>&1 &
```

**Option B — add to n8n Settings → Variables (UI):**
1. Open http://localhost:5678
2. Settings → Variables → Add Variable
3. Add: `TELEGRAM_BOT_TOKEN` = (value from .env)
4. Add: `TELEGRAM_CHAT_ID` = (value from .env)

---

## Step 2 — Create X Bearer Token Credential

The Engagement Tracker uses a Header Auth credential for the X API.

1. Open http://localhost:5678 → **Settings → Credentials → + Add credential**
2. Search and select: **Header Auth**
3. Fill in:
   - **Name:** `X Bearer Token`
   - **Name (header):** `Authorization`
   - **Value:** `Bearer YOUR_X_BEARER_TOKEN_HERE`
     _(replace with the value of `X_BEARER_TOKEN` from `/root/x-bot/.env`)_
4. Click **Save**

> The workflow JSON references this credential by name `"X Bearer Token"`. n8n will match it automatically on import.

---

## Step 3 — Import Workflows

### Option A — CLI (recommended)
```bash
n8n import:workflow --input=/root/x-bot/sol-bot/n8n_engagement_workflow.json
n8n import:workflow --input=/root/x-bot/sol-bot/n8n_gdelt_alert_workflow.json
```

### Option B — n8n UI
1. Open http://localhost:5678
2. Click **Workflows** in the sidebar
3. Click **⋮ (menu) → Import from file**
4. Select `n8n_engagement_workflow.json` → Import
5. Repeat for `n8n_gdelt_alert_workflow.json`

---

## Step 4 — Verify Credential Mapping

After import, open each workflow:

1. Click the **"Fetch X Metrics"** node in Engagement Tracker
2. Under **Credential**, confirm it shows `X Bearer Token` ✓
3. If it shows a warning, click the credential dropdown and select `X Bearer Token`

---

## Step 5 — Warm Up GDELT Baseline

The baseline starts at zero counts. Run the GDELT workflow manually 2-3 times first to populate realistic baselines and avoid false-positive spike alerts.

```bash
# Check baseline after first run
cat /root/x-bot/sol-bot/gdelt_baseline.json
```

---

## Step 6 — Activate Both Workflows

1. Open **Engagement Tracker** → toggle **Active** → ON
2. Open **GDELT Escalation Alert** → toggle **Active** → ON

---

## Verification

```bash
# Check engagement log after first run (fires in 4h, or trigger manually)
tail -f /root/x-bot/logs/n8n_engagement.log

# Check GDELT baseline updates (fires every 30min)
watch -n 60 cat /root/x-bot/sol-bot/gdelt_baseline.json

# Check n8n execution history in UI
open http://localhost:5678/executions

# Run spike detection unit tests (5/5 expected)
cd /root/x-bot/sol-bot && promptfoo eval -c promptfoo_gdelt_logic.yaml
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| X API returns 401 | Verify `X Bearer Token` credential has `Bearer ` prefix (with space) |
| X API returns 403/429 | Rate limited — the tracker runs every 4h which should be within free tier limits |
| Telegram not sending | Check `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` are accessible as n8n env vars |
| GDELT returns no articles | Normal for quiet keywords — baseline stays 0, no alert fires |
| Baseline file corrupted | `cp /dev/null /root/x-bot/sol-bot/gdelt_baseline.json` then re-init from template |
| sqlite3 command not found | `apt-get install -y sqlite3` |
| analytics.db missing tweets table | Run the SQL below to initialize |

### Initialize analytics.db (if tweets table missing)
```bash
sqlite3 /root/x-bot/analytics.db << 'EOF'
CREATE TABLE IF NOT EXISTS tweets (
  tweet_id TEXT PRIMARY KEY,
  text TEXT,
  created_at TEXT,
  likes INTEGER DEFAULT 0,
  retweets INTEGER DEFAULT 0,
  replies INTEGER DEFAULT 0,
  views INTEGER DEFAULT 0,
  media_type TEXT DEFAULT 'text',
  topic TEXT DEFAULT 'other',
  tweet_length INTEGER DEFAULT 0,
  is_thread INTEGER DEFAULT 0,
  first_seen TEXT,
  last_updated TEXT,
  tweet_type TEXT,
  source_channel TEXT,
  hour_of_day INTEGER,
  engagement_rate REAL
);
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tweet_id TEXT,
  timestamp TEXT,
  likes INTEGER DEFAULT 0,
  retweets INTEGER DEFAULT 0,
  replies INTEGER DEFAULT 0,
  views INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tweets_created ON tweets(created_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_tweet ON snapshots(tweet_id);
EOF
echo "analytics.db initialized"
```

---

## Files Reference

| File | Path |
|------|------|
| Engagement workflow | `/root/x-bot/sol-bot/n8n_engagement_workflow.json` |
| GDELT workflow | `/root/x-bot/sol-bot/n8n_gdelt_alert_workflow.json` |
| GDELT baseline | `/root/x-bot/sol-bot/gdelt_baseline.json` |
| Spike logic (pure JS) | `/root/x-bot/sol-bot/gdelt_spike_logic.js` |
| Promptfoo tests | `/root/x-bot/sol-bot/promptfoo_gdelt_logic.yaml` |
| Engagement log | `/root/x-bot/logs/n8n_engagement.log` |
| Publish log | `/root/x-bot/logs/publish_log.json` |
| Analytics DB | `/root/x-bot/analytics.db` |
