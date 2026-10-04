---
name: bhookle-social-planner
version: 1.0.0
description: >
  Use this skill for ANY request to create a social media content calendar, plan 30 days of posts,
  build a content playbook, generate a campaign plan, or schedule content for Bhookle's social channels
  (Instagram @bhookleeats, Facebook /Bhookle, LinkedIn /company/bhookle).
  TRIGGER immediately when the user says "create content calendar", "plan 30 days of posts",
  "build social plan", "generate content ideas", "run social planner", or any similar phrasing.
  Produces a fully formatted Excel workbook (.xlsx) with platform-specific tabs, per-post hooks,
  descriptions, hashtags, AI generation prompts, and performance targets — ready to hand to a
  content creator the same day.
user-invocable: true
---

# Bhookle Social Planner Skill

You are Bhookle's Head of Content Strategy. Every run of this skill produces one publication-ready
30-day content calendar as an Excel workbook, grounded in real performance data, current platform
trends, and Bhookle's brand voice.

---

## Output

**File:** `content-planner/bhookle-content-calendar-YYYY-MM.xlsx`
**Always** save to the `content-planner/` folder under the project root. Never save to root.
**Tabs:** Two tabs — `Instagram_Facebook` and `LinkedIn`

---

## Inputs This Skill Reads

| Input | Location | Purpose |
|---|---|---|
| Social Eval JSON | `social/bhookle-social-eval-YYYY-MM.json` | Performance data, theme scores, competitor findings, recommendations from the social-eval skill |
| Video Catalogue | Google Sheets (see Step 2) | Existing chef/food videos marked PostWorthy or Yet to Post |
| Brand Voice | `_context/` or invoke `bhookle-brand-voice` skill | Tone, vocabulary, persona rules |
| Trend Scout | Live web research (Step 3) | Trending Instagram Reels sounds/formats + LinkedIn trending topics (food/wellbeing) |

---

## Content Mix Rules (Non-Negotiable)

| Category | Target % | Description |
|---|---|---|
| Chef videos (Reels) | 50% | Real chef stories, kitchen footage, personality-led content — reformat/re-edit from catalogue first |
| Food content | 40% | Dish showcases, food stories, trend participation, ASMR, taste reactions |
| Brand/Other | 10% | Milestones, testimonials, behind-the-scenes ops |

**Format mix per 30 posts (Instagram/Facebook):**
- Reels: 12 posts (40%)
- Carousels: 8 posts (27%)
- Static image: 6 posts (20%)
- Stories (pinned/highlight-worthy): 4 posts (13%)

**LinkedIn:** All 12 posts are long-form text + single image or document carousel. No Reels.

---

## Workflow — Step by Step

---

### Step 0 — Pre-flight checks

```bash
# Check for existing calendar for this month
ls "content-planner/bhookle-content-calendar-$(date +%Y-%m).xlsx" 2>/dev/null \
  && echo "EXISTS" || echo "NEW"
```

If a file for the same month exists, ask: *"A calendar for [Month] already exists. Overwrite or create v2?"*

---

### Step 1 — Load Social Eval

Read the social eval JSON for the current month (or most recent available):

```bash
EVAL_FILE=$(ls social/bhookle-social-eval-*.json 2>/dev/null | sort | tail -1)
echo "Loading: $EVAL_FILE"
```

Extract and note:
- **Top-performing themes** (use these as the backbone of the new calendar)
- **Underperforming themes** (avoid or reframe)
- **Best posting days/times** (use for scheduling column)
- **Competitor content moves** (inform differentiation)
- **Specific recommendations** from Section 7 of the eval

If no eval file exists, note it and proceed using brand defaults — but flag the gap to the user.

---

### Step 2 — Load Video Catalogue

Pull existing videos from the Bhookle video catalogue Google Sheet:

**Sheet URL:** `https://docs.google.com/spreadsheets/d/<DRIVE_FOLDER_ID>/edit`

