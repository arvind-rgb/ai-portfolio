---
name: nano-create
description: >
  Generate, preview, and lock social media images for Bhookle posts tagged "Nano Banana"
  in the bhookle-social-planner Excel output. Uses Google's Nano Banana Pro (Gemini 3 Pro Image).
  TRIGGER on: "run nano-create", "generate nano banana images", "create images for the next batch",
  "generate next 7 social images", "produce nano banana creatives", or any request to generate
  images for posts in the social planner calendar.
  This skill ALWAYS produces 3 variants per post, helps the user choose one, then locks the chosen
  image and updates PostStatus to "Creative Locked" in the calendar Excel.
  Part of the social-create family (alongside higgs-create for video).
user-invocable: true
---

# nano-create — Bhookle Social Image Generator

Part of the `social-create/` skill family. This skill handles **image generation** for posts
tagged Nano Banana in the bhookle-social-planner Excel output. A sibling skill `higgs-create`
will handle video Reels.

---

## Skill location

```
bhookle-marketing/_skills/social-create/nano-create/         ← team source of truth
~/.claude/skills/social-create/nano-create/                  ← runtime
```

Both must stay in sync.

---

## Files in this skill

| File | Purpose |
|---|---|
| `scripts/list_pending.py`    | Reads the social-planner xlsx, returns the first N posts where Generator="Nano Banana" AND PostStatus is empty/"Yet to post" |
| `scripts/batch_generate.py`  | Orchestrates 3-variant generation per post with **8-retry safety-filter policy** |
| `scripts/generate_image.py`  | Low-level Gemini 3 Pro Image wrapper — generates one image per call |
| `scripts/lock_creative.py`   | After approval: copies chosen variant to output folder, updates PostStatus to "Creative Locked" in xlsx |
| `install.sh`                 | Installs `google-genai` and `pillow` |
| `requirements.txt`           | Python deps |

### Safety-filter retry policy (important)

Gemini 3 Pro Image has a probabilistic Responsible-AI filter that occasionally blocks prompts
mentioning real Indian chef names (`finish_reason=IMAGE_OTHER`). The block is **sampling-based**
— the exact same prompt retried often succeeds because the model samples different latent
representations on each call.

**Policy:** `batch_generate.py` retries every variant up to **8 times** on safety blocks before
giving up. Empirically: most blocks clear within 1-2 retries, persistent blocks (3+ in a row)
indicate the prompt phrasing is the issue and may need manual rewording.

**Never strip real chef names from prompts** to dodge the filter — chef identity is core to
Bhookle's brand voice. Always retry first.

---

## Prerequisites

1. `GEMINI_API_KEY` env var set. If missing, run: `export GEMINI_API_KEY=<key>`
2. Python deps installed: `bash _skills/social-create/nano-create/install.sh`
3. A bhookle-social-planner Excel exists at `content-planner/bhookle-content-calendar-YYYY-MM.xlsx`

---

## Folder structure (created on first run)

```
/tmp/nanobanana_variants/
  IG-002/
    v1.png
    v2.png
    v3.png
  IG-017/
    v1.png
    v2.png
    v3.png
  ...

assets/social/YYYY-MM/
  IG-002.png      ← locked final
  IG-017.png      ← locked final
  ...
```

Temp folder holds 3 variants per post until the user picks one. After locking, only the
chosen variant survives — renamed to `<POSTID>.png` and moved to the production folder.

---

## Workflow — step by step

### Step 0 — Pre-flight

```bash
test -n "$GEMINI_API_KEY" || { echo "Set GEMINI_API_KEY first"; exit 1; }

CALENDAR=$(ls -t content-planner/bhookle-content-calendar-*.xlsx 2>/dev/null | head -1)
echo "Calendar: $CALENDAR"
```

If no calendar exists, tell the user to run `bhookle-social-planner` first.

---

### Step 1a — Brief preview & approval (BEFORE any image generation)

Before spending any API credits on a post, walk the user through what the post is about and let them edit the brief. This is the **single biggest cost saver** — fixing the prompt costs nothing; regenerating 3 variants costs 3 API calls.

For each post in the batch, surface these fields from the calendar Excel:

| Field | Why it matters |
|---|---|
| `PostName`         | Internal name — sanity check |
| `PostFormat`       | Reel / Carousel / Static / Story — sets aspect ratio & slide count |
| `PostHook`         | The overlay text the image needs to leave room for |
| `PostDescription`  | The caption/copy that ships alongside — confirms the story angle |
| `PostGenPrompt`    | The prompt that will be sent to Gemini |
| `EvalHypothesis`   | Why this post is supposed to perform — informs design priorities |

Display these in a compact summary and ask:

> "Here's the brief for `IG-XXX`. Any edits to the description, hook, or prompt before I generate?"

