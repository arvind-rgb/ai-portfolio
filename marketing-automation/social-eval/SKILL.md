---
name: social-eval
version: 1.0.0
description: >
  Use this skill for ANY request to evaluate Bhookle's social media accounts,
  analyse Instagram or Facebook reels, generate a social performance report,
  run competitive social analysis, or benchmark against competitors.
  TRIGGER immediately when the user says "run social eval", "analyse my reels",
  "social report", "evaluate instagram", "evaluate facebook",
  "competitor social analysis", "what's working on social", or any similar phrasing.
  Do NOT attempt to produce a social eval report without this skill — it carries
  the Windsor.ai MCP integration, the branded PDF generator, the 7-section analysis
  framework, and all Bhookle-specific context needed to produce an actionable report.
user-invocable: true
---

# Bhookle Social Eval Skill

You are Bhookle's social media performance analyst. Every run of this skill produces one
branded PDF report covering owned-account performance, reel-level analysis, and competitive
benchmarking against @cookr.india and @app_good_food.

The report has 7 sections (see `references/sections.md` for the full spec of each).
The PDF is built from a JSON content file by `scripts/build_report.py`
(see `references/pdf-spec.md` for the JSON schema).

---

## Files in this skill

| File | Purpose | When to read |
|---|---|---|
| `references/sections.md` | Full spec for all 7 report sections | Always — read before writing any section |
| `references/pdf-spec.md` | PDF layout rules, JSON schema, block types | Always — read before building the JSON |
| `scripts/build_report.py` | Generates the branded PDF from the JSON file | Run at the end of every eval run |

---

## Output

| Field | Value |
|---|---|
| Primary PDF | `social/bhookle-social-eval-YYYY-MM.pdf` |
| Primary JSON | `social/bhookle-social-eval-YYYY-MM.json` |
| Archive PDF | `_skills/social-eval/output/bhookle-social-eval-YYYY-MM.pdf` |
| Archive JSON | `_skills/social-eval/output/bhookle-social-eval-YYYY-MM.json` |
| Data window | Last 90 days (Instagram + Facebook) |

---

## Brand tokens (PDF output)

| Token | Hex | Use |
|---|---|---|
| Bhookle Purple | `#7030A0` | Section headers, cover page, chart accent |
| Mustard Yellow | `#FFC000` | Callout boxes, key stats |
| Dark Grey | `#333333` | Body text |
| White | `#FFFFFF` | Page background |

---

## Workflow — step by step

### Step 0 — Version check

Before starting, check whether a report for the current month already exists:
```bash
ls "social/bhookle-social-eval-$(date +%Y-%m).pdf" 2>/dev/null
```
If it exists: **overwrite in place. No prompt, no versioning.**

---

### Step 1 — Windsor.ai data pull (owned accounts)

**IMPORTANT — connector availability check (do this first):**

Call `mcp__fb2ee40f-957d-41ca-b7f8-2b71e80059a4__get_connectors` to list active connectors.
Look for Instagram and Facebook connectors. If neither is present or both show as
unauthorised, call `mcp__fb2ee40f-957d-41ca-b7f8-2b71e80059a4__get_connector_authorization_url`
and show the user the URL to authenticate, then stop. Do not proceed without data.

**1a. Discover available fields:**
```
tool: mcp__fb2ee40f-957d-41ca-b7f8-2b71e80059a4__get_fields
connector: instagram  (use the exact connector ID returned by get_connectors)
```
Repeat for Facebook. Note which metric fields are available (reach, plays, impressions,
likes, comments, shares, saves, engagement_rate, follower_count, timestamp, caption, etc.)

**1b. Pull Instagram reel data (last 90 days):**
```
tool: mcp__fb2ee40f-957d-41ca-b7f8-2b71e80059a4__get_data
connector: instagram
date_from: [90 days ago in YYYY-MM-DD]
date_to: [today in YYYY-MM-DD]
fields: [all available fields from step 1a]
```
Save raw response as `ig_data`. Extract reel-level rows (filter content_type = reel if
the field exists) plus account-level aggregates (follower count, page-level reach).

**1c. Pull Facebook page + reel data (last 90 days):**
```
tool: mcp__fb2ee40f-957d-41ca-b7f8-2b71e80059a4__get_data
connector: facebook
date_from: [90 days ago in YYYY-MM-DD]
date_to: [today in YYYY-MM-DD]
fields: [all available fields from step 1a for facebook]
```
Save raw response as `fb_data`.

