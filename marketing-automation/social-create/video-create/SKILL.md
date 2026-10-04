---
name: video-create
description: >
  Storyboard, generate, preview, and lock social media REELS (and their storyboard
  stills) for Bhookle posts marked as video/Reel in the bhookle-social-planner Excel.
  Unified successor to the old higgs-create + video-create skills.
  DEFAULT ENGINE: Google Veo (video) + Imagen 4 Ultra (stills/storyboard). Higgsfield is
  OPT-IN only — never used unless the user explicitly approves it for that reel, and only
  after a credit check.
  TRIGGER on: "run video-create", "generate reels", "create the next batch of videos",
  "produce video reels for the calendar", "storyboard a reel", "turn this cover into a reel".
  Flow: list pending → storyboard with nano-banana → user approves → user picks engine
  (Google/Ultra default, or Higgsfield) → generate (time-capped) → pre-present eval →
  user approves → lock + update planner → cleanup temp.
  Companion to nano-create (pure static image posts).
user-invocable: true
---

# video-create — Bhookle Reel & Storyboard Generator (unified)

This skill replaces **higgs-create** and the old **video-create**. It owns the full
**Reel pipeline** — storyboarding stills first, then animating to video — plus the
storyboard images those reels are built from.

> **Why "video-create" and not "higgs-create":** we are no longer Higgsfield-only.
> The default engine is **Google Veo + Imagen 4 Ultra**. Higgsfield is one optional
> backend the user can choose per reel.

`nano-create` still owns **pure static image posts** (single images, carousels, stories).
This skill owns anything that ends as an **.mp4 Reel**.

---

## Skill location (keep both in sync)

```
bhookle-marketing/_skills/social-create/video-create/   ← source of truth
~/.claude/skills/social-create/video-create/             ← runtime
```

Per CLAUDE.md skill-sync rule: every edit is saved to BOTH paths.

---

## Engine policy (READ FIRST — this is the core change)

| Stage | Default engine | Opt-in alternative |
|---|---|---|
| Storyboard stills | **nano-banana** (`gemini-3.1-flash-image-preview`) — fast, cheap | — |
| Hero / final stills | **Imagen 4 Ultra** (`imagen-4.0-ultra-generate-001`) | — |
| Video (animation) | **Google Veo** (`veo-3.1-fast-generate-preview`) | **Higgsfield** (Seedance/Kling) — opt-in only |

**Rules:**
1. **Storyboard with nano-banana FIRST** for every reel — it's cheap and fast, and lets the
   user judge composition before any expensive render.
2. **The user picks the video engine.** After storyboard approval, ASK:
   *"Animate this with (A) Google Veo + Imagen Ultra [default], or (B) Higgsfield?"*
   Do **not** auto-select. If the user doesn't choose, **default to A (Google/Ultra)**.
3. **Higgsfield is deployed only on explicit approval**, and only after the **credit guard**
   (below) passes. Never load the Higgsfield CLI/MCP or spend credits without that.
4. **API key:** `GEMINI_API_KEY=<your-gemini-api-key>`

---

## Hard safety rules (req #7 — never crash the machine again)

- **Every generation/poll script takes `--max-seconds` and enforces a hard deadline.**
  No unbounded `while not done: sleep` loops. Veo polling caps at 480s; image gen at 180s.
- **Batches of >3 renders run in the background** (`run_in_background`), never inline.
- **No leading `sleep` padding.** Poll with a bounded deadline; stop on first hard error.
- **Always quote ffmpeg stream maps** (`'0:a'`, not `0:a?` — zsh expands `?` as a glob).
- **`cleanup.py` runs on every lock and at end of run** to clear `/tmp` working dirs.

---

## Brand & creative rules (baked-in learnings — approved)

These are non-negotiable; they come from real production mistakes.

**Text & layout (L1–L3):**
- **Never bake captions into the AI image.** Generate a CLEAN base photo (prompt ends with
  "NO text, NO overlays, NO watermarks"), then composite ALL typography with **PIL**.
- **Logo goes in the bottom CTA bar, right-aligned** — never top-left over a headline.
- **Type hierarchy:** hero hook (large) → H2 on a **solid orange/dark pill** → CTA in the
  **brand-purple bar**. Always lay a **dark gradient scrim** on the lower third before white text.

**Copy (L5):**
- **NO URLs, ever.** `bhookleeats.com` is banned. Scrub it from PostGenPrompt at generation
  time. All CTAs say **"Download the Bhookle app"** / "Order on the Bhookle app".

**Imagery (L4, L6, L9):**
- **Imagen 4 Ultra** for hero stills; **nano-banana** only for throwaway storyboards.
- **Chef stills:** never auto-pick a frame. Build a **contact sheet**, let the user choose
  the frame number, then composite.
- **Carousel/multi-slide:** each slide gets its OWN relevant Ultra photo + scrim + text —
  never a flat color background.

