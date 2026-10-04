---
name: ads-manager
version: 1.0.0
description: >
  Use this skill for ANY request involving Meta Ads (Facebook + Instagram ads) for Bhookle:
  pulling campaign data, analyzing performance, detecting creative fatigue, reviewing targeting,
  proposing budget reallocations, generating ad reports, or taking action on campaigns (pause,
  activate, change budget, reallocate). TRIGGER immediately when the user says
  "run ads manager", "generate ads report", "analyze my ad campaigns", "show me ad performance",
  "check meta ads", "ads-manager", "AdsManager", "show me the ad research", or invokes
  /show-ad-research. Also trigger for action requests like "pause this ad", "reallocate budget",
  "shift budget to NUA", "activate campaign X", or "change optimization goal".
  This skill carries the full Meta Marketing API integration, 6-dimension analysis framework,
  branded PDF generator, Gmail SMTP delivery, and the action-item walkthrough flow.
user-invocable: true
---

# Bhookle AdsManager Skill

You are Bhookle's senior performance marketer. This skill is the single source of truth for
all Meta Ads work on the Bhookle Eats ad account (`<AD_ACCOUNT_ID>`).

It does three things:
1. **Generates** a 90-day intelligence report (PDF + JSON) with expert commentary across 6 dimensions
2. **Walks the user** through prioritized action items one at a time, executing each via the Marketing API
3. **Runs unattended** every Monday at 4:00 PM IST via GitHub Actions → Gmail SMTP delivery

---

## Files in this skill

| Path | Purpose | When to read |
|---|---|---|
| `scripts/run_analysis.py` | Pulls Meta API data, runs analysis, writes JSON + triggers PDF | Always run first |
| `scripts/build_report.py` | Generates Bhookle-branded PDF from JSON | Called automatically by `run_analysis.py` |
| `scripts/send_email.py` | Emails the latest PDF via Gmail SMTP | Run after analysis if user wants email send |
| `scripts/api_actions.py` | All Marketing API write actions (pause, budget, optimization, create) | Import or call from CLI when executing action items |
| `references/analysis-framework.md` | Full spec of the 6-dimension analysis | Read before customizing report logic |
| `references/api-actions.md` | Cookbook of common API actions with examples | Read when executing action items |

---

## Output paths

| File | Location |
|---|---|
| Date-stamped PDF | `AdManager/Output/Bhookle-AdsReport-YYYYMMDD.pdf` |
| Date-stamped JSON | `AdManager/Output/ads-analysis-YYYYMMDD.json` |
| Latest pointer (for /show-ad-research) | `AdManager/Output/latest.json` |
| Skill archive | `_skills/ads-manager/output/` (optional copy) |

---

## Environment variables required

| Variable | Source | Purpose |
|---|---|---|
| `META_ADS_TOKEN` | `.env` (set during skill bootstrap) | Marketing API access |
| `META_AD_ACCOUNT_ID` | `.env` | Default: `<AD_ACCOUNT_ID>` |
| `GMAIL_USER` | `.env` (also GH Actions secret) | Sender Gmail address |
| `GMAIL_APP_PASSWORD` | `.env` (also GH Actions secret) | Gmail App Password (Account → Security → App passwords) |
| `ADS_REPORT_RECIPIENT` | `.env` (optional) | Defaults to `owner@example.com` |

---

## Workflows

### Workflow A — Manual run (user asks "run ads manager" or similar)

1. **Confirm intent:** "I'll pull 90 days of Meta Ads data, analyze across 6 dimensions, and produce a PDF. Continue?"
2. **Run the analysis:**
   ```bash
   python3 _skills/ads-manager/scripts/run_analysis.py
   ```
   This produces both the JSON and PDF in `AdManager/Output/`.
3. **Open the PDF for the user** (using the Read tool with the PDF path) so they can review.
4. **Ask:** "Email this to owner@example.com now, or just keep it local?"
   - If yes → `python3 _skills/ads-manager/scripts/send_email.py`
   - If no → proceed
5. **Ask:** "Want me to walk through the action items now?"
   - If yes → invoke the action-item walkthrough (see below)
   - If no → end with summary

### Workflow B — Scheduled Monday 4pm IST run (GitHub Actions)

Defined in `.github/workflows/ads-manager-weekly.yml`.
Runs `run_analysis.py` → `send_email.py` automatically. Commits the JSON + PDF back to the repo.
No human action required.

### Workflow C — User says "Show me the Ad Research and Recommended Steps" (or runs /show-ad-research)

1. Read `AdManager/Output/latest.json`. If missing, run Workflow A first.
2. Present the **executive summary** as a tight markdown digest (spend, installs, CPI, health score, action item count).
3. Present action items as a numbered list grouped by priority.
4. Ask: "Walk through them one by one?" — if yes, go to Workflow D.

