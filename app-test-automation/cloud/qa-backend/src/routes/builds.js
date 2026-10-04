/**
 * /api/builds — Skill 3 (run-auto-test) app-build uploads.
 *
 *   POST /sign-upload   → mints a 15-min Firebase Storage signed PUT URL.
 *   POST /              → records an upload in qa.builds AFTER the browser confirms.
 *   GET  /              → lists recent builds (newest first, per platform).
 *
 * Storage paths are ALWAYS rooted at `qa/builds/<uuid><ext>` — never anywhere
 * else. Production paths like `prod/dish_images/...` on the same bucket
 * (`<your-project>.appspot.com`) are out of reach. See memory:
 * firebase-storage-production-use.
 *
 * Auth: handled by the parent /api requireAuth middleware (Firebase ID token
 * for browser uploads, or X-CLI-Token for CLI helpers).
 */

const express = require("express");
const crypto = require("crypto");
const admin = require("firebase-admin");
const pool = require("../../config/postgresql");

const router = express.Router();

const ALLOWED_PLATFORMS = new Set(["android", "ios"]);
const MAX_BUILD_BYTES = 200 * 1024 * 1024; // 200 MB hard cap

// Pick a safe extension based on platform; reject anything else so the
// storage_path is always predictable.
function extFor(platform, filename) {
  const lower = String(filename || "").toLowerCase();
  if (platform === "android") {
    if (lower.endsWith(".apk")) return ".apk";
    return null;
  }
  if (platform === "ios") {
    if (lower.endsWith(".app.tar.gz")) return ".app.tar.gz";
    if (lower.endsWith(".tar.gz")) return ".tar.gz";
    if (lower.endsWith(".zip")) return ".zip";
    return null;
  }
  return null;
}

function bucket() {
  // On Cloud Functions, default bucket auto-resolves to `<project>.appspot.com`.
  // Locally (`npm start`), this will throw unless GOOGLE_APPLICATION_CREDENTIALS
  // is set — we accept that, since live runs happen on Functions.
  return admin.storage().bucket();
}

// ── POST /api/builds/sign-upload ────────────────────────────
router.post("/sign-upload", async (req, res, next) => {
  try {
    const { platform, filename, size_bytes } = req.body || {};
    if (!ALLOWED_PLATFORMS.has(platform)) {
      return res.status(400).json({ error: "platform must be 'android' or 'ios'" });
    }
    const ext = extFor(platform, filename);
    if (!ext) {
      return res.status(400).json({
        error: platform === "android"
          ? "filename must end in .apk"
          : "iOS build must be .app.tar.gz, .tar.gz, or .zip (the .app is a directory; tar it first)",
      });
    }
    if (size_bytes && Number(size_bytes) > MAX_BUILD_BYTES) {
      return res.status(413).json({
        error: `build too large (${size_bytes} bytes; max ${MAX_BUILD_BYTES})`,
      });
    }

    const uuid = crypto.randomUUID();
    const storagePath = `qa/builds/${uuid}${ext}`;
    const expiresMs = Date.now() + 15 * 60 * 1000;

    const file = bucket().file(storagePath);
    const [url] = await file.getSignedUrl({
      version: "v4",
      action: "write",
      expires: expiresMs,
      contentType: platform === "android" ? "application/vnd.android.package-archive" : "application/gzip",
    });

    res.json({
      storage_path: storagePath,
      signed_url: url,
      expires_at: new Date(expiresMs).toISOString(),
      max_bytes: MAX_BUILD_BYTES,
    });
  } catch (e) {
    next(e);
  }
});

// ── POST /api/builds — record the upload ────────────────────
router.post("/", async (req, res, next) => {
  try {
    const { platform, label, storage_path, size_bytes, sha256 } = req.body || {};
    if (!ALLOWED_PLATFORMS.has(platform)) {
      return res.status(400).json({ error: "platform must be 'android' or 'ios'" });
    }
    if (!storage_path || !storage_path.startsWith("qa/builds/")) {
      return res.status(400).json({ error: "storage_path must start with qa/builds/" });
    }

    // Verify the object actually landed in Storage before we record it.
    // This stops fake metadata rows from being inserted.
    const file = bucket().file(storage_path);
    const [exists] = await file.exists();
    if (!exists) {
      return res.status(400).json({ error: "no object at storage_path — upload first" });
    }
    const [metadata] = await file.getMetadata();
    const verifiedSize = parseInt(metadata.size, 10) || null;
    if (verifiedSize && verifiedSize > MAX_BUILD_BYTES) {
      return res.status(413).json({
        error: `uploaded build exceeds cap (${verifiedSize} > ${MAX_BUILD_BYTES})`,
      });
    }

    const { rows } = await pool.query(
      `INSERT INTO qa.builds (platform, label, storage_path, size_bytes, sha256, uploaded_by)
       VALUES ($1,$2,$3,$4,$5,$6)
       RETURNING id, uploaded_at`,
      [
        platform,
        label || null,
        storage_path,
        verifiedSize || (size_bytes ? Number(size_bytes) : null),
        sha256 || null,
        (req.user && req.user.email) || null,
      ]
    );
    res.json({ ok: true, id: rows[0].id, uploaded_at: rows[0].uploaded_at });
  } catch (e) {
    next(e);
  }
});

// ── GET /api/builds — list recent builds ────────────────────
router.get("/", async (req, res, next) => {
  try {
    const platform = req.query.platform;
    const params = [];
    let where = "";
    if (platform && ALLOWED_PLATFORMS.has(platform)) {
      where = "WHERE platform = $1";
      params.push(platform);
    }
    const { rows } = await pool.query(
      `SELECT id, platform, label, storage_path, size_bytes, sha256, uploaded_by, uploaded_at
         FROM qa.builds ${where}
        ORDER BY uploaded_at DESC
        LIMIT 50`,
      params
    );
    res.json(rows);
  } catch (e) {
    next(e);
  }
});

// ── GET /api/builds/:id/signed-download ─────────────────────
// CI (via callback token) and the dashboard both need read URLs.
// We mint a fresh 30-min GET URL on demand.
router.get("/:id/signed-download", async (req, res, next) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (!Number.isFinite(id)) return res.status(400).json({ error: "bad id" });
    const { rows } = await pool.query(
      "SELECT storage_path, platform FROM qa.builds WHERE id = $1",
      [id]
    );
    if (!rows[0]) return res.status(404).json({ error: "not found" });
    const expiresMs = Date.now() + 30 * 60 * 1000;
    const [url] = await bucket()
      .file(rows[0].storage_path)
      .getSignedUrl({ version: "v4", action: "read", expires: expiresMs });
    res.json({ signed_url: url, expires_at: new Date(expiresMs).toISOString() });
  } catch (e) {
    next(e);
  }
});

module.exports = router;