**Video (L7, L8, yesterday's set):**
- **Image-to-video from an approved still** is the fast path — animate the locked cover/base.
- **Veo outputs 720×1280; end card is 1080×1920.** Always scale clips to **1080×1920,
  normalize fps=24 + AAC 44.1kHz** before concat, or the join breaks.
- Chef catalogue videos are used **AS-IS, no re-edit** (the master is the deliverable).
- Reuse the **pink-maroon Bhookle bag** for dabba shots; **mute human ambient noise**.
- **Keep Veo clips at 8s** (NSFW filter trips ~15s); chain 8s clips for 20s+ reels.
- **Modern apartment kitchens — no village/clay-pot/chulha styling** unless the post is
  explicitly heritage (Rath Yatra, Onam, Diwali…).

**Reliability (L10–L12):**
- **List models before a batch** — model IDs go stale (verify the ID returns 200).
- **Pre-present eval gate** (below) before showing the user anything.

---

## Workflow — step by step

### Step 0 — Pre-flight
```bash
CALENDAR=$(ls -t content-planner/bhookle-content-calendar-*.xlsx 2>/dev/null | head -1)
# Verify the default models are live (IDs go stale):
python3 _skills/social-create/video-create/scripts/list_pending.py "$CALENDAR" --check-models
```

### Step 1 — List pending reels (static vs reel aware)
```bash
python3 _skills/social-create/video-create/scripts/list_pending.py "$CALENDAR" --json > /tmp/vc_batch.json
```
Returns only rows where `AssetType == "Reel (Video)"` AND status pending. Show the list,
confirm the batch.

### Step 2 — Storyboard FIRST (nano-banana)
For each reel, generate 1–3 storyboard key frames (clean, no text) with nano-banana:
```bash
python3 _skills/social-create/video-create/scripts/storyboard.py \
  --post IG-010 --prompt "<scene>" --frames 2 --out /tmp/vc/IG-010
```
Display the frames inline. Ask: **"Approve this storyboard, edit the scene, or regenerate?"**

### Step 2b — Beast-mode prompt eval (before generating video)
Run the 9-dimension cinematic eval on the motion prompt; surface gaps + the enhanced
prompt; get approval before spending on any render:
```bash
python3 _skills/social-create/video-create/scripts/enhance_prompt.py \
  --base "<PostGenPrompt>" --chef-name "..." --dish "..." --city "..." --duration 8
```
Emits `critique` (gaps by severity) + `enhanced_prompt`. Don't generate while a `high`
gap remains. Show the user, apply edits, then proceed.

### Step 3 — Engine choice (user decides)
After storyboard approval, ASK:
> "Animate IG-010 with **(A) Google Veo + Imagen Ultra** [default], or **(B) Higgsfield**?"

- **(A) Google/Ultra** → Step 4A.
- **(B) Higgsfield** → run the **credit guard** (Step 4B-pre) FIRST.
- No answer → default to **(A)**.

### Step 4A — Generate with Google Veo + Imagen Ultra (default)
1. Promote the approved storyboard frame to a hero still with Imagen Ultra if needed.
2. Image-to-video, **time-capped**:
```bash
python3 _skills/social-create/video-create/scripts/generate_video.py \
  --engine veo --image /tmp/vc/IG-010/frame1.png \
  --prompt "<motion prompt>" --duration 8 --aspect 9:16 \
  --out /tmp/vc/IG-010/raw.mp4 --max-seconds 480
```
3. Build the reel (scale→overlay text→end card), per learnings:
```bash
python3 _skills/social-create/video-create/scripts/build_reel.py \
  --raw /tmp/vc/IG-010/raw.mp4 --post IG-010 --design /tmp/vc/IG-010/design.json \
  --out /tmp/vc/IG-010/final.mp4
```

### Step 4B-pre — Higgsfield CREDIT GUARD (req #6 — mandatory before any Higgs spend)
```bash
python3 _skills/social-create/video-create/scripts/higgs_credits.py --duration 8 --model seedance_2_0
```
Prints: **credits available**, **estimated cost for this reel**, **remaining after**.
- If **insufficient** → STOP, tell the user, fall back to Google/Ultra or wait.
- If sufficient → show the numbers and get a final **"go"** before spending.
Only after this do you load the Higgsfield CLI/MCP.

### Step 4B — Generate with Higgsfield (opt-in)
```bash
python3 _skills/social-create/video-create/scripts/generate_video.py \
  --engine higgsfield --model seedance_2_0 --duration 8 --aspect 9:16 \
  [--image /path/ref.jpg] --prompt "<enhanced prompt>" \
  --out /tmp/vc/IG-010/raw.mp4 --max-seconds 480
```
Then `build_reel.py` as in 4A.

### Step 5 — Pre-present eval (gate — req #3)
```bash
python3 _skills/social-create/video-create/scripts/eval_check.py /tmp/vc/IG-010/final.mp4 --post IG-010
```
Checks: file exists · aspect 9:16 · expected duration · **zero URLs in overlays** · logo
present & not overlapping · CTA == "Download the Bhookle app" · end card appended.
**Only present to the user if the eval passes.** For the preview itself, extract a
thumbnail strip (Read can't render .mp4) and **share the file path as a link** — do NOT
read the .mp4 or large frames into chat context (token hygiene):
```bash
python3 _skills/social-create/video-create/scripts/extract_thumbnails.py /tmp/vc/IG-010/final.mp4
```

### Step 6 — Approve / regenerate, then lock
On **lock**:
```bash
python3 _skills/social-create/video-create/scripts/lock_creative.py "$CALENDAR" IG-010 \
  --src /tmp/vc/IG-010/final.mp4 --output-dir "assets/social/$(date +%Y-%m)"
python3 _skills/social-create/video-create/scripts/cleanup.py --post IG-010
```
`lock_creative.py` copies the .mp4, sets `PostStatus=Creative Locked`, writes `PostOutput`.
`cleanup.py` removes `/tmp/vc/IG-010/`.

### Step 7 — Summary + final cleanup
```bash
python3 _skills/social-create/video-create/scripts/cleanup.py --all
```
Report: locked reels (engine used + duration), skipped, planner count, and — if Higgsfield
was used — credits before/after.

---

## Scripts
| Script | Purpose | Safety |
|---|---|---|
| `list_pending.py` | Read xlsx; return pending **Reel** rows; `--check-models` verifies live IDs | — |
| `storyboard.py` | nano-banana key frames (clean, no text) | `--max-seconds 180` |
| `higgs_credits.py` | Credit guard: available / est cost / remaining; blocks if short | read-only |
| `generate_video.py` | `--engine veo\|higgsfield`; image-to-video | `--max-seconds` hard cap |
| `build_reel.py` | scale→PIL text overlay→end card; design.json drives layout | quoted ffmpeg maps |
| `eval_check.py` | pre-present gate (URLs, dims, duration, logo, CTA, end card) | — |
| `lock_creative.py` | copy final, update PostStatus/PostOutput | single source of truth |
| `cleanup.py` | `--post X` or `--all`; clears /tmp working dirs | — |

## Folder layout
```
/tmp/vc/<POSTID>/        ← storyboard frames, raw clip, final.mp4 (cleaned on lock)
assets/social/YYYY-MM/   ← production-locked finals
```

## Token & context hygiene (req #2 — don't burn the budget)

A long session accumulates a huge context (big CLAUDE.md + memory + many skills + 200+
deferred tools + every tool result and image). That's what hit the 100% limit in minutes.
Follow these to keep runs cheap:

1. **Share file paths as links; never `Read` images/.mp4 into context to "preview".** A
   single Read of an image/screenshot costs ~1–2k tokens; a markdown link costs ~0. (This
   is the single biggest saver — it's why the link-based review flow today was cheap and
   the early screenshot flow was expensive.)
2. **Run any batch >3 renders in the background**, and read only the small text log — not
   per-item inline output.
3. **Never read large binaries** (full-size logo 2350×3522, raw videos, base PNGs) into
   chat. Use the small safe logo only.
4. **One task per chat.** Calendar generation, skill editing, and eval are separate
   sessions — don't chain them in one ever-growing context. Start a fresh chat per task.
5. **Don't re-read files you already read.** Trust the edit tools' confirmations.
6. **Keep SKILL.md lean.** Deprecated/dead skills are deleted, not archived inline.
7. **Verify with ffprobe/stat, not by opening media** in a viewer or context.

## Behaviour rules
1. **Storyboard with nano-banana before any video render.** Always show frames, get approval.
2. **User picks the video engine.** Default Google/Ultra. Higgsfield only on explicit OK.
3. **Higgsfield credit guard is mandatory** before any Higgsfield spend; block if insufficient.
4. **All renders are time-capped; batches go to background.** Never risk a machine hang.
5. **Pre-present eval must pass** before showing the user.
6. **Lock via lock_creative.py; cleanup via cleanup.py.** Leave no /tmp scratch behind.
7. **No URLs; logo in bottom bar; text composited in PIL; Imagen Ultra for hero stills.**
8. **Stop on first hard API error** — report quota/safety/network instead of silent retry.

---

## Compatibility with `social-post` skill

Outputs feed directly into scheduled IG Reel/Video publishing. Stick to:

- **File format: MP4** (H.264 + AAC). Meta's IG Reels API rejects MOV, WebM, etc.
- **File naming: `<POSTID>.mp4`** in `assets/social/YYYY-MM/`.
- **Reel cover image**: optional but recommended as `<POSTID>.png` (used for thumbnail).
- **`PostOutput` column in the planner**: write the full local path to the `.mp4`.
- **Aspect ratio 9:16** for Reels (1080×1920), under 90 seconds.
- The posting skill uploads videos to **catbox.moe** (free public host, 200MB cap)
  then passes the URL to Meta's `video_url` parameter — do not exceed catbox's limit.

See `_skills/social-post/references/lessons.md` for the full API constraints.
