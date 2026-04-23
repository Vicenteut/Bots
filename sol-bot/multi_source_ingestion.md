# Sol Multi-Source Ingestion

Sol can receive monitor inbox alerts from Telegram, RSS fetchers, n8n, APIs, or manual tools through one normalized pipeline.

## Private Ingest Endpoint

`POST /api/monitor/ingest`

Headers:

```http
Authorization: Bearer $INGEST_API_TOKEN
Content-Type: application/json
```

Minimal payload:

```json
{
  "external_id": "source-unique-id",
  "source_name": "n8n-webhook",
  "source_type": "webhook",
  "canonical_url": "https://example.com/story",
  "headline": {
    "title": "Story title",
    "summary": "Short context",
    "source": "n8n-webhook",
    "url": "https://example.com/story"
  },
  "metadata": {
    "credibility": "medium",
    "priority": "normal",
    "tags": ["markets"],
    "language": "en",
    "is_official": false,
    "redistributable": true
  }
}
```

## Source Config

Edit `source_config.json` to add trusted sources. Keep new sources disabled until tested.

Important fields:

- `enabled`: whether RSS fetcher should use the source.
- `type`: `telegram`, `rss`, `webhook`, `api`, `email`, `manual`, or `x`.
- `credibility`: `high`, `medium`, `low`, or `unverified`.
- `base_priority`: `high`, `normal`, or `low`.
- `is_official`: gives a large score boost.
- `redistributable`: set `false` for premium/private newsletters that can inform but should not be quoted directly.

## Dedup And Scoring

Incoming alerts are deduplicated by canonical URL first, then by normalized title.

If a duplicate arrives, Sol consolidates it into the existing inbox item and increases `related_source_count` instead of creating another card.

Scoring is intentionally rule-based:

- official source: strong boost
- high-credibility source: boost
- URL present: boost
- relevant topic: boost
- multiple sources: boost
- missing URL: penalty
- X/unverified: penalty

## RSS Fetcher

Manual run:

```bash
cd /root/x-bot/sol-bot
python3 rss_fetcher.py sync --limit 10
python3 rss_fetcher.py sync --limit 10 --dry-run
```

Systemd:

```bash
systemctl status sol-rss-fetcher.timer
journalctl -u sol-rss-fetcher.service -n 100 --no-pager
```

The timer is designed to run every 15 minutes.

