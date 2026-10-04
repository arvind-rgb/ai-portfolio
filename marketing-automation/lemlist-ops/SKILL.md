---
name: lemlist-ops
description: Automated daily reports, completion detection, and next-batch creation for Bhookle B2B Lemlist campaigns. Use this skill for ANY request about Lemlist daily reports, batch automation, campaign monitoring, or Bhookle outreach operations.
---

# Lemlist Ops — Bhookle B2B Outreach Automation

Automates the operational layer around Bhookle's "Batch<N>-100Leads-<date>" Lemlist campaigns:

1. **Daily report** — Pulls each running campaign's stats at 19:00 IST and emails a Bhookle-branded HTML digest to `owner@example.com` via Gmail SMTP.
2. **Completion detection** — Same daily job detects when ALL leads have reached a terminal state (ended / unsubscribed / bounced / interested / notInterested). Fires a "🎉 Campaign Complete" email instead of the regular daily digest.
3. **Next-batch automation** — On completion, automatically triggers a sibling workflow that searches the Lemlist People Database with the same ICP filters used in Batch 1, dedupes against ALL prior batches, and creates a new DRAFT campaign with the next 100 fresh leads. **Does NOT auto-launch** — user reviews and approves first.

## Architecture (mirrors `bhookle-social-tick.yml` + `ads-manager-weekly.yml`)

```
cron-job.org (primary trigger)  ─┐
                                  ├─→  repository_dispatch  →  GH Actions workflow  →  Python script
GH Actions cron (backup, 3 retries) ─┘                              │
                                                                    ▼
                                                          Gmail SMTP via dawidd6/action-send-mail
                                                                    │
                                                                    ▼
                                                          owner@example.com inbox
```

## Files

- `scripts/lemlist_api.py` — shared HTTP Basic Auth helpers (uses `LEMLIST_API_KEY`)
- `scripts/fetch_daily_stats.py` — pulls stats + lead states, writes `email-marketing/lemlist/<slug>/daily-YYYY-MM-DD.json`, exits with code 3 when completion just detected
- `scripts/format_digest.py` — formats Bhookle-branded HTML + text digest, writes to `/tmp/lemlist-digest.{html,txt}`
- `scripts/create_next_batch.py` — searches People DB, dedupes against all prior `Batch<N>-*` campaigns, creates draft Batch N+1
- `.github/workflows/lemlist-daily-report.yml` — daily cron, primary entry point
- `.github/workflows/lemlist-next-batch.yml` — triggered by daily report on completion

## ICP Filters (Batch 1 source-of-truth)

Hard-coded in `create_next_batch.py::ICP_FILTERS` — adjust there to widen/narrow targeting:

| Filter | Values |
|--------|--------|
| Industry | Media and Telecommunications, Technology Information and Internet |
| Company size | 11-50 |
| Country | India |
| City / state | karnataka bengaluru |
| Job title | admin, senior administrative assistant, office manager, executive assistant, executive administrative assistant, founder, co-founder |

## Required Secrets (GitHub Actions)

| Secret | Source | Notes |
|--------|--------|-------|
| `LEMLIST_API_KEY` | Lemlist Settings → API Keys | New — must be added |
| `GMAIL_USER` | Already in repo (used by ads-manager + email-outreach) | Reused |
| `GMAIL_APP_PASSWORD` | Already in repo | Reused |
| `LEMLIST_REPORT_RECIPIENT` | New | Set to `owner@example.com` (or another address) |

## Setup Steps (one-time)

1. **Add `LEMLIST_API_KEY` to `.env` locally and to GH Secrets** — same key as the one in your conversation with Claude
2. **Add `LEMLIST_REPORT_RECIPIENT` to GH Secrets** — `owner@example.com`
3. **Push code → workflows auto-deploy**
4. **Set up cron-job.org trigger** (mirroring social-tick pattern):
   - URL: `https://api.github.com/repos/<owner>/bhookle-marketing/dispatches`
   - Method: POST
   - Headers: `Authorization: Bearer <GH personal access token>`, `Accept: application/vnd.github+json`
   - Body: `{"event_type":"lemlist_daily"}`
   - Schedule: every day at 19:00 IST (13:30 UTC)
5. **Test the wiring**: run `gh workflow run "Bhookle Lemlist Daily Report"` — confirm email lands in inbox

## How to Apply

When the user says "show me yesterday's Lemlist stats", "is Batch N done?", "kick off next batch", or any similar phrasing, invoke this skill.

For manual ops:
- `gh workflow run "Bhookle Lemlist Daily Report"` — force a daily report now
- `gh workflow run "Bhookle Lemlist Next Batch" -f dry_run=true` — preview next batch without creating it
- Run `python3 _skills/lemlist-ops/scripts/fetch_daily_stats.py --campaign-id <id>` locally for ad-hoc checks