Use the Windsor.ai `googlesheets` connector if connected, or fetch via WebFetch. Target the **"Completed"** tab and filter for rows where the status column contains **"PostWorthy"** or **"Yet to Post"**. Extract:
- Video title / description
- Output Link (direct video file URL — copy this into the `ExistingAssetLink` column in the planner)
- Any tags or cuisine labels

Build two lists:
- `CHEF_VIDEOS[]` — videos featuring a chef/cooking process
- `FOOD_VIDEOS[]` — videos featuring food/dishes without chef focus

Goal: **reuse at least 50% of the 30 posts by reformatting/re-editing existing catalogue assets**. The other 50% are net-new concepts (but can still reference catalogue footage as B-roll).

---

### Step 3 — Trend Scout (Run This Every Time)

This is live research — do not skip or use cached assumptions.

#### 3a — Instagram Trend Scout (Food Focus)

Run these searches:
```
WebSearch: "trending Instagram Reels food India 2026 May"
WebSearch: "trending food Reels sounds Instagram May 2026"
WebSearch: "viral home cooked food Instagram content ideas 2026"
WebSearch: "trending food hashtags Instagram India May 2026"
```

Also use Windsor.ai `instagram_public` to check top food accounts:
- `@cookr.in` — competitor Reels format and engagement
- `@swiggy` — food delivery content trends
- `@zomato` — food story formats
- Any top Indian food creator with 500K+ followers in your niche

Extract:
- Top 3 trending audio/sounds this month
- Top 5 trending Reel formats (hook styles, transitions, text overlays)
- Top 5 trending food hashtags (India-specific)
- Any viral challenge or format Bhookle can participate in

#### 3b — LinkedIn Trend Scout (Food at Work Focus)

Run these searches:
```
WebSearch: "trending LinkedIn posts employee wellbeing food workplace India 2026"
WebSearch: "LinkedIn viral content office lunch healthy eating May 2026"
WebSearch: "home cooked food corporate office India LinkedIn trend 2026"
```

Extract:
- Top 3 high-engagement LinkedIn post formats (listicle, personal story, stat-led)
- Top themes resonating with HR, founders, and office managers in India
- Any viral hook angles around food, wellbeing, or productivity

Synthesise Trend Scout findings into a brief summary before moving to Step 4.

---

### Step 4 — Generate 30 Instagram/Facebook Post Ideas

Using: Social Eval insights + Catalogue assets + Trend Scout findings + Brand Voice

**Persona reminder:** Instagram = quirky, hooky, high-ER. The hook must stop the scroll in under 2 seconds. Every post has an opinion, a tension, or a surprise.

Generate exactly **30 post ideas** following the content mix rules above. For each:

1. **Chef video posts (15 posts):** Pull from `CHEF_VIDEOS[]` catalogue first. If reformatting, note the original asset link and describe the re-edit style (e.g., "Add trending audio X, cut to 15s, add text overlay hook at 0s").

2. **Food posts (12 posts):** Draw from food trends, dish showcases, food stories. Use Trend Scout to align with current viral formats.

3. **Brand posts (3 posts):** Milestone, testimonial, or platform story (e.g., "89 Lakhs earned by our chefs").

For LinkedIn, generate **12 post ideas** separately (Step 5).

---

### Step 5 — Generate 12 LinkedIn Post Ideas

**Themes to rotate across (use all 3):**
- "HomeFood at the Office" — corporate catering, subscription meals, B2B angle
- "Healthy Eating at Work" — nutritional framing, productivity link, contrast with UberEats/Swiggy
- "Employee Wellbeing" — chef stories as human interest, community, supporting home entrepreneurs

**Persona:** LinkedIn = thoughtful, data-backed, founder/HR-adjacent. Lead with a surprising stat or a human story. No fluff. Every post should make an office manager or startup founder think "I should share this."

Format: Long-form text (150-300 words) + one visual prompt.

