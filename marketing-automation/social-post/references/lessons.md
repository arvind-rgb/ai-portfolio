# Hard-won Lessons — Social Posting

Every item here represents hours of debugging. Read this BEFORE making changes to the
posting pipeline or troubleshooting failures.

---

## Meta / Instagram

### Auth & app setup
- **App MUST be in "Live" mode**, not Development. `instagram_content_publish` returns
  `(#10) Application does not have permission` in Dev mode no matter what scopes you have.
- **`instagram_basic` is required alongside `instagram_content_publish`**. The token needs
  both. Without `instagram_basic`, the publish API silently fails with `(#10)`.
- **@bhookleeats IG must be linked to the Bhookle Eats Facebook Page via crossposting**
  (Instagram app → @bhookleeats profile → Professional dashboard → Settings → Business →
  Crossposting → "Crosspost to Facebook Page instead"). Without this link, the IG account
  appears unreachable to the Graph API.
- Long-lived Meta tokens report `expires_at: 0` (no hard expiry) but the real practical
  limit is `data_access_expires_at` (~60 days). The expiry check uses
  `data_access_expires_at` as fallback.
- Token refresh: 60 days, see `setup.md §1`.

### Media uploads
- **Direct video upload via `/{ig-user-id}/video_reels` does NOT work** for our token type.
  Use `video_url` parameter pointing to a public URL instead.
- **Meta rejects PNG** for IG posts. Always convert to JPG before upload.
  (`ensure_jpg()` in post_instagram.py does this automatically with Pillow.)
- **Public asset hosting:** 0x0.st shut down (AI spam ban). We use **catbox.moe** — free,
  no signup, 200MB limit, reliable. See `upload_to_catbox()`.

### Scheduling
- `publish_at` parameter takes a Unix timestamp. Min: 10 minutes from now. Max: 75 days.
- All planner times are IST (UTC+5:30). Convert with `pytz` before sending — never assume
  the local timezone of the runner machine matches IST.
- IG has a hard limit of 25 published posts per rolling 24h window. The "30 in batch"
  warning in the runner is misleading — that's spread over 30 days, not 1 day.

### Carousels
- Convention: assets are named `IG-XXX-slide1.png`, `IG-XXX-slide2.png`, … `slideN.png`
  in the same folder as the cover image.
- PostOutput column can be:
  - A single path (single image post)
  - Comma-separated paths (`find_carousel_slides()` parses these)
  - Empty (function falls back to glob `IG-XXX-slide*.png` in the project's default
    assets dir)
- Carousel posting flow: upload each slide → create child container with
  `is_carousel_item=true` → after all children, create parent with `media_type=CAROUSEL`,
  `children=<comma-separated-child-ids>`, and `publish_at`.

---

## LinkedIn

### Auth & products
- **No native scheduling API.** We work around this with GitHub Actions cron — the skill
  generates one cron job per post in `.github/workflows/bhookle-linkedin-posts-YYYY-MM.yml`.
- `r_liteprofile` scope is **deprecated**. Use `openid profile email w_member_social`
  instead. Get the user URN from the `/v2/userinfo` endpoint (OpenID Connect), not `/v2/me`.
- The LinkedIn OAuth callback at `localhost:8765/callback` may show a "Bummer" page in
  the browser — but the local server already captured the code. Check the script output,
  not the browser.
- **Community Management API (posting as company page) needs its own dedicated LinkedIn
  app** — cannot coexist with Share on LinkedIn / OpenID Connect. Requires LinkedIn
  approval (5–10 business days). Until approved, posts go to the personal profile.
- Token refresh: 60 days, re-run `linkedin_auth.py`.

### Workaround for company page visibility
- Since posts go to personal profile only (no Community Management API yet), every
  LinkedIn post description ends with:
  `— Posted by Arvind, Founder at @Bhookle | linkedin.com/company/bhookle`
- LinkedIn auto-renders the company URL as a rich preview card under the post.

### GitHub Actions cron
- Each post becomes one cron entry in the workflow YAML, calling
  `_skills/social-post/scripts/post_linkedin.py --post-id <ID> --planner <path>`.
- Required GitHub Secrets: `LI_ACCESS_TOKEN`, `LI_AUTHOR_URN`.
- The workflow checks the planner Excel into the repo (excluded from .gitignore
  exclusions specifically) so cron runs can read schedules and update statuses.
