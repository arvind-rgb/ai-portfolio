/**
 * upload-maestro-bundle.js
 *   1. Tars ~/.claude/skills/_bhookle-test-state/maestro/ → /tmp/maestro-<ts>.tar.gz
 *   2. Calls BugBhook POST /api/maestro-bundle/sign-upload to get a signed URL
 *   3. PUT the tarball to Storage
 *   4. POST /api/maestro-bundle to record the upload + mark active
 *
 * Auth: X-CLI-Token (matches QA_CLI_TOKEN env on the BE).
 *
 * Usage:  node scripts/upload-maestro-bundle.js
 *         API_BASE override:  QA_API_BASE=... node scripts/upload-maestro-bundle.js
 */

require("dotenv").config();
const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");
const { execSync } = require("child_process");

const API_BASE =
  process.env.QA_API_BASE ||
  "https://<region>-<your-project>.cloudfunctions.net/bhookleQaBackend";
const CLI_TOKEN = process.env.QA_CLI_TOKEN;
if (!CLI_TOKEN) {
  console.error("QA_CLI_TOKEN env required (copy from BhookleQaBackend/.env)");
  process.exit(1);
}

const SRC = process.env.MAESTRO_SRC
  || path.join(os.homedir(), ".claude/skills/_bhookle-test-state/maestro");

async function authedFetch(p, opts = {}) {
  const headers = Object.assign({}, opts.headers || {}, { "X-CLI-Token": CLI_TOKEN });
  if (opts.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  return fetch(API_BASE + p, Object.assign({}, opts, { headers }));
}

(async function main() {
  if (!fs.existsSync(SRC)) {
    console.error(`[upload-maestro] source dir not found: ${SRC}`);
    process.exit(1);
  }

  // 1. Tar the maestro dir.
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const out = path.join(os.tmpdir(), `maestro-${ts}.tar.gz`);
  // Tar the CONTENTS of SRC (not the dir) so files land flat after extract:
  // flows/TC-*.yaml, flows/subflows/, flows/config.yaml — which run-shard.sh
  // expects (it does `cd flows; ls TC-*.yaml`).
  console.log(`[upload-maestro] tarring contents of ${SRC} → ${out}`);
  execSync(`tar -czf "${out}" -C "${SRC}" .`, { stdio: "inherit" });
  const buf = fs.readFileSync(out);
  const size = buf.length;
  const sha256 = crypto.createHash("sha256").update(buf).digest("hex");
  console.log(`[upload-maestro] tarball: ${size} bytes, sha256=${sha256.slice(0, 16)}…`);

  // 2. Sign upload.
  console.log(`[upload-maestro] requesting signed URL…`);
  let r = await authedFetch("/api/maestro-bundle/sign-upload", {
    method: "POST",
    body: JSON.stringify({ size_bytes: size }),
  });
  if (!r.ok) {
    console.error("[upload-maestro] sign-upload failed:", r.status, await r.text());
    process.exit(1);
  }
  const { signed_url, storage_path, version } = await r.json();

  // 3. PUT to Storage.
  console.log(`[upload-maestro] PUT → ${storage_path}`);
  r = await fetch(signed_url, {
    method: "PUT",
    headers: { "Content-Type": "application/gzip" },
    body: buf,
  });
  if (!r.ok) {
    console.error("[upload-maestro] Storage PUT failed:", r.status, await r.text());
    process.exit(1);
  }

  // 4. Record + activate.
  r = await authedFetch("/api/maestro-bundle", {
    method: "POST",
    body: JSON.stringify({ version, storage_path, size_bytes: size, sha256 }),
  });
  if (!r.ok) {
    console.error("[upload-maestro] record failed:", r.status, await r.text());
    process.exit(1);
  }
  const result = await r.json();
  console.log(`[upload-maestro] DONE ✓  id=${result.id}  version=${result.version}`);
  fs.unlinkSync(out);
})();
