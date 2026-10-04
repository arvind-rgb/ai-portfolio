/**
 * /api/maestro-bundle — upload + register the tarball of Maestro flows.
 *
 *   POST /sign-upload  → 15-min signed PUT URL for qa/maestro-bundles/<uuid>.tar.gz
 *   POST /             → record (version, storage_path, sha256). Marks new row
 *                        active; deactivates all previous rows.
 *   GET  /             → list bundles (newest first)
 *
 * Auth: parent /api requireAuth (Firebase ID token OR X-CLI-Token).
 */

const express = require("express");
const crypto = require("crypto");
const admin = require("firebase-admin");
const pool = require("../../config/postgresql");

const router = express.Router();
const MAX_BYTES = 50 * 1024 * 1024;

function bucket() { return admin.storage().bucket(); }

router.post("/sign-upload", async (req, res, next) => {
  try {
    const { version, size_bytes } = req.body || {};
    if (size_bytes && Number(size_bytes) > MAX_BYTES) {
      return res.status(413).json({ error: `bundle too large (${size_bytes} > ${MAX_BYTES})` });
    }
    const uuid = crypto.randomUUID();
    const storagePath = `qa/maestro-bundles/${uuid}.tar.gz`;
    const expiresMs = Date.now() + 15 * 60 * 1000;
    const [url] = await bucket().file(storagePath).getSignedUrl({
      version: "v4", action: "write", expires: expiresMs,
      contentType: "application/gzip",
    });
    res.json({
      version: version || `v${Date.now()}`,
      storage_path: storagePath,
      signed_url: url,
      expires_at: new Date(expiresMs).toISOString(),
      max_bytes: MAX_BYTES,
    });
  } catch (e) { next(e); }
});

router.post("/", async (req, res, next) => {
  const client = await pool.connect();
  try {
    const { version, storage_path, size_bytes, sha256 } = req.body || {};
    if (!storage_path || !storage_path.startsWith("qa/maestro-bundles/")) {
      return res.status(400).json({ error: "storage_path must start with qa/maestro-bundles/" });
    }
    const file = bucket().file(storage_path);
    const [exists] = await file.exists();
    if (!exists) return res.status(400).json({ error: "no object at storage_path" });
    const [metadata] = await file.getMetadata();

    await client.query("BEGIN");
    // Deactivate any prior bundles so triggers always pick the newest.
    await client.query("UPDATE qa.maestro_bundles SET is_active = FALSE");
    const { rows } = await client.query(
      `INSERT INTO qa.maestro_bundles
         (version, storage_path, size_bytes, sha256, uploaded_by, is_active)
       VALUES ($1, $2, $3, $4, $5, TRUE)
       RETURNING id, uploaded_at, version`,
      [
        version || `v${Date.now()}`,
        storage_path,
        parseInt(metadata.size, 10) || (size_bytes ? Number(size_bytes) : null),
        sha256 || null,
        (req.user && req.user.email) || null,
      ]
    );
    await client.query("COMMIT");
    res.json({ ok: true, ...rows[0] });
  } catch (e) {
    await client.query("ROLLBACK").catch(() => {});
    next(e);
  } finally {
    client.release();
  }
});

// One-shot admin: append a CORS rule on the default bucket so the dashboard
// can PUT directly to signed Storage URLs. NEVER replaces existing rules —
// only appends. Preserved here (rather than a local script) because the
// Function auto-authenticates via its service account; running this from a
// dev machine would need ADC setup.
router.post("/_admin/set-cors", async (_req, res, next) => {
  try {
    const bucket = require("firebase-admin").storage().bucket();
    const [meta] = await bucket.getMetadata();
    const current = meta.cors || [];
    const ORIGINS = ["https://bhookle-qa.web.app", "http://localhost:7778"];
    const covers = current.some(
      (r) => Array.isArray(r.origin)
        && ORIGINS.every((o) => r.origin.includes(o))
        && (r.method || []).includes("PUT")
    );
    if (covers) {
      return res.json({ ok: true, action: "noop", current_rules_count: current.length });
    }
    const newRule = {
      origin: ORIGINS,
      method: ["GET", "HEAD", "PUT", "POST", "OPTIONS"],
      responseHeader: [
        "Content-Type", "Content-Disposition", "Content-Length",
        "Authorization", "x-goog-resumable", "x-goog-meta-*",
      ],
      maxAgeSeconds: 3600,
    };
    const merged = current.concat([newRule]);
    await bucket.setCorsConfiguration(merged);
    res.json({
      ok: true,
      action: "appended",
      before: current,
      after: merged,
    });
  } catch (e) { next(e); }
});

router.get("/", async (_req, res, next) => {
  try {
    const { rows } = await pool.query(
      `SELECT id, version, storage_path, size_bytes, sha256, uploaded_by,
              uploaded_at, is_active
         FROM qa.maestro_bundles
        ORDER BY uploaded_at DESC LIMIT 20`
    );
    res.json(rows);
  } catch (e) { next(e); }
});

module.exports = router;