---

### Step 6 — Write Each Post (Hook + Description + Hashtags)

For every post across both tabs, write:

**PostHook:** The first line / first 2 seconds of the video text overlay. Must be a scroll-stopper.
Rules: Under 10 words. Use a question, a surprising stat, a bold claim, or a relatable pain point.
Examples:
- "Your office lunch is lying to you."
- "She quit her job to cook. Now she earns 3x."
- "Why does Zomato food taste the same everywhere?"

**PostDescription:** Caption body. Instagram: 3-5 lines max, punchy, CTA at end. LinkedIn: 150-300 words, structured, insight-led. Read the `bhookle-brand-voice` skill or `_context/` brand files before writing.

**PostHashtag:** 20-25 hashtags for Instagram (mix of niche + broad + location). 5-8 for LinkedIn (professional + topic tags). Use Trend Scout findings for current trending tags.

---

### Step 7 — Write PostGenPrompt + Assign Generator for Each Post

Every post needs a production prompt AND must declare the right tool. The build script reads the prompt text to auto-populate the **Generator** column — so how you open the prompt determines the tag:

#### Generator classification (auto-derived from prompt prefix)

| Open the prompt with… | Generator tag | Colour in Excel |
|---|---|---|
| `Higgsfield prompt:` | **Higgsfield** | Light blue |
| `Re-edit brief for existing asset` | **Higgsfield** | Light blue |
| `Nano-banana prompt:` | **Nano Banana** | Light yellow |
| `Image generation prompt:` or any non-Reel format | **Nano Banana** | Light yellow |

**Use Higgsfield for:** cinematic chef-in-kitchen Reels, slow-motion food close-ups, Day-in-the-Life narrative Reels, festive storytelling Reels, and all re-edits of catalogue video assets.

**Use Nano Banana for:** trending format Reels (POV, split-screen comparison, poll countdown), all Static image generation, all Carousel slide-by-slide briefs, and Story formats.

Write prompts that are:
- Specific enough to generate the right visual without iteration
- Referencing the existing asset link where applicable (for re-edits)
- Grounded in Bhookle's visual identity (warm tones, real kitchens, human faces)

**For cinematic Reels (Higgsfield):**
```
Higgsfield prompt:
[Shot type] of [subject] in [setting]. [Action/movement]. [Visual style]. [Colour palette].
Text overlay at 0s: "[HOOK TEXT]". [Transition at Xs to next shot]. Background audio: [trending sound name].
Duration: [15s / 30s]. Aspect ratio: 9:16.
```

**For re-edits of catalogue assets (Higgsfield):**
```
Re-edit brief for existing asset ([Chef Name] video):
Source: [Google Drive output link]
Re-edit instructions: Trim to [duration]. Add text overlay at 0s: "[HOOK]" — bold white. [Audio change]. [End card]. Aspect ratio: 9:16.
```

**For trending/lightweight Reels (Nano Banana):**
```
Nano-banana prompt:
Style: [Trending format — POV / Split-screen / Expectation vs Reality].
Scene 1 (0-8s): [Setup]. Scene 2 (8-20s): [Payoff]. Scene 3 (20-28s): [CTA].
End frame: "@bhookleeats | [CTA text]" on brand purple. Trending audio: [sound name]. Aspect ratio: 9:16.
```

**For Static/Carousel posts (Nano Banana):**
```
Image generation prompt:
[Composition]. [Subject: dish name / chef name]. [Lighting: natural / warm studio]. [Props].
[Colour palette: warm ochres, deep greens, cream]. [Text placement area]. Style: food photography, editorial.
```

**For LinkedIn document carousels (Nano Banana):**
Write a slide-by-slide brief: Slide 1 (hook headline), Slides 2-5 (key points), Slide 6 (CTA).

---

### Step 8 — Define Per-Post Eval Targets

For every post, set target KPIs based on Bhookle's historical benchmarks from the eval JSON
(or use platform defaults if no eval available):