Wait for `lock the brief` (or equivalent) before generating. Apply any requested copy edits **directly to the xlsx via openpyxl** — same fields, same row — before generating. This way the calendar stays in sync with the creative from the start.

### Step 1b — Real-chef photo check (mandatory)

If the post mentions a real chef by name (e.g., "Chef C. Sample", "Chef B. Sample", "Chef A. Sample"), check `assets/chef-refs/<chef-slug>.*` for an existing reference photo. If none exists:

> "This post features Chef <Name>. Please upload her/his real photo before I generate — I'll save it to `assets/chef-refs/` and use it as the face reference. Generating without a real photo produces a fictional face which won't match the chef's actual appearance."

**Never silently generate a fictional face for a named real chef.** Wait for the upload. Fictional/generic chef portraits are only acceptable when the PostDescription uses an anonymous chef ("a Bengaluru home chef", "a Kerala amma").

### Step 1c — List the next 7 IG + 7 LinkedIn pending posts

```bash
python3 _skills/social-create/nano-create/scripts/list_pending.py "$CALENDAR" --json > /tmp/nbn_batch.json
```

Returns JSON with `instagram` and `linkedin` arrays — each entry contains `post_id`,
`post_format`, `post_gen_prompt`, etc.

Show the user the list of POSTIDs that will be generated and ask for confirmation before
spending API credits on up to 42 image generations (14 posts × 3 variants).

---

### Step 2 — Generate 3 variants per post (via batch orchestrator)

The orchestrator handles brand-style append, aspect-ratio mapping, slide-1 extraction for
multi-slide prompts, and **safety-filter retry** automatically:

```bash
python3 _skills/social-create/nano-create/scripts/batch_generate.py
```

Flags:
- `--only-missing` — skip variants already on disk (useful after partial failures)
- `--retries N`   — override the default 8-retry safety budget
- `--batch-file PATH` — point at a different list_pending.py JSON output

For one-off single-post generation, you can still call `generate_image.py` directly:

```bash
python3 _skills/social-create/nano-create/scripts/generate_image.py \
  "<prompt>" \
  -o "/tmp/nanobanana_variants/IG-002/v1.png" \
  --aspect-ratio 1:1
```

**Aspect ratio by PostFormat:**

| PostFormat | Aspect ratio |
|---|---|
| Static | `1:1` |
| Carousel | `1:1` |
| Story | `9:16` |
| Reel (Nano Banana) | `9:16` |
| Long-form Text (LinkedIn) | `4:5` |
| Document Carousel (LinkedIn) | `4:3` |
| Single Image + Text (LinkedIn) | `4:5` |

**Carousel posts — always produce ALL slides, not just slide-1.** A carousel is the slide-1 hook AND every supporting slide. Parse the `PostGenPrompt` for "Slide 1:", "Slide 2:", "Slide 3:" etc. and generate one image per slide. File naming:

| Format | File pattern |
|---|---|
| Single-image post (Static, Story, Reel cover) | `<POSTID>.png` |
| Multi-slide carousel | `<POSTID>-slide1.png`, `<POSTID>-slide2.png`, ... |

For each slide, still generate **3 variants** so the user can pick per slide. Variant temp folder:
`/tmp/nanobanana_variants/<POSTID>/slide1/v1.png` etc.

After picking, `lock_creative.py` accepts an optional `--slide N` flag to lock per-slide. `PostOutput` in the xlsx becomes a comma-separated list of all locked slide paths.

**Minimum slides for carousels:** if the PostGenPrompt describes only a single visual (e.g., "Open it. Here's what's inside." with no slide-2 brief), generate **at least 2** — slide-1 (the hook/closed state) and slide-2 (the payoff/reveal). The skill should never deliver a single-image carousel post.

---

### Step 3 — Show variants and help the user choose

After variants are generated for a post, **use the Read tool to display each variant inline**,
then give the user a short comparison:

```
IG-002 — ASMR: Bhookle Dabba Gets Packed

  Variant 1 → /tmp/nanobanana_variants/IG-002/v1.png
    [Read tool displays image]
    Notes: Tight overhead crop, more steam, less negative space.

  Variant 2 → /tmp/nanobanana_variants/IG-002/v2.png
    [Read tool displays image]
    Notes: Wider angle, hand entering frame, cleaner bottom-third for text overlay.

  Variant 3 → /tmp/nanobanana_variants/IG-002/v3.png
    [Read tool displays image]
    Notes: Side-light, more dramatic shadow, no hand.

  Recommendation: Variant 2 — best balance of food focus and copy space.
```

Ask: *"For IG-002, which variant do you want to lock? (1 / 2 / 3 / skip / regenerate)"*

Either process the user's choice one post at a time OR collect all decisions in a single
batch reply like `IG-002:2, IG-017:1, IG-023:3, LI-001:skip, ...`.

