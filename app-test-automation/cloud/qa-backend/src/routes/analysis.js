/**
 * /api/analysis — Skill 1 (test-scan-app) output store.
 *
 *   GET  /  → latest analysis row (markdown + html + meta)
 *   POST /  → upsert a new analysis (called by upload-analysis.js after a scan)
 *   GET  /history → list previous analyses (id + commit + scanned_at)
 *
 * The HTML rendered in the dashboard's "Visual Journey Map" section comes
 * from journey_flow_html — served as text and dropped into an <iframe srcdoc>.
 */

const express = require("express");
const pool = require("../../config/postgresql");

const router = express.Router();

router.get("/", async (_req, res, next) => {
  try {
    const { rows } = await pool.query(
      `SELECT id, app_commit, scan_version, app_dir,
              screen_flow_md, user_flow_md, journey_flow_html,
              meta, screens_count, journeys_count,
              scanned_at, uploaded_at
         FROM qa.app_analysis
        ORDER BY uploaded_at DESC
        LIMIT 1`
    );
    if (!rows[0]) return res.json({ analysis: null });
    res.json({ analysis: rows[0] });
  } catch (e) {
    next(e);
  }
});

router.get("/history", async (_req, res, next) => {
  try {
    const { rows } = await pool.query(
      `SELECT id, app_commit, scan_version, screens_count, journeys_count,
              scanned_at, uploaded_at
         FROM qa.app_analysis
        ORDER BY uploaded_at DESC
        LIMIT 20`
    );
    res.json(rows);
  } catch (e) {
    next(e);
  }
});

router.post("/", async (req, res, next) => {
  const b = req.body || {};
  if (!b.screen_flow_md || !b.journey_flow_html) {
    return res.status(400).json({
      error: "screen_flow_md and journey_flow_html are required",
    });
  }
  try {
    const { rows } = await pool.query(
      `INSERT INTO qa.app_analysis
         (app_commit, scan_version, app_dir,
          screen_flow_md, user_flow_md, journey_flow_html,
          meta, screens_count, journeys_count, scanned_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
       RETURNING id, uploaded_at`,
      [
        b.app_commit || null,
        b.scan_version || null,
        b.app_dir || null,
        b.screen_flow_md,
        b.user_flow_md || null,
        b.journey_flow_html,
        b.meta || null,
        b.screens_count || null,
        b.journeys_count || null,
        b.scanned_at || null,
      ]
    );
    res.json({ ok: true, id: rows[0].id, uploaded_at: rows[0].uploaded_at });
  } catch (e) {
    next(e);
  }
});

module.exports = router;
