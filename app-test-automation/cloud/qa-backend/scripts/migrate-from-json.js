/**
 * One-shot migration: local catalog.json → qa.test_catalog.
 *
 * Reads the existing local catalog, INSERTs each TC into qa.test_catalog
 * (source='generated'), seeds qa.catalog_meta, and takes an initial snapshot
 * labeled 'pre-cloud-cutover' into qa.catalog_snapshots.
 *
 * Safety:
 *   - All writes are scoped to qa.*. Public schema is never touched.
 *   - Re-runnable: existing TCs are upserted on tc_id. Run-results + bugs are
 *     untouched.
 *   - Pre-flight: snapshots public.* table list; aborts on any change.
 *
 * Usage:  node scripts/migrate-from-json.js [path/to/catalog.json]
 *         default path is the local skill state dir.
 */

require("dotenv").config();
const fs = require("fs");
const path = require("path");
const os = require("os");
const pool = require("../config/postgresql");

const DEFAULT_PATH = path.join(
  os.homedir(),
  ".claude/skills/_bhookle-test-state/testcases/catalog.json"
);

async function publicTableList(client) {
  const { rows } = await client.query(`
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    ORDER BY table_name
  `);
  return rows.map((r) => r.table_name);
}

(async function main() {
  const src = process.argv[2] || DEFAULT_PATH;
  if (!fs.existsSync(src)) {
    console.error("[migrate] catalog.json not found at:", src);
    process.exit(1);
  }

  const raw = JSON.parse(fs.readFileSync(src, "utf8"));
  const tcs = Array.isArray(raw.test_cases) ? raw.test_cases : [];
  if (tcs.length === 0) {
    console.error("[migrate] catalog has no test_cases");
    process.exit(1);
  }

  const client = await pool.connect();
  try {
    console.log("[migrate] source:", src);
    console.log("[migrate] target db:", process.env.POSTGRESQL_DATABASE);
    console.log("[migrate] TCs to migrate:", tcs.length);
    console.log();

    const publicBefore = await publicTableList(client);
    console.log(
      `[migrate] PRE-FLIGHT public.* tables: ${publicBefore.length} (snapshotted)`
    );

    await client.query("BEGIN");

    let inserted = 0;
    let updated = 0;
    for (const t of tcs) {
      if (!t.tc_id || !t.screen || !t.title) {
        console.warn("[migrate] skipping invalid TC:", t.tc_id);
        continue;
      }
      const r = await client.query(
        `INSERT INTO qa.test_catalog
           (tc_id, screen, journey, title, description, priority, type, category,
            platform, preconditions, steps, expected, data, verified_from, tags,
            maestro_yaml, default_status, status, comments, source)
         VALUES
           ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)
         ON CONFLICT (tc_id) DO UPDATE SET
            screen=EXCLUDED.screen,
            journey=EXCLUDED.journey,
            title=EXCLUDED.title,
            description=EXCLUDED.description,
            priority=EXCLUDED.priority,
            type=EXCLUDED.type,
            category=EXCLUDED.category,
            platform=EXCLUDED.platform,
            preconditions=EXCLUDED.preconditions,
            steps=EXCLUDED.steps,
            expected=EXCLUDED.expected,
            data=EXCLUDED.data,
            verified_from=EXCLUDED.verified_from,
            tags=EXCLUDED.tags,
            maestro_yaml=EXCLUDED.maestro_yaml,
            default_status=EXCLUDED.default_status,
            status=EXCLUDED.status,
            comments=EXCLUDED.comments,
            updated_at=NOW()
         RETURNING (xmax = 0) AS inserted`,
        [
          t.tc_id,
          t.screen,
          t.journey || null,
          t.title,
          t.description || null,
          t.priority || null,
          t.type || null,
          t.category || null,
          t.platform || "Both",
          t.preconditions || null,
          t.steps || null,
          t.expected || null,
          t.data || null,
          t.verified_from || null,
          t.tags || null,
          t.maestro_yaml || null,
          t.default_status || "Pending Review",
          t.status || "Pending Review",
          t.comments || null,
          "generated",
        ]
      );
      if (r.rows[0].inserted) inserted++;
      else updated++;
    }

    await client.query(
      `INSERT INTO qa.catalog_meta (id, schema_version, locked, last_written_at)
       VALUES (1, $1, FALSE, NOW())
       ON CONFLICT (id) DO UPDATE
         SET schema_version = EXCLUDED.schema_version,
             last_written_at = NOW()`,
      [raw.schema_version || "v2"]
    );

    // initial snapshot
    const snap = await client.query(
      "SELECT * FROM qa.test_catalog ORDER BY tc_id"
    );
    const meta = await client.query(
      "SELECT * FROM qa.catalog_meta WHERE id = 1"
    );
    await client.query(
      `INSERT INTO qa.catalog_snapshots (label, payload) VALUES ($1, $2)`,
      [
        "pre-cloud-cutover",
        {
          taken_at: new Date().toISOString(),
          test_cases: snap.rows,
          meta: meta.rows[0],
          run_results: [],
          bugs: [],
        },
      ]
    );

    const publicAfter = await publicTableList(client);
    if (publicAfter.join("|") !== publicBefore.join("|")) {
      throw new Error("public.* changed during migration — rolling back");
    }

    await client.query("COMMIT");
    console.log(
      `[migrate] DONE ✓  inserted=${inserted}  updated=${updated}  total_in_db=${
        inserted + updated
      }`
    );
    console.log(
      "[migrate] qa.catalog_snapshots seeded with 'pre-cloud-cutover'"
    );
  } catch (e) {
    await client.query("ROLLBACK").catch(() => {});
    console.error("[migrate] FAILED:", e.message);
    process.exitCode = 1;
  } finally {
    client.release();
    await pool.end();
  }
})();