---

### Step 4 — Lock approved variants

For every approved post:

```bash
python3 _skills/social-create/nano-create/scripts/lock_creative.py \
  "$CALENDAR" \
  IG-002 \
  2 \
  --temp-dir   /tmp/nanobanana_variants \
  --output-dir "assets/social/$(basename $CALENDAR .xlsx | sed 's/bhookle-content-calendar-//')"
```

This will:
1. Copy `v2.png` → `assets/social/2026-06/IG-002.png`
2. Update PostStatus in the xlsx to `Creative Locked`
3. Write the final path into PostOutput
4. Delete the temp folder for that post

For **skip** — leave temp variants in place for later review.
For **regenerate** — re-run Step 2 for just that post.

---

### Step 5 — Summary report

```
✅ Locked creatives:
   IG-002 → assets/social/2026-06/IG-002.png
   IG-017 → assets/social/2026-06/IG-017.png
   LI-001 → assets/social/2026-06/LI-001.png

⏭️  Skipped (variants kept in /tmp/nanobanana_variants):
   IG-023, LI-005

🔁 Regenerated and locked:
   IG-011 → assets/social/2026-06/IG-011.png

📊 Calendar updated: 8/14 posts now Creative Locked.
```

---

## Kitchen variety rules (avoid the "same kitchen" problem)

Gemini's default Indian-home-kitchen render converges on a stereotyped village-amma visual: clay/mud handis stacked on shelves, labeled glass spice jars, steel dabba rack, ladles hanging from a rod. If you generate 14 chef cards back-to-back without varying the brief, all 14 kitchens will look identical — and they'll all look like a 1970s village home, not the modern urban Indian kitchen where Bhookle's actual chefs cook.

**BAN — never include in prompts unless the post specifically calls for heritage/festival framing:**

- ❌ Clay handis / mud pots / terracotta cooking vessels
- ❌ Stacks of unlabeled clay storage jars
- ❌ Stone chulhas (traditional wood-fired stoves)
- ❌ Pestle-and-mortar prominently in foreground

These read as "village past" not "home chef present". Most Bhookle chefs cook in modern apartment kitchens.

**MANDATE — for each chef post, specify ONE distinguishing kitchen detail per category. Rotate across:**

- **Tile / wall finish** — green-and-white checkered, exposed brick painted white, pastel pink wall, white painted wall with subway tile, blue-and-white tile, plain ochre wall, glossy white modular cabinetry
- **Cooking surface** — modern 2-burner gas stove with stainless backsplash, 4-burner gas with chimney hood, induction cooktop on a granite counter, built-in oven beside the cooktop
- **Storage style** — open wooden shelving with neatly arranged glass jars, modular cabinet with frosted glass doors, wall-mounted stainless steel rack, plastered niche with spice tins, hanging copper-bottom utensils, white melamine pantry
- **Window / light source** — large modern window with bars, sliding window with mosquito mesh, frosted glass kitchen window, low side-window with curtain pulled aside, skylight
- **Regional cues** — banana leaf hanging on the wall (Kerala/Tamil), framed Tanjore painting (Tamil), Madhubani painting (Bihar/Mithila), brass kuthuvilakku lamp on a small niche (South Indian), Warli art motif on a wall (Maharashtra)
- **Chef-personal items** — framed family photo on a shelf, small puja niche with a brass diya, child's drawing taped to the fridge, an apron hanging on a hook, a wall clock, a calendar with the current month
- **Modern appliance** — visible mixer-grinder on counter, electric kettle, OTG, refrigerator door visible, microwave above the cooktop

Pick **2 distinguishing details** per chef and put them in the prompt. Goal: two chef-spotlight posts side-by-side feel like two different real urban Indian apartment kitchens — not the same set redressed.

## Bhookle logo placement (mandatory on every IG and LinkedIn post)

Every locked creative — IG and LinkedIn, every format including Stories — must carry the Bhookle wordmark or icon. No exceptions.

**Placement rules:**

| Format | Logo placement | Treatment |
|---|---|---|
| IG Static / Carousel slide | Bottom-right corner | Small mustard-yellow badge (~10% of frame width) OR "Bhookle" wordmark in brand purple on a white strip |
| IG Story / Reel cover | Top-centre OR bottom-centre | Mustard-yellow badge with the rounded "Bhookle" wordmark |
| LinkedIn Document Carousel | Bottom-centre on brand-purple strip | "Bhookle" wordmark in white (mustard accent ok) |
| LinkedIn Single Image | Bottom-right | "Bhookle" wordmark in mustard against a brand-purple bar |

Always include in the prompt one of:
- *"Small Bhookle mustard-yellow badge top-right corner."*
- *"Brand purple strip across the bottom with 'Bhookle' wordmark in mustard yellow / white."*

