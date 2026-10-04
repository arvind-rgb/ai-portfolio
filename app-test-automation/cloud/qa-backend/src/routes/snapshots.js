/**
 * /api/snapshots — replaces the local _forks/ directory.
 *
 *   GET  /            → list snapshots (id, label, taken_at)
 *   POST /            → take a snapshot of the current catalog
 *   POST /:id/restore → restore a snapshot (always snapshots current state first)
 *
 * Snapshot payload is the full catalog (test_cases + meta + run_results + bugs)
 * stored as JSONB so we can restore exactly what was there.
 */

const express = require("express");
const pool = require("../../config/postgresql");

const router = express.Router();

router.get("/", async (_req, res, next) => {
  try {
    const { rows } = await pool.query(
      "SELECT id, label, taken_at FROM qa.catalog_snapshots ORDER BY taken_at DESC LIMIT 100"
    );
    res.json(rows);
  } catch (e) {
    next(e);
  }
});

router.post("/", async (req, res, next) => {
  const label = (req.body && req.body.label) || "manual";
  try {
    const id = await takeSnapshot(label);
    res.json({ ok: true, snapshot_id: id });
  } catch (e) {
    next(e);
  }
});

router.post("/:id/restore", async (req, res, next) => {
  const id = parseInt(req.params.id, 10);
  if (!Number.isFinite(id)) {
    return res.status(400).json({ error: "bad snapshot id" });
  }
  const client = await pool.connect();
  try {
    const { rows } = await client.query(
      "SELECT payload FROM qa.catalog_snapshots WHERE id = $1",
      [id]
    );
    if (!rows[0]) return res.status(404).json({ error: "snapshot not found" });
    const payload = rows[0].payload;
    if (!Array.isArray(payload.test_cases)) {
      return res
        .status(400)
        .json({ error: "snapshot payload missing test_cases array" });
    }

    // Take a fresh snapshot of CURRENT state before restoring — undo path.
    await takeSnapshot(`pre-restore-of-${id}`);

    await client.query("BEGIN");

    // Restore test_catalog fields in-place. We don't delete TCs the snapshot
    // doesn't mention (defensive — if a manual TC was added after the
    // snapshot, restoring should not silently wipe it). The pre-restore
    // snapshot we just took covers anything inadvertently changed below.
    for (const tc of payload.test_cases) {
      if (!tc.tc_id) continue;
      await client.query(
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
            source=EXCLUDED.source,
            updated_at=NOW()`,
        [
          tc.tc_id,
          tc.screen,
          tc.journey || null,
          tc.title,
          tc.description || null,
          tc.priority || null,
          tc.type || null,
          tc.category || null,
          tc.platform || "Both",
          tc.preconditions || null,
          tc.steps || null,
          tc.expected || null,
          tc.data || null,
          tc.verified_from || null,
          tc.tags || null,
          tc.maestro_yaml || null,
          tc.default_status || "Pending Review",
          tc.status || "Pending Review",
          tc.comments || null,
          tc.source || "generated",
        ]
      );
    }
    await client.query("COMMIT");
    res.json({ ok: true, restored_from: id });
  } catch (e) {
    await client.query("ROLLBACK").catch(() => {});
    next(e);
  } finally {
    client.release();
  }
});

async function takeSnapshot(label) {
  const [tcs, meta, runs, bugs] = await Promise.all([
    pool.query("SELECT * FROM qa.test_catalog ORDER BY tc_id"),
    pool.query("SELECT * FROM qa.catalog_meta WHERE id = 1"),
    pool.query("SELECT * FROM qa.run_results"),
    pool.query("SELECT * FROM qa.bugs"),
  ]);
  const payload = {
    taken_at: new Date().toISOString(),
    test_cases: tcs.rows,
    meta: meta.rows[0] || null,
    run_results: runs.rows,
    bugs: bugs.rows,
  };
  const { rows } = await pool.query(
    "INSERT INTO qa.catalog_snapshots (label, payload) VALUES ($1, $2) RETURNING id",
    [label, payload]
  );
  return rows[0].id;
}

module.exports = router;
