/**
 * /api/catalog — read + bulk save + status + lock/unlock.
 *
 * Mirrors the old serve.py contract so the FE swap is mechanical:
 *   GET  /         → { test_cases, meta, run_results, bugs, schema_version }
 *   POST /save     → bulk upsert of statuses/comments; preserves run_results + bugs server-side
 *   GET  /status   → summary { all_approved, locked, total, by_status, by_priority }
 *   POST /lock     → { ok, locked: true }
 *   POST /unlock   → { ok, locked: false }
 *
 * Every query fully qualifies the qa.* schema. No bare table names.
 */

const express = require("express");
const pool = require("../../config/postgresql");

const router = express.Router();

const APPROVED_STATUSES = new Set(["Approved", "Skip-Until-Flag-On"]);

// ── GET /api/catalog ────────────────────────────────────────
router.get("/", async (_req, res, next) => {
  try {
    const [tcs, meta, runs, bugs, analysis] = await Promise.all([
      pool.query(
        "SELECT * FROM qa.test_catalog ORDER BY screen, tc_id"
      ),
      pool.query("SELECT * FROM qa.catalog_meta WHERE id = 1"),
      pool.query(
        "SELECT * FROM qa.run_results ORDER BY ran_at DESC LIMIT 500"
      ),
      pool.query("SELECT * FROM qa.bugs ORDER BY reported_at DESC LIMIT 500"),
      // Latest scan: surface its self-critique into the ledger header.
      pool.query(
        `SELECT app_commit, scan_version, meta, screens_count, scanned_at
           FROM qa.app_analysis ORDER BY uploaded_at DESC LIMIT 1`
      ),
    ]);
    const a = analysis.rows[0] || {};
    const am = (a && a.meta) || {};
    const mergedMeta = Object.assign({}, meta.rows[0] || {}, {
      // Test-case-generator's self-critique = the latest scan's confidence_score (0-100).
      critique_score: am.confidence_score != null ? am.confidence_score : null,
      critique_basis: am.confidence_basis || null,
      app_commit: a.app_commit || null,
      scan_version: a.scan_version || null,
      screens_count: a.screens_count || null,
      scanned_at: a.scanned_at || null,
    });
    res.json({
      schema_version: (meta.rows[0] && meta.rows[0].schema_version) || "v2",
      meta: mergedMeta,
      test_cases: tcs.rows,
      run_results: runs.rows,
      bugs: bugs.rows,
    });
  } catch (e) {
    next(e);
  }
});

// ── POST /api/catalog/save ──────────────────────────────────
// Body: { test_cases: [ { tc_id, status, comments, ...optionally other fields } ], meta? }
// Server preserves run_results + bugs (we never touch them here).
router.post("/save", async (req, res, next) => {
  const body = req.body || {};
  const tcs = Array.isArray(body.test_cases) ? body.test_cases : null;
  if (!tcs) {
    return res.status(400).json({ error: "test_cases array required" });
  }

  const client = await pool.connect();
  try {
    await client.query("BEGIN");

    for (const t of tcs) {
      if (!t.tc_id) continue;
      // Update only the fields the dashboard edits inline.
      // For full TC field updates use PUT /api/tcs/:id.
      await client.query(
        `UPDATE qa.test_catalog
            SET status     = COALESCE($2, status),
                comments   = COALESCE($3, comments),
                updated_at = NOW()
          WHERE tc_id = $1`,
        [t.tc_id, t.status ?? null, t.comments ?? null]
      );
    }

    await client.query(
      `INSERT INTO qa.catalog_meta (id, last_written_at)
       VALUES (1, NOW())
       ON CONFLICT (id) DO UPDATE SET last_written_at = NOW()`
    );

    await client.query("COMMIT");

    const summary = await summariseStatus(client);
    res.json({ ok: true, summary });
  } catch (e) {
    await client.query("ROLLBACK").catch(() => {});
    next(e);
  } finally {
    client.release();
  }
});

// ── GET /api/catalog/status ─────────────────────────────────
router.get("/status", async (_req, res, next) => {
  try {
    const s = await summariseStatus(pool);
    res.json(s);
  } catch (e) {
    next(e);
  }
});

// ── POST /api/catalog/lock ──────────────────────────────────
router.post("/lock", async (_req, res, next) => {
  try {
    const s = await summariseStatus(pool);
    if (!s.all_approved) {
      return res.status(409).json({
        error: "cannot lock — not all TCs approved",
        summary: s,
      });
    }
    await pool.query(
      `INSERT INTO qa.catalog_meta (id, locked, locked_at)
       VALUES (1, TRUE, NOW())
       ON CONFLICT (id) DO UPDATE
         SET locked = TRUE, locked_at = NOW()`
    );
    res.json({ ok: true, locked: true });
  } catch (e) {
    next(e);
  }
});

// ── POST /api/catalog/unlock ────────────────────────────────
router.post("/unlock", async (_req, res, next) => {
  try {
    await pool.query(
      `INSERT INTO qa.catalog_meta (id, locked, locked_at)
       VALUES (1, FALSE, NULL)
       ON CONFLICT (id) DO UPDATE
         SET locked = FALSE, locked_at = NULL`
    );
    res.json({ ok: true, locked: false });
  } catch (e) {
    next(e);
  }
});

async function summariseStatus(c) {
  const [tot, byStatus, byPri, meta] = await Promise.all([
    c.query("SELECT COUNT(*)::int AS n FROM qa.test_catalog"),
    c.query(
      "SELECT COALESCE(status,'Pending Review') AS s, COUNT(*)::int AS n FROM qa.test_catalog GROUP BY s"
    ),
    c.query(
      "SELECT COALESCE(priority,'-') AS p, COUNT(*)::int AS n FROM qa.test_catalog GROUP BY p"
    ),
    c.query("SELECT locked FROM qa.catalog_meta WHERE id = 1"),
  ]);
  const by_status = {};
  for (const r of byStatus.rows) by_status[r.s] = r.n;
  const by_priority = {};
  for (const r of byPri.rows) by_priority[r.p] = r.n;
  const unapproved =
    tot.rows[0].n -
    Object.entries(by_status)
      .filter(([s]) => APPROVED_STATUSES.has(s))
      .reduce((a, [, n]) => a + n, 0);
  return {
    total: tot.rows[0].n,
    by_status,
    by_priority,
    all_approved: tot.rows[0].n > 0 && unapproved === 0,
    locked: !!(meta.rows[0] && meta.rows[0].locked),
  };
}

module.exports = router;
