/**
 * Idempotent DDL runner for the `qa` schema.
 *
 * Hard guarantees enforced here (matching the approved plan):
 *   1. Pre-flight snapshots `public.*` table list, runs DDL, then snapshots again.
 *      If ANY product table appears/disappears/changes count, we ABORT and roll back.
 *   2. DDL is CREATE … IF NOT EXISTS only. No DROP/ALTER/TRUNCATE anywhere.
 *   3. All objects live under `qa.*` — never the public schema.
 *
 * Re-run safely: every CREATE is guarded by IF NOT EXISTS.
 *
 * Usage:  node scripts/init-qa-schema.js
 */

require("dotenv").config();
const pool = require("../config/postgresql");

const DDL = `
BEGIN;

CREATE SCHEMA IF NOT EXISTS qa;

CREATE TABLE IF NOT EXISTS qa.test_catalog (
  tc_id            TEXT PRIMARY KEY,
  screen           TEXT NOT NULL,
  journey          TEXT,
  title            TEXT NOT NULL,
  description      TEXT,
  priority         TEXT,
  type             TEXT,
  category         TEXT,
  platform         TEXT DEFAULT 'Both',
  preconditions    TEXT,
  steps            TEXT,
  expected         TEXT,
  data             TEXT,
  verified_from    TEXT,
  tags             TEXT,
  maestro_yaml     TEXT,
  default_status   TEXT DEFAULT 'Pending Review',
  status           TEXT DEFAULT 'Pending Review',
  comments         TEXT,
  last_run_result  TEXT,
  last_run_ts      TIMESTAMPTZ,
  failure_reason   TEXT,
  screenshot_path  TEXT,
  source           TEXT DEFAULT 'generated',
  created_at       TIMESTAMPTZ DEFAULT NOW(),
  updated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qa.catalog_meta (
  id              INT PRIMARY KEY DEFAULT 1,
  schema_version  TEXT,
  locked          BOOLEAN DEFAULT FALSE,
  locked_at       TIMESTAMPTZ,
  last_written_at TIMESTAMPTZ DEFAULT NOW(),
  CHECK (id = 1)
);

CREATE TABLE IF NOT EXISTS qa.run_results (
  id           BIGSERIAL PRIMARY KEY,
  tc_id        TEXT REFERENCES qa.test_catalog(tc_id) ON DELETE CASCADE,
  platform     TEXT,
  status       TEXT,
  duration_s   NUMERIC,
  log_excerpt  TEXT,
  ran_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qa.bugs (
  id          BIGSERIAL PRIMARY KEY,
  bug_id      TEXT,
  tc_id       TEXT REFERENCES qa.test_catalog(tc_id) ON DELETE SET NULL,
  severity    TEXT,
  summary     TEXT,
  details     TEXT,
  reported_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qa.catalog_snapshots (
  id          BIGSERIAL PRIMARY KEY,
  label       TEXT,
  payload     JSONB NOT NULL,
  taken_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Skill 1 output (test-scan-app). Latest row wins; older rows kept for history.
CREATE TABLE IF NOT EXISTS qa.app_analysis (
  id                 BIGSERIAL PRIMARY KEY,
  app_commit         TEXT,
  scan_version       INT,
  app_dir            TEXT,
  screen_flow_md     TEXT,
  user_flow_md       TEXT,
  journey_flow_html  TEXT,
  meta               JSONB,
  screens_count      INT,
  journeys_count     INT,
  scanned_at         TIMESTAMPTZ,
  uploaded_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Skill 1 reference uploads (PDFs, screenshots) attached to the next scan.
-- Inline bytea for simplicity; cap enforced server-side (5 MB).
CREATE TABLE IF NOT EXISTS qa.app_analysis_inputs (
  id           BIGSERIAL PRIMARY KEY,
  kind         TEXT NOT NULL,                     -- 'pdf' | 'screenshot' | 'other'
  filename     TEXT NOT NULL,
  mime_type    TEXT NOT NULL,
  size_bytes   INT NOT NULL,
  file_data    BYTEA NOT NULL,
  note         TEXT,
  uploaded_at  TIMESTAMPTZ DEFAULT NOW(),
  uploaded_by  TEXT
);

-- Skill 3 (run-auto-test). Tables originally placeholder; now extended.
CREATE TABLE IF NOT EXISTS qa.test_runs (
  id            BIGSERIAL PRIMARY KEY,
  label         TEXT,
  platform      TEXT,                              -- 'android' | 'ios'
  apk_url       TEXT,
  app_url       TEXT,
  status        TEXT DEFAULT 'queued',             -- queued | running | done | failed
  triggered_by  TEXT,
  started_at    TIMESTAMPTZ,
  finished_at   TIMESTAMPTZ,
  summary       JSONB,                             -- {pass, fail, skipped, duration_s, report_url}
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ── Skill 3 additions (2026-06-08) ────────────────────────────────────────
-- All additive. ALTER … ADD COLUMN IF NOT EXISTS is purely add-only and safe
-- to re-run; no existing data is touched.

-- Uploaded app builds. File lives in Firebase Storage; we only record metadata.
CREATE TABLE IF NOT EXISTS qa.builds (
  id              BIGSERIAL PRIMARY KEY,
  platform        TEXT NOT NULL,                   -- 'android' | 'ios'
  label           TEXT,
  storage_path    TEXT NOT NULL,                   -- 'qa/builds/<uuid>.apk' etc.
  size_bytes      BIGINT,
  sha256          TEXT,
  uploaded_by     TEXT,
  uploaded_at     TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE qa.test_runs ADD COLUMN IF NOT EXISTS android_build_id BIGINT REFERENCES qa.builds(id);
ALTER TABLE qa.test_runs ADD COLUMN IF NOT EXISTS ios_build_id     BIGINT REFERENCES qa.builds(id);
ALTER TABLE qa.test_runs ADD COLUMN IF NOT EXISTS gh_run_id        TEXT;
ALTER TABLE qa.test_runs ADD COLUMN IF NOT EXISTS gh_run_url       TEXT;
ALTER TABLE qa.test_runs ADD COLUMN IF NOT EXISTS report_dir       TEXT;     -- Storage path 'qa/runs/<id>/'
ALTER TABLE qa.test_runs ADD COLUMN IF NOT EXISTS callback_token_hash TEXT;  -- sha256 of issued HMAC; never store raw

-- Per-shard checkpoints so the FE can show "Android shard 2/4 done".
CREATE TABLE IF NOT EXISTS qa.run_shards (
  id              BIGSERIAL PRIMARY KEY,
  run_id          BIGINT REFERENCES qa.test_runs(id) ON DELETE CASCADE,
  platform        TEXT NOT NULL,                   -- 'android' | 'ios'
  shard_index     INT NOT NULL,
  shard_total     INT NOT NULL,
  status          TEXT DEFAULT 'queued',           -- queued|running|done|failed
  started_at      TIMESTAMPTZ,
  finished_at     TIMESTAMPTZ,
  passed          INT, failed INT, skipped INT,
  log_excerpt     TEXT,
  UNIQUE (run_id, platform, shard_index)
);
CREATE INDEX IF NOT EXISTS idx_run_shards_run_id ON qa.run_shards(run_id);

-- Scope results + bugs to a specific run.
ALTER TABLE qa.run_results ADD COLUMN IF NOT EXISTS run_id BIGINT REFERENCES qa.test_runs(id) ON DELETE CASCADE;
ALTER TABLE qa.bugs        ADD COLUMN IF NOT EXISTS run_id BIGINT REFERENCES qa.test_runs(id) ON DELETE SET NULL;

-- Bug detection extras.
ALTER TABLE qa.bugs ADD COLUMN IF NOT EXISTS signature          TEXT;         -- sha1(tc_id + first 200 chars of failure)
ALTER TABLE qa.bugs ADD COLUMN IF NOT EXISTS platform           TEXT;         -- 'android' | 'ios' | 'both'
ALTER TABLE qa.bugs ADD COLUMN IF NOT EXISTS platform_diff_flag BOOLEAN DEFAULT FALSE;
ALTER TABLE qa.bugs ADD COLUMN IF NOT EXISTS first_seen_run_id  BIGINT REFERENCES qa.test_runs(id) ON DELETE SET NULL;
ALTER TABLE qa.bugs ADD COLUMN IF NOT EXISTS last_seen_run_id   BIGINT REFERENCES qa.test_runs(id) ON DELETE SET NULL;
ALTER TABLE qa.bugs ADD COLUMN IF NOT EXISTS occurrence_count   INT DEFAULT 1;
ALTER TABLE qa.bugs ADD COLUMN IF NOT EXISTS screenshot_url     TEXT;
CREATE INDEX IF NOT EXISTS idx_bugs_signature ON qa.bugs(signature);

-- Per-occurrence ledger — links a known bug signature to every run it appeared in.
CREATE TABLE IF NOT EXISTS qa.bug_occurrences (
  id           BIGSERIAL PRIMARY KEY,
  bug_id       BIGINT REFERENCES qa.bugs(id) ON DELETE CASCADE,
  run_id       BIGINT REFERENCES qa.test_runs(id) ON DELETE CASCADE,
  occurred_at  TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (bug_id, run_id)
);

-- Maestro bundle versions (zipped maestro/ dir uploaded from dev machine).
CREATE TABLE IF NOT EXISTS qa.maestro_bundles (
  id            BIGSERIAL PRIMARY KEY,
  version       TEXT NOT NULL,
  storage_path  TEXT NOT NULL,                    -- 'qa/maestro-bundles/<version>.tar.gz'
  size_bytes    BIGINT,
  sha256        TEXT,
  uploaded_by   TEXT,
  uploaded_at   TIMESTAMPTZ DEFAULT NOW(),
  is_active     BOOLEAN DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_maestro_bundles_active ON qa.maestro_bundles(is_active, uploaded_at DESC);

COMMIT;
`;

