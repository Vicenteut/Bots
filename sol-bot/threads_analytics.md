# Threads Analytics

Sol stores Threads-only performance snapshots in:

```text
/root/x-bot/sol-bot/threads_analytics.db
```

This database is runtime state and must not be committed.

## Manual Commands

Fetch live data without writing SQLite:

```bash
python3 threads_analytics.py fetch --limit 20
```

Sync the latest Threads posts into SQLite:

```bash
python3 threads_analytics.py sync --limit 50
```

Read the persisted summary:

```bash
python3 threads_analytics.py summary --days 7
```

## Dashboard

The dashboard reads persisted data from SQLite through:

```text
GET /api/threads/analytics?days=7
```

Manual sync is available through:

```text
POST /api/threads/analytics/sync
```

The sync endpoint requires a valid dashboard session and `X-CSRF-Token`.

## Systemd Timer

Production runs the sync hourly:

```bash
systemctl is-active sol-threads-analytics.timer
systemctl list-timers | grep sol-threads-analytics
journalctl -u sol-threads-analytics.service -n 100 --no-pager
```

## Data Model

- `posts`: one row per Threads post, enriched with Sol metadata from `publish_log.json`.
- `post_snapshots`: one metrics snapshot per sync run.
- `sync_runs`: sync status, count, and short error message.

## Notes

- Analytics use the Threads API, not the legacy X/Twitter `analytics.db`.
- `tweet_type` comes from `publish_log.json` when available.
- `topic_tag` comes from `publish_log.json` or the shared keyword classifier.
- Follower growth is intentionally out of scope for this phase.
