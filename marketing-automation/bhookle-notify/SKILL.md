# bhookle-notify — On-the-dot push-notification scheduler

Autonomous Bhookle app push notifications via **FCM topic `all`** (Firebase project
`<firebase-project-id>`). **Sending is on-the-dot via Cloud Scheduler + Firebase functions**
(±seconds), not GitHub Actions. Works with your laptop off. No servers to maintain.

Two motherly nudges a day: **lunch 11:45 IST**, **dinner 18:45 IST**.
Vibe: weekday lunch = gentle work-time concern · weekday dinner = eat healthy + relax ·
weekend (both) = home-cooked comfort + therapy.

## Why Cloud Scheduler (not GitHub Actions) sends
GitHub native cron drifts 3–15 min, and even a precise trigger pays ~30–90s of runner
spin-up. Cloud Scheduler fires to the second and the function calls FCM directly (~200ms),
in the same project/region (asia-south1) as FCM. GitHub Actions is kept only for syncing
the calendar to Firestore and the Monday FYI email.

## Components
```
notifications/notification-calendar.json   (source of truth; lint guards no-repeat)
        │  (commit/push)
GitHub Actions (.github/workflows/bhookle-notify.yml)
        │  mode=sync → notifications/functions/sync.js → Firestore  app_notifications/<date>_<slot>
        ▼
Firestore (<firebase-project-id>, default DB, asia-south1)
        ▲ read + mark posted
Cloud Scheduler (auto-created by onSchedule, tz Asia/Kolkata)
   notifyLunch 11:45 (+notifyLunchRetry 11:57) · notifyDinner 18:45 (+notifyDinnerRetry 18:57)
        │
   notifications/functions/index.js → notify.js sendSlot() → FCM HTTP v1 → topic "all"
```

### Firebase functions (codebase `bhookle-notify`, isolated from other <firebase-project-id> fns)
- `notifications/functions/notify.js` — `sendSlot(slot)`: reads `app_notifications/<IST-date>_<slot>`,
  sends if status=`scheduled`, marks `posted` (idempotent → retries never double-send).
- `notifications/functions/index.js` — 4 `onSchedule` exports (primary + 12-min retry per meal).
- `notifications/functions/sync.js` — calendar JSON → Firestore (never downgrades `posted`).
- `notifications/functions/test_local.js` — local dry/real verify (not deployed).
- Deploy: `firebase deploy --only functions:bhookle-notify --project <firebase-project-id>`
  (runtime = default compute SA, which has roles/editor → FCM + Firestore).

### GitHub Actions (`bhookle-notify.yml`) — does NOT send
- `sync` (auto on calendar push) — pushes armed entries to Firestore.
- `preview` (Mon 07:00 IST) — FYI email of the week.
- `dry` (manual) — FCM auth self-test. `tick` (manual) — break-glass sender only.

## Source of truth & status
`notifications/notification-calendar.json`, entries: `date, day, kind, slot, send_ist, title, body, status`.
Status: `yet_to_schedule → scheduled → posted`. In steady state the **calendar holds the plan**
(`scheduled`) and **Firestore holds live truth** (`posted` after the function sends).

## Secrets
- `FCM_SERVICE_ACCOUNT_JSON` (GitHub) — used by the Actions `sync` (Firestore write) + dry self-test.
- `GMAIL_USER`, `GMAIL_APP_PASSWORD` (GitHub) — preview email.
- The Cloud Function needs **no secret** — it uses its runtime SA (ADC).

## Weekly operating rhythm
1. **Generate** next week's copy with Claude (brand-voice on); keep ~2 weeks armed ahead.
2. **No repeats:** every title unique vs the whole calendar — `lint_calendar.py` enforces it.
3. **Arm** (status=`scheduled`) + commit. Push auto-syncs to Firestore (or run `node sync.js`).
4. **Mon 07:00 IST** — FYI email; reply to request changes.
5. Cloud Scheduler fires each slot on the dot; Firestore docs go `posted`.

## Copy rules (see bhookle-brand-voice)
Title-only, **≤ 26 chars**. Body = single space `" "` (FCM rejects empty). Motherly "beta"
voice, no URLs, no banned vocab. **Never reuse a title** already in the calendar.

## Manual ops
```bash
# Lint, then sync after generating a week:
python3 _skills/bhookle-notify/scripts/lint_calendar.py
cd notifications/functions && GOOGLE_APPLICATION_CREDENTIALS=/path/key.json node sync.js
# Verify a slot end-to-end without delivering (reads Firestore, validates FCM):
GOOGLE_APPLICATION_CREDENTIALS=/path/key.json node test_local.js lunch dry 2026-06-19
# Redeploy functions:
firebase deploy --only functions:bhookle-notify --project <firebase-project-id>
```
