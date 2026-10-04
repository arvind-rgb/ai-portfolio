/**
 * upload-analysis.js — push the local test-scan-app output to qa.app_analysis.
 *
 * Reads ~/.claude/skills/_bhookle-test-state/flows/{screen-flow.md,user-flow.md,journey-flow.html,.meta.json}
 * and writes a new row to qa.app_analysis directly via pg (so it doesn't need
 * the BE to be live).
 *
 * Usage:  node scripts/upload-analysis.js
 *         node scripts/upload-analysis.js /path/to/flows-dir
 */

require("dotenv").config();
const fs = require("fs");
const path = require("path");
const os = require("os");
const pool = require("../config/postgresql");

const DEFAULT_DIR = path.join(
  os.homedir(),
  ".claude/skills/_bhookle-test-state/flows"
);

(async function main() {
  const dir = process.argv[2] || DEFAULT_DIR;
  const screen = path.join(dir, "screen-flow.md");
  const user = path.join(dir, "user-flow.md");
  const journey = path.join(dir, "journey-flow.html");
  const metaPath = path.join(dir, ".meta.json");

  for (const f of [screen, user, journey]) {
    if (!fs.existsSync(f)) {
      console.error("[upload-analysis] missing file:", f);
      process.exit(1);
    }
  }

  const screen_flow_md = fs.readFileSync(screen, "utf8");
  const user_flow_md = fs.readFileSync(user, "utf8");
  const journey_flow_html = fs.readFileSync(journey, "utf8");
  const meta = fs.existsSync(metaPath)
    ? JSON.parse(fs.readFileSync(metaPath, "utf8"))
    : {};

  const client = await pool.connect();
  try {
    console.log("[upload-analysis] target db:", process.env.POSTGRESQL_DATABASE);
    const { rows } = await client.query(
      `INSERT INTO qa.app_analysis
         (app_commit, scan_version, app_dir,
          screen_flow_md, user_flow_md, journey_flow_html,
          meta, screens_count, journeys_count, scanned_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
       RETURNING id, uploaded_at`,
      [
        meta.app_commit || null,
        meta.version || null,
        meta.app_dir || null,
        screen_flow_md,
        user_flow_md,
        journey_flow_html,
        meta,
        meta.counts ? meta.counts.screens : null,
        meta.counts ? meta.counts.journeys : null,
        meta.generated_at || null,
      ]
    );
    console.log(
      `[upload-analysis] DONE ✓  id=${rows[0].id}  uploaded_at=${rows[0].uploaded_at}`
    );
  } catch (e) {
    console.error("[upload-analysis] FAILED:", e.message);
    process.exitCode = 1;
  } finally {
    client.release();
    await pool.end();
  }
})();
