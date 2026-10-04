---
name: test-scan-app
description: Scans the Bhookle consumer app codebase (bhookleApp-v2, Expo + RN) and produces a screen-by-screen map plus user-journey catalog. Outputs screen-flow.md and user-flow.md to the shared test-state dir so downstream skills (test-case-generator, run-auto-test) can consume them. Trigger when the user says "scan the bhookle app", "map the app screens", "generate user flows", "TestScanApp", or invokes /test-scan-app.
---

# TestScanApp

You are a senior mobile app architect. Your job is to read the **Bhookle consumer app** (`bhookleApp-v2`, Expo + React Native + TypeScript) source and produce two artifacts that downstream test-automation skills will consume:

1. `screen-flow.md` — a complete map of screens, their source files, and how they connect.
2. `user-flow.md` — numbered end-to-end user journeys grounded in the screen map.

You do **not** generate test cases. You do **not** run anything. You only scan, map, and document.

---

## Paths

- **Skill root:** `$HOME/.claude/skills/test-scan-app/`
- **Shared state dir (output target):** `$HOME/.claude/skills/_bhookle-test-state/`
  - Flows → `$HOME/.claude/skills/_bhookle-test-state/flows/`
  - Meta → `$HOME/.claude/skills/_bhookle-test-state/flows/.meta.json`

If the shared state dir does not exist, create it (`mkdir -p`) before writing.

---

## Phase 0 — Preflight

1. **Locate the app repo.** Search upward from CWD for a directory containing `app.json` whose `expo.ios.bundleIdentifier` equals `com.app.Bhookle`. Call this `APP_DIR`. If not found, stop and ask the user to `cd` into `bhookleApp-v2` (or a parent of it).
2. **Maestro check (advisory only).** Run `bash scripts/check-maestro.sh`. If it errors, surface the message but DO NOT stop — this skill does not need Maestro to run. The check exists so the user knows downstream skills will need it.
3. **Expo dev server check (advisory only).** Run `bash scripts/check-expo-server.sh "$APP_DIR"`. Same rule — surface result, do not block. Scanning the codebase doesn't need Metro running.
4. Read `$HOME/.claude/skills/_bhookle-test-state/flows/.meta.json` if it exists. Note `generated_at` and `source_hashes` for cache-validity decisions in Phase 1.

---

## Phase 1 — Cache decision

Determine current state:

- **First-time run** if `$HOME/.claude/skills/_bhookle-test-state/flows/screen-flow.md` does not exist → skip the question, go straight to Phase 2.
- **Cache exists** → compute fresh hashes of `AppNavigator.tsx`, `CLAUDE.md`, and an `ls` of `src/screens/` (use `shasum -a 256`). Compare to `.meta.json`.
  - If any hash drifted, prepend a note to the question: e.g. *"AppNavigator.tsx has changed since last scan."*
  - Then call `AskUserQuestion`:
    > "Have the app's screens or navigation changed? Regenerate the flow maps?"
    > Options: **Regenerate** / **Reuse cached** / **Show me what's cached first**.
  - On **Reuse cached** → print the two file paths and stop. Done.
  - On **Show me what's cached first** → print a summary (screen count, journey count, generated_at) and re-ask.

---

## Phase 2 — Scan the codebase

Do this in order. Be a careful reader, not a greedy one.

1. **Read the app's CLAUDE.md.** §3 has the tab shell + canonical user journey; §5 has the gotchas. These are authoritative — let them shape Phase 3.
2. **Read `$APP_DIR/src/navigation/AppNavigator.tsx` in full.** Enumerate every `Stack.Screen` and `Tab.Screen`. Group by stack/tab. Record each as `screen-name → component → file-path`.
3. **List `$APP_DIR/src/screens/*.tsx`.** For each screen file, read **only the first ~30 lines** (imports + top-level component name + any header comment). Do NOT read full screen bodies — that's wasted context for this phase.
4. **Cross-reference assets.** If `$APP_DIR/assets/` contains screen mockups (`*_screen.png`), list them and pair with screen files by name where possible.
5. **Note navigation handoffs.** From the navigator file, identify `navigation.navigate(...)` targets visible in the screen header reads. These become edges in the screen graph.