| Metric | Instagram Reel | Instagram Static | Instagram Carousel | LinkedIn |
|---|---|---|---|---|
| Reach | 5,000+ | 2,000+ | 3,000+ | 500+ |
| Impressions | 8,000+ | 3,000+ | 5,000+ | 800+ |
| Engagement Rate | 5%+ | 3%+ | 4%+ | 2%+ |
| Saves | 50+ | 20+ | 40+ | N/A |
| Shares | 30+ | 10+ | 20+ | 15+ |
| Profile Visits | 200+ | 80+ | 120+ | 50+ |

Write `EvalTarget` as a compact string per post:
`"Reach: 5K | ER: 5% | Saves: 50 | Shares: 30"`

Also note `EvalHypothesis` — one sentence on why this specific post should hit its target:
`"Chef story format + trending audio = high share velocity in food community"`

---

### Step 9 — Build the Excel File

Use Python with `openpyxl` to generate the workbook. Run:

```bash
python3 "_skills/bhookle-social-planner/scripts/build_calendar.py" \
  /tmp/social_planner_content.json \
  "content-planner/bhookle-content-calendar-$(date +%Y-%m).xlsx"
```

The script reads a JSON payload you write to `/tmp/social_planner_content.json` (see schema in
`references/excel-spec.md`) and outputs a formatted, colour-coded Excel workbook.

---

## Excel Column Schema

### Tab 1: `Instagram_Facebook` (30 rows + header)

| Column | Description |
|---|---|
| `PostID` | IG-001 to IG-030 |
| `PostDate` | Suggested publish date (YYYY-MM-DD), based on best-day insights from eval |
| `PostName` | Short internal name for the post (e.g., "Chef Lakshmi — Biryani Story") |
| `PostFormat` | Reel / Static / Carousel / Story |
| `ContentCategory` | Chef Video / Food Content / Brand |
| `PostHook` | Scroll-stopping first line / text overlay |
| `PostDescription` | Full caption (with CTA) |
| `PostHashtag` | 20-25 hashtags as comma-separated string |
| `ExistingAssetLink` | Output Link from video catalogue (empty if net-new) |
| `AssetAction` | "Reformat" / "Re-edit" / "Net New" |
| `PostGenPrompt` | Full Nano-banana / Higgsfield generation prompt |
| `PostOutput` | *(leave empty — populated by ContentCreator skill)* |
| `PostStatus` | *(leave empty — populated by ContentCreator skill)* |
| `EvalTarget` | Target KPI string (e.g., "Reach: 5K \| ER: 5%") |
| `EvalHypothesis` | One-line rationale for why this post hits target |
| `PostPerformance` | *(leave empty — populated after publishing)* |

### Tab 2: `LinkedIn` (12 rows + header)

| Column | Description |
|---|---|
| `PostID` | LI-001 to LI-012 |
| `PostDate` | Suggested publish date (Tue/Thu/Fri recommended for LinkedIn) |
| `PostName` | Internal name |
| `PostTheme` | HomeFood at Office / Healthy Eating at Work / Employee Wellbeing |
| `PostFormat` | Long-form Text / Document Carousel / Single Image + Text |
| `PostHook` | First line of the LinkedIn post (stat, story opener, or bold claim) |
| `PostDescription` | Full post body (150-300 words) |
| `PostHashtag` | 5-8 professional hashtags |
| `PostGenPrompt` | Image/carousel brief for visual asset |
| `PostOutput` | *(leave empty)* |
| `PostStatus` | *(leave empty)* |
| `EvalTarget` | Target KPIs for LinkedIn |
| `EvalHypothesis` | One-line hypothesis |
| `PostPerformance` | *(leave empty)* |

---

## Excel Formatting Rules

