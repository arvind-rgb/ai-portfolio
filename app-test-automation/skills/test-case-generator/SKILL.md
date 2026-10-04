---
name: test-case-generator
description: Reads verified flow maps from test-scan-app and produces a local web dashboard for reviewing and approving Bhookle test cases. Generates catalog.json as the single source of truth, then spins up a localhost HTTP server (stdlib only) that serves an editable dashboard at http://localhost:7777 with 5 tabs (Test Cases, Dashboard, Coverage, Run Results, Bugs Found). User edits Status/Comments inline; ⌘+S saves to disk. Same catalog.json is consumed by run-auto-test. Supports `refine` mode to revise rejected TCs while preserving approved ones. Trigger when the user says "generate test cases", "build test catalog", "open test dashboard", "TestCaseGenerator", or invokes /test-case-generator.
---

# TestCaseGenerator

You are a senior QA architect. Your job is to read the verified flow maps produced by `test-scan-app` and emit a structured, editable Excel test-case catalog for the **Bhookle consumer app** (`bhookleApp-v2`).

You do **not** run anything. You do **not** scan the app code (that's `test-scan-app`'s job). You read flows → generate TCs → build the Excel + Maestro YAMLs → present for approval → refine on demand.

---

## Paths

- **Skill root:** `$HOME/.claude/skills/test-case-generator/`
- **Shared state dir (read flows from):** `$HOME/.claude/skills/_bhookle-test-state/`
  - **Input flows:** `_bhookle-test-state/flows/screen-flow.md`, `user-flow.md`, `.meta.json`
  - **Output catalog (single source of truth):** `_bhookle-test-state/testcases/catalog.json`
  - **Output Maestro YAMLs:** `_bhookle-test-state/maestro/<TC-ID>.yaml`
  - **Lock marker:** `_bhookle-test-state/testcases/.locked` (written when user clicks Lock in dashboard, or when all rows are Approved/Skip-Until-Flag-On)
- **Dashboard:** `dashboard.html` (in skill root) served via `scripts/serve.py` at `http://localhost:7777`

---

## Phase 0 — Preflight

1. Confirm `_bhookle-test-state/flows/screen-flow.md` and `user-flow.md` exist. If not, stop and tell the user to run `test-scan-app` first.
2. Read `_bhookle-test-state/flows/.meta.json` — confirm `version >= 3`. If older, warn that flows may be stale.
3. Check Python: `python3 --version` (3.7+). Stdlib only — no external deps needed.
4. Check if `_bhookle-test-state/testcases/catalog.json` already exists. Determine mode:
   - **Fresh run** (no file) → Phase 1 generation.
   - **Refine run** (file exists + user invoked with `refine` arg) → Phase 6 refinement.
   - **Serve only** (user invoked with `serve` arg) → skip to Phase 7 (start server on existing catalog).
   - **File exists, no flag** → ask via `AskUserQuestion`:
     > "A catalog already exists. Open the dashboard, refine the rejected rows, or regenerate from scratch?"
     > Options: **Open dashboard** / **Refine** / **Regenerate**.

---

## Phase 1 — Read flows

Read **both files in full**:
- `_bhookle-test-state/flows/screen-flow.md` — gives you the screen graph, route names, the dormant subscription path, the "AddressCollection not in checkout" correction.
- `_bhookle-test-state/flows/user-flow.md` — gives you the 12 journeys with steps and verified file:line citations.

Read every `## ` heading. Don't skim. Don't infer journeys not in the file.

---

## Phase 2 — Generate test cases

