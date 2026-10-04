---
name: email-outreach
version: 1.0.0
description: >
  Use this skill for ANY request to create email campaigns, run email outreach,
  send email campaigns, or manage Bhookle email marketing. TRIGGER immediately
  when the user says "create email campaign", "run email outreach", "send email
  campaign", "email marketing for Bhookle", or invokes /email-outreach.
  Backed by Resend (free tier: 100/day, 3,000/month). Runs a 5-stage gated
  workflow: interview → audience ingest → send-time research → dispatch
  (GitHub Actions) → performance tracking (GitHub Actions). Computer-independent
  for stages 4-5.
user-invocable: true
---

# Email Outreach Skill

## Quick start
```bash
# Stage 2: ingest audience CSV after Claude finishes Stage 1
python3 _skills/email-outreach/scripts/ingest_audience.py <slug> <path/to/audience.csv>

# Stage 4+5: generate GitHub Actions workflows (run after Stage 3)
python3 _skills/email-outreach/scripts/gen_github_actions.py

# Check environment (Resend key, domain, Python packages)
python3 _skills/email-outreach/scripts/dispatch_batch.py --check-env

# Manual dispatch (testing only — Actions handles this in production)
python3 _skills/email-outreach/scripts/dispatch_batch.py --dry-run

# Force stats refresh
python3 _skills/email-outreach/scripts/fetch_stats.py --days 7
python3 _skills/email-outreach/scripts/update_master_xlsx.py
```

## Files
| File | Purpose |
|---|---|
| `scripts/ingest_audience.py` | Stage 2: validate CSV, dedupe, build send-plan.json |
| `scripts/gen_hero_image.py` | Stage 1: generate campaign hero via Imagen 4 Ultra |
| `scripts/dispatch_batch.py` | Stage 4: daily Resend batch dispatch (used in GH Actions) |
| `scripts/fetch_stats.py` | Stage 5: poll Resend /emails/{id}, update results.json |
| `scripts/update_master_xlsx.py` | Stage 5: roll results into campaigns-master.xlsx |
| `scripts/gen_github_actions.py` | Generates dispatch + stats GH Actions workflows |
| `references/resend-api.md` | Resend endpoints, rate limits, auth |
| `references/batch-math.md` | Free-tier batching logic and quota math |
| `references/interview-template.md` | Stage 1 Q&A template |

## Credentials (`.env` in project root)
```
RESEND_API_KEY=re_xxxx          # Resend API key — NEVER commit to git
GEMINI_API_KEY=...              # For Imagen 4 Ultra hero images
```
GitHub Secrets required (repo Settings → Secrets → Actions):
```
RESEND_API_KEY                  # Same key — for GH Actions dispatch & stats
```

## Campaign folder layout
```
email-marketing/
├── campaigns-master.xlsx              # Live status + performance for all campaigns
└── campaigns/
    └── <slug>/
        ├── config.json                # Campaign metadata + send slot
        ├── brief.md                   # Q&A capture + approved copy
        ├── subject.txt
        ├── body.html
        ├── body.txt
        ├── hero.png                   # Imagen 4 Ultra output
        ├── audience.csv               # Uploaded by user (Stage 2)
        ├── send-plan.json             # Batches ≤90/day keyed by date
        ├── sent-log.csv               # resend_id, email, sent_at (appended by Actions)
        └── results.json               # Rolled-up events (delivered/opened/clicked/etc.)
```

## 5-Stage Orchestration

### Stage 1 — Interview & Ideate (Claude drives, no script)
**What Claude does:**
1. Ask the Q&A questions from `references/interview-template.md` in 3 rounds.
2. Draft `{name, subject, preview_text, body_html, body_txt, image_prompt}` per campaign.
3. Run `gen_hero_image.py` for each campaign hero image.
4. Present draft + image to user. Iterate until user says **"approve"**.
5. Create `email-marketing/campaigns/<slug>/` and write `brief.md`, `subject.txt`, `body.html`, `body.txt`, `config.json`.

**Rules:**
- Always invoke `bhookle-brand-voice` skill before writing any copy.
- CTAs always say "Download the Bhookle app" — never a URL.
- Never include `bhookleeats.com` anywhere.
- `from_email` is always `team@example.com`, `from_name` is `Bhookle`.

### Daily dispatch report
After every dispatch run (including GH Actions cron runs), `dispatch_batch.py`
verifies each Resend message via `GET /emails/{id}` and emails a summary
to `EMAIL_ADMIN_RECIPIENT` (default: `owner@example.com`).

**Sent via Gmail SMTP** (reuses `GMAIL_USER` / `GMAIL_APP_PASSWORD` GH Secrets
already configured for the social-post skill). **Zero Resend quota impact.**

Report includes per-campaign: sent / delivered / pending / failed counts.
Skipped in `--test` and `--dry-run` modes.

To change recipient: set `EMAIL_ADMIN_RECIPIENT` env var.

