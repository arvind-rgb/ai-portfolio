# BhookleQaBackend

Hosted backend for the Bhookle QA test-catalog dashboard. Backs onto a new `qa.*` schema in the existing SIT Postgres (`<database>`). Deployed as a Firebase Function (`bhookleQaBackend`, asia-south1).

**Production safety**: every query in this BE fully qualifies `qa.*` table names, and the pool sets `search_path=qa,public` on each connection. No DDL ever touches existing product tables. The DDL script has a pre-flight snapshot of `public.*` and aborts on any drift.

## Layout

```
app.js                       express + Firebase Functions entrypoint
config/postgresql.js         PG pool; search_path forced to qa,public
config/firebase-auth.js      ID-token middleware + email allowlist + CLI-token fallback
src/routes/catalog.js        GET/save/status/lock/unlock
src/routes/tcs.js            POST (create) + PUT (update); auto-assigns tc_id per screen
src/routes/snapshots.js      list / take / restore (replaces local _forks/)
scripts/init-qa-schema.js    idempotent DDL with pre-flight schema check
scripts/migrate-from-json.js one-shot: local catalog.json → qa.test_catalog
```

## HTTP contract (all `/api/*` paths gated by auth middleware)

| Method | Path | Body | Description |
|---|---|---|---|
| GET  | `/api/catalog`             | — | full catalog + meta + recent runs/bugs |
| POST | `/api/catalog/save`        | `{ test_cases: [{tc_id, status?, comments?}] }` | bulk-save inline edits |
| GET  | `/api/catalog/status`      | — | summary `{ all_approved, locked, total, by_status, by_priority }` |
| POST | `/api/catalog/lock`        | — | sets `qa.catalog_meta.locked=true` (rejects unless all approved) |
| POST | `/api/catalog/unlock`      | — | clears lock |
| POST | `/api/tcs`                 | TC fields (`screen` + `title` required) | manual create; BE auto-assigns `tc_id` |
| PUT  | `/api/tcs/:tc_id`          | partial TC | update any field on a single TC |
| GET  | `/api/snapshots`           | — | list snapshots |
| POST | `/api/snapshots`           | `{ label? }` | take a snapshot of current catalog |
| POST | `/api/snapshots/:id/restore` | — | restore (auto-takes a pre-restore snapshot first) |

**Auth options on `/api/*`:**
- `Authorization: Bearer <firebase-id-token>` — browser path; email must be in `ALLOWED_EMAILS`.
- `X-CLI-Token: <shared-secret>` — CLI path; matches `QA_CLI_TOKEN` env. Used by `test-case-generator` skill helpers.

## Deploy runbook

> Each step is verifiable before the next. **Do not run `migrate-from-json.js` until the schema script succeeded.** **Do not delete local `catalog.json` until end-to-end verification passes.**

### 0. One-time prerequisites

- **Firebase project**: `<your-firebase-project>` (existing). Already on Blaze plan from BhookleAdminBackend/BhookleWebBackend deploys — no plan change needed. Adding this BE is **$0 incremental** (well under free tier: 2M Function invocations/mo, 5 GB egress/mo).
- **Firebase CLI**: `npm i -g firebase-tools && firebase login`.
- **Postgres credentials**: same SIT values as `BhookleAdminBackend/.env`.

### 0.1 Set a $1 billing alert (do this before deploying — protects the "$0 in practice" guarantee)