Coverage is **screen-first**. For **every screen** in `screen-flow.md` (not just every journey), enumerate:
- **The screen's core happy path** — it loads and its primary purpose works.
- **Every in-page action** — each button, toggle, stepper, filter, sort, accordion, input field, modal, and bottom-sheet on that screen gets its own TC. Page-to-page navigation alone is **not** sufficient; in-page interactions are the point. (The user's explicit feedback: "you considered just pageflows but what about actions within the page?")
- **Negative / validation branches** — every "what if it fails / is empty / is invalid" path.
- **Edge cases** — empty states, caps (e.g. dish_max_quantity), serviceability, timeouts, permission denials.
- **Data variations** — Veg Mode (two-valued), Get Today vs Get Later, with/without coupon, guest vs logged-in.

Cross-check against the product screenshots when available — every distinct control visible on a screenshot should map to at least one TC. Concretely, screens like CartScreen, ChefFoodListScreen, GetNowScreen and ProfileScreen are control-dense and should carry **many** TCs each (10–25), not one or two.

The two **column dimensions** the user requires are kept separate:
- **`priority`** — P0 / P1 / P2 / P3 (business criticality).
- **`type`** — `core` (essential: happy paths + primary in-page actions the screen must support) vs `extra` (secondary/edge/negative/cosmetic/supplementary). These are *orthogonal* — a P1 can be core or extra.
- **`category`** (test nature) — `smoke` / `functional` / `negative` / `edge` / `data-variation`.
- **`screen`** — the page the TC exercises. Shown as its own column so the user can see *which page each test is generated for*.

**Hard constraints driven by v3 flow corrections:**
- Do NOT include any TC traversing `Cart → AddressCollectionScreen → Payment` — that path doesn't exist.
- Subscription self-serve PhonePe path TCs must be **tagged DORMANT** with `Status: Skip-Until-Flag-On` by default — they only run if BE flag flips.
- Today's subscription happy path = Subscribe tab → silent redirect to subscriptionRequestScreen → form submit. That's the smoke TC.
- Festival booking TCs are form-submit verifications, not checkout flows.
- Chef-register network-failure silent-bug TC must be P1 negative (the bug is documented).
- Search TCs are supplementary (separate group), not part of New User / Existing User journeys.

Build the TC list **as an in-memory Python list of dicts** (one dict per TC) with this exact schema:

```python
{
  "tc_id": "TC-CART-009",          # SCREEN-prefixed ID (per-screen counter)
  "screen": "CartScreen",           # the page this TC exercises  (NEW — own column)
  "journey": "F. Coupons",          # cross-journey label (kept for coverage)
  "title": "...",                   # one-line imperative
  "priority": "P0",                 # P0 / P1 / P2 / P3  (business criticality)
  "type": "core",                   # core | extra        (essential vs secondary)
  "category": "functional",         # smoke | functional | negative | edge | data-variation
  "platform": "Both",               # iOS / Android / Both
  "preconditions": "...",           # multi-line ok
  "steps": "1. ...\n2. ...\n3. ...",  # numbered, newline-separated
  "expected": "...",                # expected end state
  "data": "phone=<TEST_PHONE>, OTP=<TEST_OTP> (6-digit), chef=Demo Chef (99999), coupon=DEMO100, env=SIT",
  "verified_from": "screenshot IMG_0530, CartScreen.tsx:1371",  # citation (screenshot and/or code:line)
  "tags": "cart, coupon, discount",
  "maestro_yaml": "TC-CART-009.yaml",  # filename only; full path under state/maestro/
  "default_status": "Pending Review",  # 'Pending Review' on fresh gen; 'Skip-Until-Flag-On' for DORMANT
}
```

Target catalog size: **comprehensive — every screen × its in-page actions** (the current catalog is ~190 TCs across 33 screens). Do not cap at a small round number; a control-dense screen left with one TC is a defect. Quality still gates quantity: every TC must map to a real screen control, conditional branch, or data variation verified from screenshots, v3 flows, or code.

---

## Phase 3 — Self-critique (≥90% gate)

Score against `reference/self-critique-rubric.md`:
- Journey-core coverage (every journey has ≥1 `core` TC) — 25 pts
- Screen / in-page coverage (every screen has a `core` happy path **and** its in-page actions covered) — 25 pts
- Negative-path coverage (every critical screen has ≥1 negative/edge TC) — 20 pts
- Data-variation coverage (Veg Mode both values, fulfilment modes, coupon, guest vs logged) — 15 pts
- Dormant-flow tagging (subscription PhonePe path correctly marked DORMANT / Skip-Until-Flag-On) — 15 pts

If total < 90, enumerate gaps, append missing TCs, re-score. Loop until ≥90. Report final score in chat.

---

## Phase 4 — Maestro YAML scaffolding

For each TC, write a Maestro YAML stub at `_bhookle-test-state/maestro/<tc_id>.yaml`:

```yaml
# <tc_id>: <title>
# Screen: <screen>  ·  Journey: <journey>
# Priority: <priority>  ·  Type: <type>  ·  Category: <category>
# Generated by test-case-generator; refine elements/text matchers before running.
appId: ${APP_ID_IOS}
---
- launchApp
- runFlow: subflows/setup-<new-user|existing-user>.yaml
# === Steps from TC ===
# 1. ...
# 2. ...
# 3. ...
- takeScreenshot: result-<tc_id>
```

Standardize two reusable subflows at `_bhookle-test-state/maestro/subflows/`:
- `setup-new-user.yaml` — fresh-install state (clear app data, launch fresh)
- `setup-existing-user.yaml` — pre-logged-in state

Don't try to write detailed Maestro tapOn/inputText steps in this phase — `run-auto-test` (or a future iteration) will fill them in. The stubs exist so file paths can be locked into the Excel.

---

## Phase 5 — Build the catalog JSON

Call `scripts/build-catalog-json.py` with the TC list as JSON via stdin. On refine runs add `--preserve-runs` so prior `run_results` and `bugs` arrays + any user-edited Status/Comments are merged in.

The script writes `_bhookle-test-state/testcases/catalog.json` with this shape:

```json
{
  "schema_version": 1,
  "written_at": "ISO timestamp",
  "meta": { generated_at, flow_version, app_commit, critique_score, journeys_covered },
  "test_cases": [ { tc_id, screen, journey, title, priority, type, category, platform,
                    preconditions, steps, expected, data, verified_from,
                    tags, maestro_yaml,
                    status, comments,                              // user-edited
                    last_run_result, last_run_ts, failure_reason,  // filled by run-auto-test
                    screenshot_path } ],
  "run_results": [],   // appended by run-auto-test (empty on fresh gen)
  "bugs": []           // appended by run-auto-test
}
```

This single file backs all five dashboard tabs. No Excel.

---

## Phase 6 — Refinement loop (when invoked with `refine` arg)

1. Call `scripts/read-decisions.py` — it reads the Excel and emits JSON of all rows with `Status` ∈ {Rejected, Needs Refinement} along with their Comments.
2. For each rejected/needs-refinement TC:
   - Read user comment.
   - Update the TC dict — adjust steps, expected, priority, tags as the comment directs.
   - If user said "remove" or "not applicable", mark as `default_status: Removed` (this is a sentinel; the script will hide the row).
3. Approved rows are preserved exactly — do NOT regenerate them.
4. `Pending Review` rows that user hasn't touched: leave as-is.
5. Re-run Phase 5 to overwrite the Excel. The script preserves Run Results + Bugs Found sheets (append-only) — don't blow them away.
6. Re-score in Phase 3 if any TC text changed materially.

---

## Phase 7 — Start the dashboard server

1. Kill any prior server on port 7777 (check `lsof -ti:7777` and `kill` if present — don't error if absent).
2. Launch `python3 scripts/serve.py --no-browser &` in the background (run_in_background=true). The user will open the URL themselves — do NOT auto-open the browser.
3. Print to chat:
   - **Dashboard URL:** `http://localhost:7777` (clickable)
   - Catalog path: `_bhookle-test-state/testcases/catalog.json`
   - Counts: total TCs, P0/P1/P2/P3 breakdown, journeys covered, self-critique score
   - **One-line instructions:** "Open the dashboard → review each TC → set Status (Approved/Rejected/Needs Refinement) and Comments → ⌘+S to save. Re-invoke `/test-case-generator refine` to revise rejected rows. Click 'Lock catalog' when all rows are Approved or Skip-Until-Flag-On."
4. Do NOT write the `.locked` marker automatically — the user clicks the Lock button in the dashboard when ready. (The server handles that via `POST /api/lock`.)
5. Tell the user how to stop the server: `lsof -ti:7777 | xargs kill`.

---

## Rules

- **Never edit `_bhookle-test-state/flows/` files.** Flows are owned by `test-scan-app`.
- **Never touch sheets 4 (Run Results) or 5 (Bugs Found)** on regenerate — those are append-only and owned by `run-auto-test`.
- **Never write Maestro YAMLs that target screens/routes not in `screen-flow.md`** — if a TC implies a screen not in the map, drop the TC and log the gap.
- **Preserve approved TCs verbatim during refinement** — only modify rows the user flagged.
- **Echo the v3 flow caveats** in every TC's `verified_from` column so the user can audit.
- **Subscription PhonePe TCs are tagged `DORMANT` and default `Status: Skip-Until-Flag-On`.** Do not flag them as failures.
- **No `testID`-based selectors in Maestro YAML.** The app has no testIDs yet (per v3 §13). Use visible text or coordinate-based matchers, and note this in the YAML header comment.