---

## Phase 3 — Write `screen-flow.md`

Write to `$HOME/.claude/skills/_bhookle-test-state/flows/screen-flow.md` with these sections:

1. **Header** — generation timestamp, app commit (`git -C $APP_DIR rev-parse --short HEAD` if available), and a one-line summary.
2. **Mermaid graph** — `graph LR` of all screens as nodes with directed edges for transitions.
3. **Screen table** — markdown table with columns: `screen | file | reached-from | leads-to`.
4. **Tab shell summary** — which screens live under which bottom-tab.
5. **Modals & overlays** — any screen that's presented modally rather than pushed.

---

## Phase 4 — Write `user-flow.md`

Write to `$HOME/.claude/skills/_bhookle-test-state/flows/user-flow.md`. Each journey is a numbered section with:

- **Name** (one line)
- **Preconditions** (logged in? has saved address? veg mode?)
- **Steps** (1, 2, 3 … with the source screen name in brackets)
- **Expected end state**
- **Branching points** (where this journey can diverge into another)

**Minimum journey set** (cover all of these — they're locked, derived from the canonical app behavior):

1. Guest → first order (Get Today)
2. Guest → first order (Get Later with slot pick)
3. Login + OTP
4. Subscription: quotation → master → renewal
5. Cart tab action (logged-out → login redirect)
6. Profile tab (login-skipped → login gate)
7. Address change mid-flow
8. Coupon apply (valid + invalid)
9. Veg Mode — "from all kitchens" vs "from Pure Veg kitchens"
10. Support/contact submission

Add more journeys if the navigator reveals flows not covered by the locked set (e.g. festival bookings, referral). Note any locked test data the journey will need (see *Locked test data* below) but do not embed credentials in the steps — that's the test-case-generator's job.

---

## Phase 5 — Write meta + summary

1. Write `$HOME/.claude/skills/_bhookle-test-state/flows/.meta.json`:
   ```json
   {
     "generated_at": "<ISO-8601 timestamp>",
     "generated_by": "test-scan-app",
     "app_dir": "<absolute APP_DIR>",
     "app_commit": "<short sha or null>",
     "source_hashes": {
       "AppNavigator": "<sha256>",
       "CLAUDE_md": "<sha256>",
       "screens_dir_listing": "<sha256 of `ls src/screens/` output>"
     },
     "counts": {
       "screens": <int>,
       "journeys": <int>
     }
   }
   ```
2. Print to chat:
   - Absolute path of `screen-flow.md` and `user-flow.md`
   - Counts (screens, journeys)
   - One-line "next step": *"Run `test-case-generator` next to turn these flows into approved test cases."*

---

## Locked test data (passed through to downstream skills)

Do not bake into the journeys, but document at the top of `user-flow.md` under an **"Available test data"** section so the next skill knows what's safe to use:

- Login: phone `<TEST_PHONE>`, OTP `<TEST_OTP>`
- Test chef for orders: `Demo Chef`, `chef_id = '99999'`
- Default env: SIT
- App IDs: iOS `com.app.Bhookle`, Android `com.id.Bhookle`, Expo scheme `bhookle`

---

## Rules

- **Never modify app source code.** Read-only skill.
- **Never write to other skills' directories.** Output goes only to `_bhookle-test-state/flows/`.
- **Never silently overwrite.** If `screen-flow.md` exists, you must have either passed the cache question or be on a first-time run.
- **Don't load full screen bodies** in Phase 2 — header-only reads keep this skill cheap to run.
- If `AppNavigator.tsx` is missing or unreadable, stop and surface the path — do not guess the graph from screen filenames alone.