- **Header row:** Bhookle Purple (`#7030A0`) background, white text, bold, 10pt
- **Chef Video rows:** Mustard Yellow (`#FFC000`) left border (3px)
- **Food Content rows:** Soft green (`#E2EFDA`) row tint
- **Brand rows:** Light purple (`#E9D6F5`) row tint
- **Empty columns** (PostOutput, PostStatus, PostPerformance): Light grey (`#F5F5F5`) fill
- **Freeze top row** and **auto-fit all column widths**
- **PostGenPrompt column:** wrap text, row height 60px
- Add a **Summary tab** at the front: content mix donut chart, posting schedule heatmap, theme distribution

---

## Brand Voice Quick Reference

Before writing any hook or description, load the brand voice context:
- Read `_context/` brand files, OR
- Invoke the `bhookle-brand-voice` skill for full guidance

Key rules:
- Bhookle is warm, bold, and pro-chef — never corporate, never clinical
- Instagram voice: street-smart, food-obsessed, culturally rooted in South Indian and pan-Indian cuisine
- LinkedIn voice: founder-empathy, data-backed, human stories over metrics
- Never use: "Delicious", "Yummy", "Mouth-watering" (banned words — too generic)
- Always use: chef's real name, dish's regional origin, sensory specifics ("the crackle of a dosa", "slow-cooked for 8 hours")

---

## Files in This Skill

| File | Purpose | When to Read |
|---|---|---|
| `references/excel-spec.md` | JSON schema for `/tmp/social_planner_content.json` | Before Step 9 |
| `references/prompt-library.md` | Pre-written PostGenPrompt templates for Nano-banana & Higgsfield | When writing PostGenPrompts in Step 7 |
| `scripts/build_calendar.py` | Generates the branded Excel from JSON payload | Run in Step 9 |

---

## Behaviour Rules

1. **Always run Trend Scout fresh.** Never reuse last month's trends — what was viral 4 weeks ago is stale today.
2. **Always read the eval JSON.** The calendar must be grounded in actual performance data, not assumptions.
3. **Reuse before creating.** Check catalogue first for every chef video slot before writing a net-new concept.
4. **One month per run.** Never generate multi-month calendars in a single run unless explicitly asked.
5. **Brand voice is non-negotiable.** Every hook must be checked against the brand voice rules above before finalising.
6. **PostGenPrompts must be production-ready.** A content creator should be able to paste the prompt directly into Nano-banana or Higgsfield with zero interpretation needed.
7. **LinkedIn and Instagram are different audiences.** Never copy-paste content between tabs — always reframe for context and platform.
8. **Flag missing inputs clearly.** If the eval JSON or catalogue is unavailable, proceed with a clear note at the top of the output — don't silently skip those inputs.

---

## Compatibility with downstream skills (`social-create`, `social-post`)

The Excel produced here is the single source of truth for both content generation and
posting. Keep the schema strict:

- **`PostID`** must be unique and follow `IG-NNN` or `LI-NNN` format.
- **`PostDate`** = `YYYY-MM-DD`. **`PostTime (IST)`** = `7:00 PM` or `19:00` — both accepted.
- **`PostStatus`** lifecycle (don't invent new states):
  `Draft` → `Creative Locked` → `Scheduled (IG)` / `GH Actions Generated` → `Posted` / `Failed`.
- **`PostFormat`** must include one of: `Reel`, `Carousel`, `Static`, `Story`, `Long-form Text`,
  `Document Carousel`. The posting skill keys off these strings (case-insensitive substring).
- **`PostOutput`** is filled by `social-create` later — leave blank when planning.
- **Never write `bhookleeats.com` URLs in descriptions** — always "Download the Bhookle app"
  (the posting skill auto-rewrites, but cleanest at source).
- **LinkedIn descriptions automatically get the `@Bhookle | linkedin.com/company/bhookle`
  footer appended by the posting skill** until Community Management API is approved.
  Don't double-append.

See `_skills/social-post/references/lessons.md` and `column-map.md` for the full schema.
