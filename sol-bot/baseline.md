# Sol Bot Dashboard — Baseline Report
**Date:** 2026-03-25
**Version:** dashboard.py @ 43d6c1f
**Streamlit:** 1.55.0

---

## 1. Render Performance (per page load)

| Operation | Avg (ms) | Calls/render | Total cost |
|---|---|---|---|
| `context.json` read | 0.13 ms | 1 | 0.13 ms |
| `systemctl is-active` | 4.4 ms | 1 | 4.4 ms |
| `tail` log file | 1.82 ms | 3 | 5.46 ms |
| `journalctl` | 17.4 ms | 1 | 17.4 ms |
| **Full render sim** | **~27 ms** | — | **~27 ms** |

> Streamlit framework overhead (Python import, widget tree) adds ~800-1500ms on first load.
> Every 30s `sleep+rerun` blocks the entire process — no other session can render during sleep.

---

## 2. Architecture Failure Points

| Component | Risk | Impact |
|---|---|---|
| Hardcoded password `sol2026` | HIGH — plaintext in source | Auth bypass if repo exposed |
| `BASE_DIR = Path("/root/x-bot/sol-bot")` | MEDIUM — breaks if path changes | All reads fail silently |
| `time.sleep(30) + st.rerun()` | HIGH — blocks entire process | All concurrent sessions frozen |
| No caching on subprocess calls | MEDIUM — repeated cost each render | 27ms overhead × every 30s |
| Auth has no session TTL | MEDIUM — session never expires | Persistent access from shared browser |
| `journalctl` is slowest op (17.4ms) | LOW-MEDIUM | Bottleneck under load |
| No `.env` loading | MEDIUM — config not portable | Breaks on deploy to new env |
| Log reads have no size cap | LOW | Will slow down as logs grow |

---

## 3. Current Data Sources

| Source | Path | Size | Errors found |
|---|---|---|---|
| Context (tweets) | `/root/x-bot/sol-bot/context.json` | 10 entries | 0 |
| Scheduler log | `/root/x-bot/logs/scheduler.log` | 9.2 KB | 0 |
| Calendar log | `/root/x-bot/logs/calendar.log` | 0.3 KB | 0 |
| Analytics log | `/root/x-bot/logs/analytics.log` | 4.5 KB | 0 |
| Monitor service | `journalctl -u xbot-monitor` | live | 0 |

---

## 4. Security Audit

| Issue | Severity | Current state |
|---|---|---|
| Password hardcoded in source | CRITICAL | `if pwd == "sol2026"` |
| No session TTL | HIGH | Session never expires |
| No HTTPS | MEDIUM | Plain HTTP on port 8501 |
| No rate limiting on auth | MEDIUM | Unlimited attempts |
| Absolute paths hardcoded | LOW | `/root/x-bot/...` |

---

## 5. Baseline KPIs (Target improvements)

| Metric | Baseline | Phase 2 Target |
|---|---|---|
| Full render time | ~27ms data + ~1200ms framework | <800ms framework |
| Subprocess calls/render | 5 | 1-2 (cached) |
| Sleep blocking | 30s full block | 0 (fragment refresh) |
| Hardcoded secrets | 2 (password, paths) | 0 |
| Auth expiry | Never | 60 min configurable |

---

## 6. Rollback Plan (all phases)

```bash
# On VPS: revert to last working commit
cd /root/x-bot
git log --oneline -5
git checkout <commit-hash> -- sol-bot/dashboard.py
systemctl restart sol-dashboard
```