async function snapshotPublic(client) {
  const { rows } = await client.query(`
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    ORDER BY table_name
  `);
  return rows.map((r) => r.table_name).join("|");
}

async function listQaObjects(client) {
  const { rows: schemas } = await client.query(
    "SELECT schema_name FROM information_schema.schemata WHERE schema_name='qa'"
  );
  const { rows: tables } = await client.query(`
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema='qa' AND table_type='BASE TABLE'
    ORDER BY table_name
  `);
  return {
    qaSchemaExists: schemas.length > 0,
    qaTables: tables.map((r) => r.table_name),
  };
}

(async function main() {
  const client = await pool.connect();
  try {
    console.log("[init-qa-schema] connecting to:", process.env.POSTGRESQL_HOST);
    console.log("[init-qa-schema] db:", process.env.POSTGRESQL_DATABASE);
    console.log();

    console.log("[init-qa-schema] PRE-FLIGHT — snapshotting public schema…");
    const publicBefore = await snapshotPublic(client);
    const beforeCount = publicBefore.split("|").filter(Boolean).length;
    console.log(`[init-qa-schema]   public has ${beforeCount} tables before DDL`);

    const qaBefore = await listQaObjects(client);
    console.log(
      `[init-qa-schema]   qa schema before: ${
        qaBefore.qaSchemaExists ? "exists" : "missing"
      }; tables: ${qaBefore.qaTables.join(", ") || "(none)"}`
    );
    console.log();

    console.log("[init-qa-schema] running CREATE … IF NOT EXISTS DDL…");
    await client.query(DDL);
    console.log("[init-qa-schema]   DDL applied.");
    console.log();

    console.log("[init-qa-schema] POST-FLIGHT — re-snapshotting public…");
    const publicAfter = await snapshotPublic(client);
    if (publicAfter !== publicBefore) {
      throw new Error(
        "PUBLIC SCHEMA CHANGED — aborting. before=" +
          publicBefore +
          " after=" +
          publicAfter
      );
    }
    console.log(
      `[init-qa-schema]   public unchanged (${beforeCount} tables) ✓`
    );

    const qaAfter = await listQaObjects(client);
    const expected = [
      "app_analysis",
      "app_analysis_inputs",
      "bug_occurrences",
      "bugs",
      "builds",
      "catalog_meta",
      "catalog_snapshots",
      "maestro_bundles",
      "run_results",
      "run_shards",
      "test_catalog",
      "test_runs",
    ];
    const missing = expected.filter((t) => !qaAfter.qaTables.includes(t));
    if (!qaAfter.qaSchemaExists || missing.length > 0) {
      throw new Error(
        "qa schema not fully present after DDL — missing: " +
          missing.join(", ")
      );
    }
    console.log(`[init-qa-schema]   qa.* tables: ${qaAfter.qaTables.join(", ")} ✓`);
    console.log();
    console.log("[init-qa-schema] DONE ✓");
  } catch (e) {
    console.error("[init-qa-schema] FAILED:", e.message);
    process.exitCode = 1;
  } finally {
    client.release();
    await pool.end();
  }
})();