If the model omits the logo (it happens), it's a regen condition — not a lock. **No-logo posts cannot be locked.**

## Brand prompt rules (append to every prompt)

The build script does NOT auto-append these — you must add them to every prompt before
calling `generate_image.py`:

```
Bhookle brand style: warm ochre and terracotta colour palette, real home kitchen textures
(steel vessels, clay pots, handwritten masala labels), natural window light from the left,
editorial food photography feel — not commercial stock photo. Gritty, authentic. No artificial
brightness, no plastic food styling, no sterile white studio backgrounds.
```

For chef portraits also append:
```
Chef portrait style: natural expression, kitchen visible in background, warm side light,
not posed or staged. Real person, real hands, real kitchen.
```

---

## Behaviour rules

1. **Always preview the brief BEFORE generating.** For each post in the batch, surface PostName / PostFormat / PostHook / PostDescription / PostGenPrompt from the xlsx, and ask the user for any edits. Apply approved edits to the xlsx via openpyxl. Only generate once the brief is locked.
2. **Always ask for a real chef photo if the post names a real chef.** Check `assets/chef-refs/` for an existing reference. If none, request upload before generating. Never silently generate a fictional face for a named chef.
3. **Carousel posts produce all slides, not just slide-1.** Parse "Slide 1:", "Slide 2:", etc. from PostGenPrompt and generate one image per slide (3 variants each per slide). Minimum 2 slides for any carousel post — never deliver a single-image carousel. Filename pattern: `<POSTID>-slide1.png`, `<POSTID>-slide2.png`, …
4. **Every IG and LinkedIn creative must carry the Bhookle logo.** Mustard badge or wordmark on brand-purple strip — no exceptions. Missing logo = regen condition, not a lock.
5. **Always generate 3 variants per slide.** User picks the winner. Never deliver one shot.
6. **Always use the Read tool to display variants inline** so the user can see them in chat.
7. **ALWAYS preview after regeneration.** Whenever you regenerate a variant — for any reason — immediately Read-display the new file and wait for the user's lock/reject decision. Do not move on until the regen has been previewed and decided on.
8. **Always confirm batch size before spending credits.** 14 posts × multi-slide × 3 variants can easily exceed 100 API calls — confirm first.
9. **Lock via `lock_creative.py` only.** That script is the single source of truth for PostStatus. Content edits to PostName/PostHook/PostDescription/PostGenPrompt/EvalHypothesis can be written directly via openpyxl when the user changes the brief.
10. **Save chef reference photos to `assets/chef-refs/<slug>.<ext>`** and pass them as `--input` to `generate_image.py`. Reference the file path in the xlsx PostGenPrompt so future regenerations stay consistent.
11. **Variants live in `/tmp/nanobanana_variants/` only.** Final locked images go to `assets/social/YYYY-MM/`.
12. **Safety filter is probabilistic — retry up to 8 times.** Never strip real chef names to dodge it. `batch_generate.py` handles this automatically.
13. **Modern apartment kitchens, not village ammas.** No clay/mud pots, no stone chulhas, no stacks of unlabeled clay jars — unless the post specifically calls for heritage/festival framing.
14. **Default batch: first 7 IG + first 7 LinkedIn.** Override with `--ig N --li N` if requested.

---

## Errors

| Error | Fix |
|---|---|
| `GEMINI_API_KEY not set` | `export GEMINI_API_KEY=<key>` and retry |
| `No module named google.genai` | `bash _skills/social-create/nano-create/install.sh` |
| `RAI filtered` / safety block | Remove named real people or sensitive elements from prompt, retry once |
| `429 / quota exceeded` | Wait 60s, retry. If persistent: check quota at https://aistudio.google.com |
| `post_id not found in xlsx` | Verify POSTID matches exactly (case-sensitive). Re-run `list_pending.py` |

---

## Compatibility with `social-post` skill

Outputs from this skill are picked up by `social-post` for scheduled publishing. Stick to:

- **Carousel slide naming**: `<POSTID>-slide1.png`, `<POSTID>-slide2.png`, … `<POSTID>-slideN.png`
  in the same folder as the cover. The posting skill auto-discovers these by glob.
- **Static / Reel cover**: `<POSTID>.png` (single file).
- **PNG is fine** — Meta rejects PNG for IG posts, but `social-post` auto-converts
  PNG → JPG with Pillow before upload. No action needed here.
- **`PostOutput` column in the planner**: write the single path for static posts, or
  comma-separated paths for carousels. Empty is also OK for carousels — the posting
  skill falls back to the glob pattern above.
- All assets should live under `assets/social/YYYY-MM/`.

See `_skills/social-post/references/lessons.md` for the full list of API/format
constraints if you're considering changing the output format or naming.