- After post: cron commits the updated PostStatus back to the repo (`git add planner;
  git commit; git push`) so local + cloud stay in sync.

---

## Excel planner conventions

- Status chain: `Draft` → `Creative Locked` → `Scheduled (IG)` / `GH Actions Generated`
  → `Posted` / `Failed`. Runner only picks up `Creative Locked`.
- Setting status to `Failed` is auto-done by the runner on errors. To retry, manually
  reset to `Creative Locked`.
- `PostOutput` can hold a single absolute path OR comma-separated paths (carousels).
- `PostTime (IST)` accepts both `7:00 PM` and `19:00` formats.
- Captions must NEVER reference `bhookleeats.com` — runner auto-replaces with
  "Download the Bhookle app". But the source-of-truth fix is to not write the URL in
  the first place (see `feedback_no_url_always_app.md` memory).

---

## Pre-flight gates (already automated)

The runner now refuses to start posting if:
1. Either token is expired (`data_access_expires_at` < now for IG, or LinkedIn
   `/v2/userinfo` returns 401)
2. Required env vars are missing
3. The planner Excel file is not findable

Warns (does not block) if either token has <7 days left.

---

## ⚠️ CRITICAL LESSON: `publish_at` does NOT work for our account

**What we tried:** Pre-uploading IG containers with `publish_at=<unix_ts>` so Meta would
auto-publish at the scheduled time, computer-independent.

**What actually happened:**
- `publish_at` was **silently ignored** by Meta — the parameter only works on specific
  enterprise accounts with Meta Business Suite enrollment + extra permissions
- Containers stayed in `"Finished: Media has been uploaded and it is ready to be
  published"` status but never auto-published
- **Containers expire after ~24 hours** if `/media_publish` is never called
- All 30 pre-scheduled IG posts expired before any could fire

**Architectural correction (mandatory):**
- DO NOT pre-upload IG containers. Use the same pattern as LinkedIn — GitHub Actions cron
  job per post that runs at the scheduled time and does: upload slides → create container
  → immediately call `/media_publish` → mark Posted in planner.
- Container creation and publish must happen within the same job, within ~5 minutes of
  each other. Never separate them by hours.

---

## Email notifications (per-post, baked into workflow)

Every cron job auto-includes a Gmail SMTP step that emails on success or failure.
This is generated by `_job_steps()` in `gen_github_actions.py` — DO NOT remove
unless replaced with an equivalent monitoring path.

Secrets used:
- `GMAIL_USER` — full email address (e.g. `owner@example.com`)
- `GMAIL_APP_PASSWORD` — 16-char Google App Password (NOT regular password)

Gotchas observed:
- **"Bad Credentials 535-5.7.8"** from `dawidd6/action-send-mail@v3` = wrong App Password.
  Always strip spaces from the 16-char password before pasting into GitHub Secret.
- Google App Passwords require **2-Step Verification ON** for the account; otherwise
  the App Passwords page is hidden in account settings.

A safe `TEST_EMAIL` workflow_dispatch entry exists in every generated workflow —
trigger it (via Actions UI → Run workflow → input `TEST_EMAIL`) to verify Gmail
credentials without posting anything to IG/LinkedIn.

---

## ⚠️ CRITICAL LESSON: verify slide count BEFORE publishing (don't trust the function)

**What happened (2026-05-24):** Published IG-013 with 10 slides instead of 5 because both
`.png` (originals) and `.jpg` (auto-converted) existed in the assets dir, and
`find_carousel_slides()` returned both. Bad post had to be manually deleted from IG
(Meta API doesn't allow programmatic delete of published posts).

**Rules going forward:**
1. `find_carousel_slides()` now **dedupes by file stem** (keeps JPG over PNG when both exist).
2. **Always assert expected slide count BEFORE calling `/media_publish`**:
   - Cross-check against the planner if the row has a slide count column, OR
   - Print the slide list and require sanity (e.g., `len(slides) <= 10` per IG carousel limit)
3. **If unsure, abort and report instead of publishing.** Once published, removal is manual.
4. The reusable publish helper must include the guardrail
   `assert len(slides) == expected_count` before parent container creation.
