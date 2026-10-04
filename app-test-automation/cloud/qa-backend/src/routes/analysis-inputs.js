/**
 * /api/analysis/inputs — reference uploads (PDFs, screenshots) attached to
 * the next test-scan-app run.
 *
 *   GET    /             → list (no file_data — just metadata)
 *   POST   /             → upload (JSON: { filename, mime_type, kind, base64, note? })
 *   GET    /:id/download → returns the file bytes
 *   DELETE /:id          → remove
 *
 * 5 MB cap per file (enforced server-side). Files live as BYTEA inline
 * in qa.app_analysis_inputs — small enough for a couple dozen PDFs/PNGs.
 */

const express = require("express");
const pool = require("../../config/postgresql");

const router = express.Router();
const MAX_BYTES = 5 * 1024 * 1024;
const ALLOWED_KINDS = new Set(["pdf", "screenshot", "other"]);

router.get("/", async (_req, res, next) => {
  try {
    const { rows } = await pool.query(
      `SELECT id, kind, filename, mime_type, size_bytes, note,
              uploaded_at, uploaded_by
         FROM qa.app_analysis_inputs
        ORDER BY uploaded_at DESC`
    );
    res.json(rows);
  } catch (e) {
    next(e);
  }
});

router.post("/", async (req, res, next) => {
  const b = req.body || {};
  const { filename, mime_type, kind, base64, note } = b;
  if (!filename || !mime_type || !kind || !base64) {
    return res.status(400).json({
      error: "filename, mime_type, kind, and base64 are required",
    });
  }
  if (!ALLOWED_KINDS.has(kind)) {
    return res.status(400).json({
      error: `kind must be one of ${[...ALLOWED_KINDS].join(", ")}`,
    });
  }

  let buf;
  try {
    buf = Buffer.from(base64, "base64");
  } catch (e) {
    return res.status(400).json({ error: "invalid base64 payload" });
  }
  if (buf.length === 0) {
    return res.status(400).json({ error: "empty file" });
  }
  if (buf.length > MAX_BYTES) {
    return res.status(413).json({
      error: `file too large (${buf.length} bytes; max ${MAX_BYTES})`,
    });
  }

  try {
    const { rows } = await pool.query(
      `INSERT INTO qa.app_analysis_inputs
         (kind, filename, mime_type, size_bytes, file_data, note, uploaded_by)
       VALUES ($1,$2,$3,$4,$5,$6,$7)
       RETURNING id, uploaded_at`,
      [
        kind,
        filename,
        mime_type,
        buf.length,
        buf,
        note || null,
        (req.user && req.user.email) || null,
      ]
    );
    res.json({ ok: true, id: rows[0].id, uploaded_at: rows[0].uploaded_at });
  } catch (e) {
    next(e);
  }
});

router.get("/:id/download", async (req, res, next) => {
  const id = parseInt(req.params.id, 10);
  if (!Number.isFinite(id)) {
    return res.status(400).json({ error: "bad id" });
  }
  try {
    const { rows } = await pool.query(
      "SELECT filename, mime_type, file_data FROM qa.app_analysis_inputs WHERE id = $1",
      [id]
    );
    if (!rows[0]) return res.status(404).json({ error: "not found" });
    res.set("Content-Type", rows[0].mime_type);
    res.set(
      "Content-Disposition",
      `inline; filename="${rows[0].filename.replace(/"/g, "")}"`
    );
    res.send(rows[0].file_data);
  } catch (e) {
    next(e);
  }
});

router.delete("/:id", async (req, res, next) => {
  const id = parseInt(req.params.id, 10);
  if (!Number.isFinite(id)) {
    return res.status(400).json({ error: "bad id" });
  }
  try {
    const r = await pool.query(
      "DELETE FROM qa.app_analysis_inputs WHERE id = $1",
      [id]
    );
    if (r.rowCount === 0) return res.status(404).json({ error: "not found" });
    res.json({ ok: true, deleted: id });
  } catch (e) {
    next(e);
  }
});

module.exports = router;
