---
name: social-post
version: 2.0.0
description: >
  Use this skill for ANY request to post content to Instagram or LinkedIn, publish
  scheduled posts from the content planner, run the social posting workflow, or update
  post statuses after publishing. TRIGGER immediately when the user says "post to instagram",
  "post to linkedin", "run social post", "publish locked posts", "schedule posts",
  "post approved content", or similar.
  ARCHITECTURE (v2.0 — 2026-05-25): a single GitHub Actions workflow
  (.github/workflows/bhookle-social-tick.yml) fires every 15 min and posts whatever
  is due from the planner via scripts/social_tick.py. The skill's only job at
  planning time is to mark posts as "Creative Locked" in the planner xlsx —
  NO per-post cron generation, NO per-month workflow files. This avoids GH Actions
  cron queueing delays that plagued v1.x (where 41 stacked crons caused 3+ hour
  posting delays). gen_github_actions.py is DEPRECATED — do not call it.
user-invocable: true
---

# Social Post Skill (v2.0)

## 🚨 CRITICAL: Commit + push the planner after EVERY edit

**The 2026-06-06 incident:** local planner was edited to move IG-006 → Jun 27 and add
IG-031, but the changes were not committed/pushed before the next cron tick. The GH
Actions runner read the **old** planner from GitHub and fired IG-006 anyway — causing
a duplicate post that had to be manually deleted from Instagram.

**The cron tick runs on GitHub Actions, not your laptop.** It only ever sees what's
committed and pushed. ANY change to:
- `content-planner/bhookle-content-calendar-*.xlsx`
- `assets/_posted-log.csv`
- `assets/_cloudinary-manifest.json`

…MUST be followed **immediately** by:
```bash
git pull --rebase   # in case the remote cron pushed since last pull
git add content-planner/*.xlsx assets/_posted-log.csv assets/_cloudinary-manifest.json
git commit -m "<one-line summary>"
git push
```

`lock_post.py` and `post_instagram.py` do NOT push for you. Skipping this step means
the next 15-min cron tick will use stale state.

## 🚨 CRITICAL: How to mark a post "Creative Locked"

**NEVER** directly edit the `PostStatus` column to "Creative Locked" in the planner.
**ALWAYS** use `lock_post.py` — it atomically syncs the asset to Cloudinary
before flipping the status, which is the ONLY way to guarantee the GH Actions
runner will be able to fetch the asset at posting time.

```bash
python3 _skills/social-post/scripts/lock_post.py --post-id IG-004
# → verifies asset exists locally
# → uploads to Cloudinary (idempotent)
# → updates PostStatus to "Creative Locked"
# → fails atomically if any step errors (never leaves an undeployed lock)
```

If a post is marked Creative Locked without its asset on Cloudinary, the
runner's preflight will mark it Failed and email you. This is the safety net,
but `lock_post.py` is the gate that prevents the issue in the first place.

## Quick start (posting flow)
```bash
# 1. After generating an asset, lock the post (asset auto-syncs to Cloudinary)
python3 _skills/social-post/scripts/lock_post.py --post-id IG-004

# 2. Commit + push (tick worker picks up automatically within 15 min)
git add content-planner/*.xlsx assets/_cloudinary-manifest.json
git commit -m "lock IG-004"
git push

# 3. Wait for the tick worker email. No further action needed.
```