**1d. Derive key aggregates from the raw data:**
- Total reels published in 90 days
- Average engagement rate (likes + comments + saves + shares) / reach × 100
- Top 5 reels by engagement rate — capture caption snippet, publish date, key metrics
- Bottom 5 reels by engagement rate
- Best-performing day of week (by avg engagement)
- Content theme classification: for each reel, tag with one of:
  Chef Story, Food Visual, Offer/Discount, UGC/Testimonial, Educational, Behind-the-Scenes
- Aggregate engagement by theme
- 30-day follower growth delta (if available)

If the Windsor.ai connector returns aggregate data rather than post-level data,
use what's available and note the limitation clearly with ⚠️ in the report.

---

### Step 2 — Competitor research (WebSearch)

Windsor.ai does not hold competitor account data. Use WebSearch + WebFetch:

**For @cookr.india:**
- Search: `cookr.india instagram reels 2025 2026`
- Search: `cookr india food app instagram strategy`
- Document: approximate follower count (SocialBlade or visible profile), posting cadence,
  dominant content themes, brand tone, CTA patterns, recent campaigns

**For @app_good_food:**
- Search: `app_good_food instagram reels strategy`
- Search: `good food app india instagram 2025 2026`
- Document: same dimensions as above

**For benchmarks:**
- Search: `home food delivery app india instagram engagement rate 2025`
- Flag any unverified estimates with ⚠️
- Note: competitor data is observational — never present it as audited metrics

---

### Step 3 — Write all 7 sections

Write sections 2–7 first, then write Section 1 (Executive Summary) last.
See `references/sections.md` for exact output requirements per section.

**Voice rules:**
- Data-backed and specific — reference actual reel captions, real numbers from Windsor.ai
- Actionable — every observation must connect to a recommendation
- Human-first — Bhookle's brand is about people, not product features; reflect that in analysis
- Never invent data — write "data unavailable" or flag with ⚠️ when estimates are used
- Competitor data: always flag as estimated/observed, never as audited

---

### Step 4 — Build the JSON content file

Assemble all written content into a JSON file. See `references/pdf-spec.md` for schema.

**Always write JSON via Bash heredoc — never use the Write tool (it fails on large content):**
```bash
cat > /tmp/social_eval_content.json << 'HEREDOC'
{
  "month": "May 2026",
  "generated_date": "2026-05-16",
  "sections": [ ... ]
}
HEREDOC
```

---

### Step 5 — Generate PDF, persist JSON, and copy to output

```bash
# Build primary output
python3 .claude/skills/social-eval/scripts/build_report.py \
  /tmp/social_eval_content.json \
  "social/bhookle-social-eval-$(date +%Y-%m).pdf"

# Persist JSON alongside PDF (used as input by downstream skills e.g. social-planner)
cp /tmp/social_eval_content.json \
   "social/bhookle-social-eval-$(date +%Y-%m).json"

# Archive copies (always)
mkdir -p "_skills/social-eval/output"
cp "social/bhookle-social-eval-$(date +%Y-%m).pdf" "_skills/social-eval/output/"
cp "social/bhookle-social-eval-$(date +%Y-%m).json" "_skills/social-eval/output/"
```

Three output locations are always written: PDF + JSON in `social/`, both archived in `_skills/social-eval/output/`.

---

### Step 6 — Sync files to runtime location

After any change to skill files, sync:
```bash
cp -r _skills/social-eval/. .claude/skills/social-eval/
```

---

## Behaviour rules

1. **Always cite.** Every metric needs a source: Windsor.ai connector pull date, or web search URL + access date.
2. **Never invent competitor data.** If unavailable, write "data unavailable" or "⚠️ estimated from public profile".
3. **Overwrite in place.** Same-month reports are replaced silently — no prompt.
4. **Data limitation transparency.** If Windsor.ai returns only aggregate (not post-level) data, note this prominently.
5. **Engagement formula.** Always define engagement rate used: (likes + comments + saves + shares) / reach × 100.
6. **Theme classification.** Always classify every reel into one of 6 themes before writing Section 3.
7. **JSON via Bash heredoc only.** Never use the Write tool for JSON content files.
8. **Three outputs always.** PDF + JSON in `social/` (primary), both archived in `_skills/social-eval/output/`. The JSON is the handoff file for downstream skills.
9. **Section 1 written last.** Executive Summary is always the last section written, placed first in PDF.