1. Open [Google Cloud Console → Billing → Budgets & alerts](https://console.cloud.google.com/billing/budgets) for the billing account attached to `<your-firebase-project>`.
2. **Create budget** → name: `bhookle-qa-tripwire`, scope: project `<your-firebase-project>`, amount: **$1 USD/month**, alert thresholds at 50% / 90% / 100%, email: an allow-listed Google account.
3. Save. You'll never see an alert in practice — but if there's a bug that runs away, you find out before any real spend.

### 0.2 Create the Hosting site (one-time)

The admin dashboard uses Hosting site `bhookle-admin` under `<your-firebase-project>`. We mirror that pattern with a new site `bhookle-qa`. URL will be `https://bhookle-qa.web.app`.

1. Firebase console → Hosting → **Add another site** → site ID: `bhookle-qa`.
2. (If `bhookle-qa` is taken, pick `bhookle-qa2` or similar — note your choice and update `BhookleQaDashboard/firebase.json`'s `"site"` field + `BhookleQaDashboard/public/config.js`'s `authDomain` if you changed projects.)

### 1. Configure env

```bash
cd BhookleQaBackend
cp .env.example .env
# Edit .env:
#   POSTGRESQL_USER, POSTGRESQL_PASSWORD  — copy from BhookleAdminBackend/.env
#   FIREBASE_PROJECT_ID                   — the Firebase project hosting this BE
#   ALLOWED_EMAILS                        — already pre-filled (arvind@, reviewer2@)
#   QA_CLI_TOKEN                          — generate: openssl rand -hex 32
npm install
```

### 2. Create the `qa` schema (read-only impact on `public`)

```bash
npm run init-schema
# Expected output:
#   PRE-FLIGHT — snapshotting public schema… (N tables)
#   running CREATE … IF NOT EXISTS DDL…
#   POST-FLIGHT — re-snapshotting public… public unchanged ✓
#   qa.* tables: bugs, catalog_meta, catalog_snapshots, run_results, test_catalog ✓
#   DONE ✓
```

If you see "PUBLIC SCHEMA CHANGED — aborting" — **STOP** and inspect. The script will not commit, but report it.

### 3. Migrate the existing 190 TCs

```bash
npm run migrate
# Expected:  DONE ✓  inserted=190  updated=0  total_in_db=190
#            qa.catalog_snapshots seeded with 'pre-cloud-cutover'
```

### 4. Configure Firebase Auth

In the Firebase console for your project:
- Authentication → Sign-in method → enable **Google**.
- Authentication → Settings → Authorized domains → make sure `<project>.web.app` is listed.

(The email allowlist is enforced server-side from `ALLOWED_EMAILS`; the FE shows sign-in for any Google user, but the BE returns 403 unless allowlisted.)

### 5. Deploy the Function

```bash
cp .firebaserc.example .firebaserc   # already points to <your-firebase-project>
firebase use <your-firebase-project>
firebase deploy --only functions:bhookleQaBackend
# Output: Function URL:
#   https://<region>-<your-project>.cloudfunctions.net/bhookleQaBackend
```

### 6. Deploy the dashboard

```bash
cd ../BhookleQaDashboard
cp .firebaserc.example .firebaserc   # already points to <your-firebase-project>
# Edit public/config.js — API_BASE is already pre-filled for <your-firebase-project>;
# fill in FIREBASE.apiKey and FIREBASE.appId from the Firebase console
# (Project settings → General → Your apps → Web app → SDK setup snippet).
firebase deploy --only hosting
# Output: Hosting URL: https://bhookle-qa.web.app
```

### 7. Verify end-to-end

1. Open the Hosting URL on your laptop. Sign in with an allow-listed Google account.
2. Confirm 190 TCs render with descriptions and statuses.
3. Edit one TC's status → Save → refresh → edit persists.
4. Click **+ New Test Case**, fill in `Screen=Cart Screen`, `Title=Manual TC sanity`, submit. Confirm it appears in the list with `source=manual`.
5. From a phone or another device, open the same URL, sign in, confirm edits visible.
6. Sanity SQL (read-only) to confirm production tables untouched:
   ```sql
   SELECT table_name FROM information_schema.tables
   WHERE table_schema='public' AND table_type='BASE TABLE'
   ORDER BY 1;
   -- compare to a snapshot you took before step 2; should be identical
   ```

### 8. Retire the local server (only after step 7)

```bash
# Final safety copy on disk:
TS=$(date +%Y-%m-%d_%H%M%S)
mkdir -p ~/.claude/skills/_bhookle-test-state/_forks/${TS}_pre-cloud-removal
cp ~/.claude/skills/_bhookle-test-state/testcases/catalog.json \
   ~/.claude/skills/_bhookle-test-state/_forks/${TS}_pre-cloud-removal/

# Stop & remove the local server + catalog:
lsof -ti :7777 | xargs -r kill
rm ~/.claude/skills/_bhookle-test-state/testcases/catalog.json
rm ~/.claude/skills/test-case-generator/scripts/serve.py
```

## Local dev (optional)

```bash
npm start          # runs Express on :3010 (skips Functions wrapper)
# In another shell:
curl http://localhost:3010/health
curl -H "X-CLI-Token: $QA_CLI_TOKEN" http://localhost:3010/api/catalog | jq '.test_cases | length'
```