## Files
| File | Purpose |
|---|---|
| `scripts/lock_post.py` | **USE THIS to mark posts Creative Locked.** Atomic asset sync + status flip. |
| `scripts/sync_assets.py` | Bulk Cloudinary sync for an entire month's assets |
| `scripts/social_tick.py` | Dispatcher run by GH Actions every 15 min |
| `scripts/post_instagram.py` | IG Graph API immediate poster (JIT-fetches missing assets) |
| `scripts/post_linkedin.py` | LinkedIn API immediate poster (JIT-fetches missing assets) |
| `scripts/update_planner.py` | Low-level: writes status back to Excel |
| `scripts/linkedin_auth.py` | One-time LinkedIn OAuth helper |
| `scripts/social_post_runner.py` | Legacy bulk runner — only for ad-hoc manual posting |
| `scripts/gen_github_actions.py` | **DEPRECATED** — do not call. Replaced by social_tick.py |
| `references/setup.md` | Token refresh + first-time setup |
| `references/column-map.md` | Excel column reference |
| `references/lessons.md` | **READ THIS BEFORE DEBUGGING** — hard-won lessons (Meta quirks, LinkedIn workarounds, format requirements, auth gotchas, asset deploy gotchas) |

## Credentials

### Local `.env` (project root) — for running runner manually
```
IG_USER_ID, IG_ACCESS_TOKEN          # Meta — 60-day token
IG_APP_ID, IG_APP_SECRET             # For token refresh
FB_PAGE_ID                           # Bhookle Eats page (reference)
LI_ACCESS_TOKEN, LI_AUTHOR_URN       # LinkedIn — 60-day token
LINKEDIN_CLIENT_ID/SECRET            # For LinkedIn re-auth
```

### GitHub Secrets (Repo → Settings → Secrets → Actions) — for cloud cron
Same 4 platform secrets above (`IG_USER_ID`, `IG_ACCESS_TOKEN`, `LI_ACCESS_TOKEN`, `LI_AUTHOR_URN`)
**plus** for the email notifications:
```
GMAIL_USER              # owner@example.com
GMAIL_APP_PASSWORD      # 16-char Google App Password (NOT regular Gmail password)
                        # Generate at: https://myaccount.google.com/apppasswords
                        # Requires 2-Step Verification ON for the Google account.
```

## Source of truth
`content-planner/bhookle-content-calendar-YYYY-MM.xlsx` — both `Instagram_Facebook` and
`LinkedIn` tabs. Runner picks rows where `PostStatus == "Creative Locked"`.

## How scheduling works
- **Instagram**: Meta's `publish_at` parameter holds the post on Meta's servers and
  publishes at the scheduled UTC time. Computer can be off. Range: 10 min – 75 days.
- **LinkedIn**: No native scheduling API. Skill generates
  `.github/workflows/bhookle-linkedin-posts-YYYY-MM.yml` with one cron per post.
  Commit + push it once → GitHub Actions runs each post at its scheduled time.
  Required GitHub Secrets: `LI_ACCESS_TOKEN`, `LI_AUTHOR_URN`.

## Status chain
`Creative Locked` → `GH Actions Generated` → `Posted` / `Failed`

## Email notifications (built-in)
Every cron job ends with a Gmail SMTP email step (via `dawidd6/action-send-mail@v3`).
You get one email per post — success or failure — with title, post ID, platform,
schedule time, and a link to the workflow run. A safe `TEST_EMAIL` workflow_dispatch
job exists to verify Gmail credentials without posting anything.

This is permanent — regenerated automatically every time the runner produces a new
month's workflow. No re-configuration needed. Just keep the `GMAIL_USER` and
`GMAIL_APP_PASSWORD` GitHub Secrets valid.

## Rules
1. Always `--dry-run` first and confirm before posting.
2. All planner times are IST (UTC+5:30) — runner converts to UTC.
3. Only process `Creative Locked` rows; never re-schedule already-handled ones.
4. Strip `bhookleeats.com` URL → "Download the Bhookle app" in every caption.
5. IG hard limit: 25 posts/24h. Warn if a run exceeds this.
6. After any skill file edit:
   `cp -r _skills/social-post/. .claude/skills/social-post/`

## Outputs
- Excel `PostStatus` updated in place
- `.github/workflows/bhookle-linkedin-posts-YYYY-MM.yml` (commit + push)
- `_skills/social-post/output/post_log_YYYY-MM.json` (audit log)
