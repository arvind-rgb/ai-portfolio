/**
 * upload-build.js — upload an app build (APK / iOS tarball) to BugBhook.
 *   1. POST /api/builds/sign-upload  -> signed PUT URL + storage_path
 *   2. PUT the file bytes to Storage
 *   3. POST /api/builds              -> records the row, returns its id
 *
 * Auth: X-CLI-Token (matches QA_CLI_TOKEN on the BE).
 *
 * Usage:
 *   node scripts/upload-build.js <android|ios> <path-to-file> [label]
 *   e.g. node scripts/upload-build.js android ~/Downloads/sit-android.apk "testid-2026-06-09"
 *
 * Prints the build id (use it as android_build_id / ios_build_id in /api/runs/trigger).
 */
require("dotenv").config();
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const API_BASE =
  process.env.QA_API_BASE ||
  "https://<region>-<your-project>.cloudfunctions.net/bhookleQaBackend";
const CLI_TOKEN = process.env.QA_CLI_TOKEN;
if (!CLI_TOKEN) {
  console.error("QA_CLI_TOKEN env required (copy from BhookleQaBackend/.env)");
  process.exit(1);
}

const platform = process.argv[2];
const filePath = process.argv[3];
const label = process.argv[4] || null;
if (!["android", "ios"].includes(platform) || !filePath) {
  console.error("usage: node scripts/upload-build.js <android|ios> <file> [label]");
  process.exit(1);
}
const abs = filePath.replace(/^~/, require("os").homedir());
if (!fs.existsSync(abs)) {
  console.error(`file not found: ${abs}`);
  process.exit(1);
}

async function authedFetch(p, opts = {}) {
  const headers = Object.assign({}, opts.headers || {}, { "X-CLI-Token": CLI_TOKEN });
  if (opts.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  return fetch(API_BASE + p, Object.assign({}, opts, { headers }));
}

(async function main() {
  const buf = fs.readFileSync(abs);
  const size = buf.length;
  const sha256 = crypto.createHash("sha256").update(buf).digest("hex");
  const filename = path.basename(abs);
  const contentType =
    platform === "android"
      ? "application/vnd.android.package-archive"
      : "application/gzip";
  console.log(`[upload-build] ${platform} ${filename} (${size} bytes, sha256=${sha256.slice(0, 16)}…)`);

  // 1. sign
  let r = await authedFetch("/api/builds/sign-upload", {
    method: "POST",
    body: JSON.stringify({ platform, filename, size_bytes: size }),
  });
  if (!r.ok) { console.error("sign-upload failed:", r.status, await r.text()); process.exit(1); }
  const { signed_url, storage_path } = await r.json();

  // 2. PUT
  console.log(`[upload-build] PUT → ${storage_path}`);
  r = await fetch(signed_url, { method: "PUT", headers: { "Content-Type": contentType }, body: buf });
  if (!r.ok) { console.error("Storage PUT failed:", r.status, await r.text()); process.exit(1); }

  // 3. record
  r = await authedFetch("/api/builds", {
    method: "POST",
    body: JSON.stringify({ platform, label, storage_path, size_bytes: size, sha256 }),
  });
  if (!r.ok) { console.error("record failed:", r.status, await r.text()); process.exit(1); }
  const out = await r.json();
  console.log(`[upload-build] DONE ✓  build_id=${out.id}  uploaded_at=${out.uploaded_at}`);
  console.log(`BUILD_ID=${out.id}`);
})();