## Permanent test seeds
`references/test-seeds.json` holds 3 QA addresses always prepended to batch 1 of every campaign:
- `owner@example.com`, `owner@example.com`, `owner@example.com`

To add/remove seeds, edit `references/test-seeds.json` only — `ingest_audience.py` reads it automatically.

## Stage 2 — Audience Ingest (script)
**What Claude does:**
1. Say: *"Please share the audience CSV for [campaign name]. It needs name and email columns."*
2. Wait for user to provide the file path or paste the path.
3. Run: `python3 _skills/email-outreach/scripts/ingest_audience.py <slug> <csv_path>`
4. Show the summary output: record count, deduped count, batch plan, quota warning if any.
5. If monthly quota > 3,000 or daily collision detected → warn user and ask how to proceed.

### Stage 3 — Send-Time Research (Claude drives)
**What Claude does:**
1. Use WebSearch: "best email send time B2C food delivery India 2025"
2. Combine with Bhookle priors: lunch audience 10:30 IST, dinner audience 17:30 IST.
3. Present recommendation with data source summary.
4. Ask user to confirm (or pick from options).
5. Write confirmed IST time to `config.json` as `send_time_ist: "HH:MM"`.

### Stage 4 — Dispatch Workflow (script → GH Actions)
**What Claude does:**
1. Run: `python3 _skills/email-outreach/scripts/gen_github_actions.py`
2. Show the generated `.github/workflows/email-dispatch.yml` path.
3. Tell user: *"Commit and push this file. GitHub Actions will handle all future sends — your computer can be off."*
4. Instruct user to add `RESEND_API_KEY` to GitHub Secrets if not done.

**Hard guards (enforced in dispatch_batch.py):**
- Refuses to send if no verified Resend domain.
- Refuses if today's planned + already-sent > 100.
- Logs every send to `sent-log.csv` before returning.

### Stage 5 — Performance Tracking (GH Actions, auto)
- `email-stats.yml` runs daily at 02:00 IST (20:30 UTC).
- Polls `GET /emails/{id}` for each message sent in last 7 days.
- Updates `results.json` → rolls up into `campaigns-master.xlsx`.
- No action needed from user — runs cloud-side.

## Status chain
`Draft` → `Approved` → `Audience Loaded` → `Scheduled` → `In Progress` → `Complete`

## Email template (non-negotiable)
All campaigns use `templates/base-email.html`. Key rules from the Bhookle design system:
- **Logo:** NEVER a separate header band. Always run `stamp_logo.py <slug>` after hero generation — this composites `logo-full-orange.png` top-left onto `hero.png` with a dark scrim for contrast. Logo is baked into the image.
- **Background:** always `#FFF8EC` (cream). Never pure white.
- **Footer:** mulberry `#3D0C11` band with cream text
- **CTA button:** `#FF6B00` orange, 12px radius. Use `<div class="cta-btn">` (no `<a href>`) until a Bhookle app deep link is confirmed. CTA text is always "Order Now on your Bhookle App". Update to `<a href="bhookle://...">` once deep link is provided.

## Stage 1 image generation order (always follow this sequence)
1. `gen_hero_image.py <slug> "<prompt>"` — generate hero
2. `stamp_logo.py <slug>` — bake logo into hero
3. `gen_hero_image.py` or `gemini-3-pro-image-preview` for any supporting images (founder photo, etc.)
4. Share preview link: `file://~/bhookle-marketing/email-marketing/campaigns/<slug>/body.html`
5. Wait for explicit **"approve"** before setting status to `Creative Locked`

## Preview & approval step (Stage 1, after image generation)
After generating all images, tell the user:
> "Open this in your browser to preview: `file://~/bhookle-marketing/email-marketing/campaigns/<slug>/body.html`"
Wait for explicit **"approve"** before saving config status as `Creative Locked`.

## Rules
1. Never commit `RESEND_API_KEY` — it must only live in `.env` (gitignored) and GH Secrets.
2. Batch size ≤ 90/day (10-email safety margin under 100/day cap).
3. Warn if projected monthly total > 3,000.
4. Always `--dry-run` before first live dispatch.
5. Free-tier open/click tracking is polling-based — data appears next morning after stats cron.
6. After any skill file edit:
   `cp -r _skills/email-outreach/. .claude/skills/email-outreach/`

## GitHub Secrets setup (one-time)
Repo → Settings → Secrets and variables → Actions → New repository secret:
- `RESEND_API_KEY` — your Resend API key

## Outputs
- `email-marketing/campaigns-master.xlsx` — live campaign registry with performance
- `.github/workflows/email-dispatch.yml` — daily batch sender
- `.github/workflows/email-stats.yml` — daily stats poller
- `email-marketing/campaigns/<slug>/sent-log.csv` — immutable send audit
- `email-marketing/campaigns/<slug>/results.json` — rolling performance