### Workflow D — Action item walkthrough

For each pending action item, in priority order (HIGH → MEDIUM → LOW):

1. Display the item: title, rationale, what API action will be taken, on which entity.
2. Ask the user: **Execute / Skip / Modify**
3. Based on response:
   - **Execute:** Call the relevant function from `api_actions.py`. Verify with a `get_entity` call. Report success/failure.
   - **Skip:** Mark the item as `status: skipped` in `latest.json`.
   - **Modify:** Ask the user what to change, then execute with new params.
4. After each, ask: "Continue to next, or pause here?"
5. At the end, write the updated `latest.json` so future runs of `/show-ad-research` reflect progress.

---

## Action item execution playbook

Each action item's `api_action.type` maps to a function in `api_actions.py`:

| `api_action.type` | Function called | Required params |
|---|---|---|
| `pause_ad` | `pause_ad(entity_id)` | `entity_id` |
| `pause_campaign` | `pause_campaign(entity_id)` | `entity_id` |
| `pause_adset` | `pause_adset(entity_id)` | `entity_id` |
| `activate_campaign` | `activate_campaign(entity_id)` | `entity_id` |
| `update_optimization_goal` | `set_adset_optimization_goal(entity_id, goal)` | `entity_id`, `suggested_value` |
| `reallocate_budget` | `reallocate_budget(from_id, to_id, amount)` | confirm amount with user first |
| `monitor` | (no API call; flag for manual creative refresh) | — |
| `manual_review` | (no API call; surface as guidance) | — |

For any action that materially changes spend (budget moves, activations), always re-confirm
the rupee amount with the user before calling the API.

---

## Creating new campaigns / creatives

When the user asks "create a new campaign for X" or "generate a new creative":

1. **Campaign skeleton:** Call `create_campaign(name, objective, daily_inr)` to create a paused campaign.
   The skill creates the campaign in PAUSED status as a safety default.
2. **Ad sets and ads:** Direct the user to Ads Manager (UI is faster for first-time setup with
   creative assets, targeting refinement, and bid strategy choices). Note in the response that
   the campaign skeleton was created and the URL to finish setup:
   `https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=<AD_ACCOUNT_ID>`
3. **For creative generation:** Delegate to the `social-create` skill, which produces ready-to-upload
   image + video assets. Save them to `assets/social/` and reference them when uploading in Ads Manager.

---

## Failure handling

- **`META_ADS_TOKEN` invalid:** Surface this clearly. The user generated this as a System User token
  on the "Bhookle Ads API" app. To regenerate: business.facebook.com/settings/system_users →
  Arvind Ravichandran → Generate New Token → Bhookle Ads API → ads_read + ads_management.
- **Peer-approval block on writes:** If a write action returns "permission error", remind the user
  that their Security Centre may require peer approval for ad-account edits. Toggle that off
  before retrying.
- **GH Actions cron failure:** Check `Actions` tab on GitHub. The workflow has retry-friendly
  cron schedules (4pm, 4:15pm, 4:30pm IST) to survive GH's cron jitter.

---

## Tone of analysis

When generating commentary, **write like a senior performance marketer would speak to a founder**:
- Be specific. "CPI is high" is useless; "CPI of ₹6.08 is 2.3× the ₹2.68 benchmark of our best campaign"
  is actionable.
- Pair every issue with a recommended action.
- Cite the metric and time window. "CTR dropped 18% week-over-week" beats "CTR is down."
- Flag risks proactively. If a creative is 8 months old, mention it even if the metrics still look OK —
  fatigue is a leading indicator, not a lagging one.
- Avoid jargon ("ROAS-positive Q4 hookcraft") — write plainly. The user is the founder.

---

## Output examples

The skill produces three artifacts on every run:

1. **JSON** (machine-readable) — full structured data, used by `/show-ad-research`.
2. **PDF** (human-readable) — Bhookle-branded 8-section report.
3. **Email** (when triggered) — HTML + PDF attachment to owner@example.com.

The PDF always has these sections in this order:
1. Cover page
2. Executive Summary (KPIs + narrative)
3. Campaign Performance (table + per-campaign commentary)
4. Creative Fatigue Analysis (table + HIGH-fatigue deep-dives)
5. New Creative Watch (launch cohort ≤28 days old vs incumbent benchmark; learning-phase-aware verdicts — LEARNING ads are never judged or flagged for fatigue)
6. Targeting & Audience Review (per ad set, with flags)
7. Budget Reallocation (specific moves with rationale)
8. Improvement Opportunities (untapped levers)
9. Action Items (prioritized, executable — includes New Creative cohort actions: NO_TRACTION→review, UNDERPERFORMER→pause, WINNER→scale)
