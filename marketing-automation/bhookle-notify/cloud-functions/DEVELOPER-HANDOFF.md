# Developer handoff — FIRST100 day-after follow-up push

**Goal:** every day at 11:00 IST, automatically send a push notification
("₹100 off your first meal 🍱 / Use code FIRST100 · home-cooked by real ammas
near you.") to every user who **registered yesterday and has not placed an
order**. This replaces a manual CSV process marketing runs today.

**Codebase:** `notifications/functions/` in the `bhookle-marketing` repo — the
same **bhookle-notify** Firebase functions codebase that already runs the
11:45/18:45 daily notifications (project `<firebase-project-id>`, region `asia-south1`).
Everything is already written and wired **except one function** that needs your
schema knowledge.

---

## Step 1 — Pull the code

```bash
git pull   # in bhookle-marketing
```

New/changed files:
- `notifications/functions/followup.js`  ← new module (read it top to bottom, ~150 lines)
- `notifications/functions/index.js`     ← one new scheduled export `followupRegNotOrdered` (11:00 IST daily)

## Step 2 — Implement `getEligibleUsers(start, end)` (the only real work)

Open `followup.js`, find the function marked **⚠️ DEVELOPER TODO**.

Contract:
- **Input:** `start`, `end` — JS `Date` objects (UTC instants) bounding "yesterday
  in IST" as a half-open interval `[start, end)`. Already computed and unit-tested — don't change.
- **Output:** `Promise<Array<{ uid: string, token: string }>>`
- **Criteria:** user registered within the window **AND** has zero orders **AND**
  has a non-empty FCM token.

The file contains two reference implementations — use whichever matches reality:
- **Firestore** sketch (if users/orders live in Firestore) — adjust collection
  and field names (`users`, `createdAt`, `fcmToken`, `orderCount` are guesses).
- **SQL** equivalent (if users/orders live in your own DB):
  ```sql
  SELECT u.user_id AS uid, u.fcm_token AS token
  FROM users u
  LEFT JOIN orders o ON o.user_id = u.user_id
  WHERE u.created_at >= :start AND u.created_at < :end
    AND o.id IS NULL AND u.fcm_token IS NOT NULL;
  ```
  Run through your existing DB client and map rows to `{uid, token}`.

Do **not** filter out already-notified users yourself — `sendFollowup()` does
that via the `reactivation_log` Firestore collection (see Step 3).

## Step 3 — Understand the safety model (nothing to build, just don't break it)

- **Once-ever guarantee:** before sending, every uid is checked against the
  `reactivation_log` collection; after sending, every touched uid is written
  there (`status: sent | invalid_token`). Re-runs, retries, and overlapping
  data sources can never message the same user twice. Don't bypass it.
- **Transient errors** are deliberately NOT logged, so those users retry on
  tomorrow's run if still eligible.
- **Dead tokens** get `status: invalid_token`. Optional (recommended): in that
  branch, also clear the stale token on the user record — the hook point is
  marked with a comment. This fixes the ~60%/month token-rot we measured.

## Step 4 — Test before deploying

Dry run (queries + filters, sends nothing):
```bash
cd notifications/functions
node -e "
const { initializeApp } = require('firebase-admin/app');
initializeApp();  // needs GOOGLE_APPLICATION_CREDENTIALS or gcloud ADC
const { sendFollowup } = require('./followup');
sendFollowup({ dryRun: true }).then(r => console.log(JSON.stringify(r, null, 2)));
"
```
Expected output: `{ window: {...}, eligible: N, alreadyTouched: M, sent: 0, dryRun: true }`.
Sanity-check `eligible` against a manual DB count for yesterday.

Then a real one-user test: temporarily make `getEligibleUsers` return just
`[{ uid: '<your-own-uid>', token: '<your-device-token>' }]`, run
`sendFollowup()` without dryRun, confirm the push lands on your phone, then
**delete your uid from `reactivation_log`** and restore the real query.

## Step 5 — Deploy

```bash
cd notifications/functions
firebase deploy --only functions:followupRegNotOrdered --project <firebase-project-id>
```
Cloud Scheduler is auto-provisioned by `onSchedule` (same as the existing
notify functions). Runtime uses the default compute service account — it
already has FCM + Firestore access (same as notifyLunch/notifyDinner).

## Step 6 — Cutover

Nothing to disable — the interim CSV pipeline was removed on 2026-07-13; this
function is the only follow-up mechanism. One historical note: users who
registered **Jun 12 – Jul 12 2026** already received this push via a one-off
blast on Jul 13 (record: `notifications/followup_registry.json`). Since this
function only ever targets *yesterday's* registrants, there is no overlap —
but if you ever widen the window beyond one day, seed `reactivation_log` from
that file first.

Tell Arvind when the function is live.

## Step 7 — Verify for the first 2–3 days

- Cloud Functions logs (`followupRegNotOrdered`) print a JSON summary per run:
  `{ eligible, alreadyTouched, sent, invalidToken, errors }`.
- Cross-check `sent` against FIRST100 code redemptions.

## One question to answer back

Does the app update the stored FCM token **on every app open**, or only at
registration? We measured ~60% token death within a month on this segment.
If tokens are only captured at signup, adding an on-open token refresh
(`onTokenRefresh` / `getToken()` → write to user record) will materially
increase reach for this and every future push.

— Prepared 2026-07-13. Copy questions to Arvind; the message text is marketing-
approved and lives as constants at the top of `followup.js` — don't change it
without his sign-off.
