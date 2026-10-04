/**
 * /api/tcs — single-TC CRUD. The "+ New TC" form posts here.
 *
 *   POST /         → create a new TC (manual). Auto-assigns tc_id from screen prefix.
 *   PUT  /:tc_id   → partial update of any field on a single TC.
 *
 * All queries fully qualify qa.test_catalog.
 */

const express = require("express");
const pool = require("../../config/postgresql");

const router = express.Router();

const ALLOWED_FIELDS = [
  "screen",
  "journey",
  "title",
  "description",
  "priority",
  "type",
  "category",
  "platform",
  "preconditions",
  "steps",
  "expected",
  "data",
  "verified_from",
  "tags",
  "maestro_yaml",
  "default_status",
  "status",
  "comments",
];

// ── POST /api/tcs — manual create ────────────────────────────
router.post("/", async (req, res, next) => {
  const b = req.body || {};
  if (!b.screen || !b.title) {
    return res
      .status(400)
      .json({ error: "screen and title are required" });
  }

  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const tc_id = await nextTcIdForScreen(client, b.screen);

    const row = {
      tc_id,
      screen: b.screen,
      journey: b.journey || null,
      title: b.title,
      description: b.description || null,
      priority: b.priority || "P2",
      type: b.type || "extra",
      category: b.category || "functional",
      platform: b.platform || "Both",
      preconditions: b.preconditions || null,
      steps: b.steps || null,
      expected: b.expected || null,
      data: b.data || null,
      verified_from: b.verified_from || "manual",
      tags: b.tags || null,
      maestro_yaml: null,
      default_status: "Approved",
      status: b.status || "Approved",
      comments: b.comments || null,
      source: "manual",
    };

    await client.query(
      `INSERT INTO qa.test_catalog
         (tc_id, screen, journey, title, description, priority, type, category,
          platform, preconditions, steps, expected, data, verified_from, tags,
          maestro_yaml, default_status, status, comments, source)
       VALUES
         ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)`,
      [
        row.tc_id,
        row.screen,
        row.journey,
        row.title,
        row.description,
        row.priority,
        row.type,
        row.category,
        row.platform,
        row.preconditions,
        row.steps,
        row.expected,
        row.data,
        row.verified_from,
        row.tags,
        row.maestro_yaml,
        row.default_status,
        row.status,
        row.comments,
        row.source,
      ]
    );

    await client.query(
      `INSERT INTO qa.catalog_meta (id, last_written_at)
       VALUES (1, NOW())
       ON CONFLICT (id) DO UPDATE SET last_written_at = NOW()`
    );

    await client.query("COMMIT");
    const { rows } = await pool.query(
      "SELECT * FROM qa.test_catalog WHERE tc_id = $1",
      [tc_id]
    );
    res.json({ ok: true, tc: rows[0] });
  } catch (e) {
    await client.query("ROLLBACK").catch(() => {});
    next(e);
  } finally {
    client.release();
  }
});

// ── PUT /api/tcs/:tc_id — partial update ────────────────────
router.put("/:tc_id", async (req, res, next) => {
  const id = req.params.tc_id;
  const b = req.body || {};
  const sets = [];
  const vals = [];
  let i = 1;
  for (const k of ALLOWED_FIELDS) {
    if (k in b) {
      sets.push(`${k} = $${++i}`);
      vals.push(b[k]);
    }
  }
  if (sets.length === 0) {
    return res.status(400).json({ error: "no editable fields supplied" });
  }
  try {
    const sql = `UPDATE qa.test_catalog
                    SET ${sets.join(", ")}, updated_at = NOW()
                  WHERE tc_id = $1
              RETURNING *`;
    const { rows } = await pool.query(sql, [id, ...vals]);
    if (!rows[0]) return res.status(404).json({ error: "tc not found" });
    res.json({ ok: true, tc: rows[0] });
  } catch (e) {
    next(e);
  }
});

// ── helpers ─────────────────────────────────────────────────

// Build a sensible 4-letter prefix from a screen name. We use the same prefixes
// the generator uses (BOOT, LGN, OTP, CART, etc.) by reading existing TCs for the
// screen and reusing their prefix. If none exist, derive one from the screen text.
async function nextTcIdForScreen(client, screen) {
  const { rows } = await client.query(
    `SELECT tc_id FROM qa.test_catalog
      WHERE screen = $1 AND tc_id ~ '^TC-[A-Z0-9]+-[0-9]+$'`,
    [screen]
  );
  let prefix = null;
  let maxN = 0;
  for (const r of rows) {
    const m = r.tc_id.match(/^TC-([A-Z0-9]+)-(\d+)$/);
    if (!m) continue;
    if (!prefix) prefix = m[1];
    const n = parseInt(m[2], 10);
    if (n > maxN) maxN = n;
  }
  if (!prefix) {
    prefix = derivePrefix(screen);
    // Check global collisions on derived prefix
    const { rows: globalRows } = await client.query(
      "SELECT MAX(CAST(SUBSTRING(tc_id FROM '\\d+$') AS INT)) AS m FROM qa.test_catalog WHERE tc_id LIKE $1",
      [`TC-${prefix}-%`]
    );
    if (globalRows[0] && globalRows[0].m) maxN = globalRows[0].m;
  }
  const n = String(maxN + 1).padStart(3, "0");
  return `TC-${prefix}-${n}`;
}

function derivePrefix(screen) {
  const letters = String(screen)
    .replace(/[^A-Za-z]/g, "")
    .toUpperCase();
  return letters.slice(0, 4) || "MAN";
}

module.exports = router;
