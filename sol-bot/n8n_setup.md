# n8n Workflow Setup Guide — Sol Bot

Sol Bot now publishes and tracks publishing through Threads only. The legacy engagement tracker has been removed, so n8n only needs the GDELT escalation workflow.

## Workflows

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| GDELT Escalation Alert | Every 30 minutes | Monitors geopolitical keyword spikes and sends Telegram alerts |

---

## Step 1 — Set n8n Environment Variables

The Telegram nodes read `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` via `$env.*`.
Expose them to n8n before activating the workflow.

**Option A — restart n8n with env vars loaded:**
```bash
# Kill current n8n
pkill -f "node /usr/bin/n8n"

# Restart with env from .env file
set -a && source /root/x-bot/.env && set +a
nohup n8n start > /var/log/n8n.log 2>&1 &
```

**Option B — add to n8n Settings -> Variables (UI):**
1. Open http://localhost:5678
2. Settings -> Variables -> Add Variable
3. Add: `TELEGRAM_BOT_TOKEN` = value from `.env`
4. Add: `TELEGRAM_CHAT_ID` = value from `.env`
5. Add: `SOL_DASHBOARD_BASIC_AUTH` = base64 of `DASHBOARD_USER:DASHBOARD_PASSWORD` for the private dashboard API

---

## Step 2 — Import Workflow

### Option A — CLI (recommended)
```bash
n8n import:workflow --input=/root/x-bot/sol-bot/n8n_gdelt_alert_workflow.json
```

### Option B — n8n UI
1. Open http://localhost:5678
2. Click **Workflows** in the sidebar
3. Click **... (menu) -> Import from file**
4. Select `n8n_gdelt_alert_workflow.json` -> Import

---

## Step 3 — Warm Up GDELT Baseline

The baseline starts at zero counts. Run the GDELT workflow manually 2-3 times first to populate realistic baselines and avoid false-positive spike alerts.

```bash
# Check baseline after first run
cat /root/x-bot/sol-bot/gdelt_baseline.json
```

---

## Step 4 — Activate Workflow

Open **GDELT Escalation Alert** and toggle **Active** -> ON.

---

## Verification

```bash
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
| Telegram not sending | Check `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` are accessible as n8n env vars |
| GDELT returns no articles | Normal for quiet keywords; baseline stays 0 and no alert fires |
| Baseline file corrupted | `cp /dev/null /root/x-bot/sol-bot/gdelt_baseline.json` then re-run warmup |

---

## Files Reference

| File | Path |
|------|------|
| GDELT workflow | `/root/x-bot/sol-bot/n8n_gdelt_alert_workflow.json` |
| GDELT baseline | `/root/x-bot/sol-bot/gdelt_baseline.json` |
| Spike logic (pure JS) | `/root/x-bot/sol-bot/gdelt_spike_logic.js` |
| Promptfoo tests | `/root/x-bot/sol-bot/promptfoo_gdelt_logic.yaml` |
| Publish log | `/root/x-bot/logs/publish_log.json` |
