/**
 * /api/runs — Skill 3 (run-auto-test) orchestration.
 *
 *   GET  /                 → list recent runs
 *   GET  /:id              → run detail (shards, summary, results count)
 *   POST /trigger          → start a new run: creates qa.test_runs row,
 *                            mints HMAC callback token + signed URLs,
 *                            optionally fires GitHub workflow_dispatch.
 *   GET  /:id/manifest     → list of tc_id + maestro_yaml to run (called by CI)
 *
 * The shard-result + finalize routes live in callback.js (mounted at
 * /api/runs/:id/shard/... and /api/runs/:id/finalize) so they can use a
 * different auth (HMAC token instead of Firebase ID token).
 */

const express = require("express");
const admin = require("firebase-admin");
const pool = require("../../config/postgresql");
const callbackToken = require("../lib/callback-token");

const router = express.Router();

const SHARDS_PER_PLATFORM = 1;

// ── GET /api/runs — list recent ─────────────────────────────
router.get("/", async (_req, res, next) => {
  try {
    const { rows } = await pool.query(
      `SELECT id, label, status, started_at, finished_at, summary, created_at,
              android_build_id, ios_build_id, gh_run_url
         FROM qa.test_runs
        ORDER BY created_at DESC
        LIMIT 50`
    );
    res.json(rows);
  } catch (e) {
    next(e);
  }
});

// ── GET /api/runs/:id — full run detail ─────────────────────
// One request returns everything the dashboard needs for live + history view.
router.get("/:id", async (req, res, next) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (!Number.isFinite(id)) return res.status(400).json({ error: "bad id" });

    const [run, shards, counts, results, bugs] = await Promise.all([
      pool.query(
        `SELECT id, label, status, started_at, finished_at, summary,
                android_build_id, ios_build_id, gh_run_url, report_dir,
                created_at, triggered_by
           FROM qa.test_runs WHERE id = $1`,
        [id]
      ),
      pool.query(
        `SELECT id, platform, shard_index, shard_total, status,
                started_at, finished_at, passed, failed, skipped, log_excerpt
           FROM qa.run_shards
          WHERE run_id = $1
          ORDER BY platform, shard_index`,
        [id]
      ),
      pool.query(
        `SELECT COUNT(*)::int AS total,
                SUM(CASE WHEN status = 'PASS'    THEN 1 ELSE 0 END)::int AS pass,
                SUM(CASE WHEN status = 'FAIL'    THEN 1 ELSE 0 END)::int AS fail,
                SUM(CASE WHEN status = 'SKIPPED' THEN 1 ELSE 0 END)::int AS skipped
           FROM qa.run_results WHERE run_id = $1`,
        [id]
      ),
      pool.query(
        `SELECT r.tc_id, r.platform, r.status, r.duration_s, r.log_excerpt,
                t.screen, t.priority, t.title
           FROM qa.run_results r
           LEFT JOIN qa.test_catalog t ON t.tc_id = r.tc_id
          WHERE r.run_id = $1
          ORDER BY t.screen NULLS LAST, r.tc_id, r.platform`,
        [id]
      ),
      pool.query(
        `SELECT b.id, b.bug_id, b.tc_id, b.severity, b.summary, b.platform,
                b.platform_diff_flag, b.occurrence_count, b.screenshot_url,
                b.first_seen_run_id, b.last_seen_run_id, b.reported_at,
                t.screen, t.title
           FROM qa.bugs b
           LEFT JOIN qa.test_catalog t ON t.tc_id = b.tc_id
          WHERE b.run_id = $1
             OR b.id IN (SELECT bug_id FROM qa.bug_occurrences WHERE run_id = $1)
          ORDER BY
            CASE b.severity WHEN 'blocker' THEN 0 WHEN 'high' THEN 1
                            WHEN 'medium'  THEN 2 ELSE 3 END,
            t.screen, b.tc_id`,
        [id]
      ),
    ]);

    if (!run.rows[0]) return res.status(404).json({ error: "not found" });
    res.json({
      run: run.rows[0],
      shards: shards.rows,
      result_counts: counts.rows[0],
      results: results.rows,
      bugs: bugs.rows,
    });
  } catch (e) {
    next(e);
  }
});

// ── GET /api/runs/:id/manifest — TCs to run ─────────────────
// Called by CI before each shard starts. Returns the ordered list of
// (tc_id, maestro_yaml) for Approved TCs. The shard takes its slice via
// `maestro test --shard-split N --shard-index I`.
router.get("/:id/manifest", async (req, res, next) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (!Number.isFinite(id)) return res.status(400).json({ error: "bad id" });
    // Confirm the run exists (browser-token-callers will already be authed,
    // but a 404 helps surface bad ids early).
    const { rows: runRows } = await pool.query(
      "SELECT id FROM qa.test_runs WHERE id = $1",
      [id]
    );
    if (!runRows[0]) return res.status(404).json({ error: "run not found" });

    const { rows } = await pool.query(
      `SELECT tc_id, maestro_yaml, screen, priority
         FROM qa.test_catalog
        WHERE status = 'Approved' AND maestro_yaml IS NOT NULL
        ORDER BY tc_id`
    );
    res.json({
      shards_per_platform: SHARDS_PER_PLATFORM,
      total: rows.length,
      tcs: rows,
    });
  } catch (e) {
    next(e);
  }
});

// ── POST /api/runs/trigger — start a new run ────────────────
router.post("/trigger", async (req, res, next) => {
  const client = await pool.connect();
  try {
    const { android_build_id, ios_build_id, label } = req.body || {};
    if (!android_build_id && !ios_build_id) {
      return res.status(400).json({
        error: "at least one of android_build_id / ios_build_id is required",
      });
    }

    // Verify the build rows exist and platforms match.
    const buildIds = [android_build_id, ios_build_id].filter(Boolean);
    const { rows: builds } = await client.query(
      "SELECT id, platform, storage_path FROM qa.builds WHERE id = ANY($1::bigint[])",
      [buildIds]
    );
    const byPlat = {};
    for (const b of builds) byPlat[b.platform] = b;
    if (android_build_id && !byPlat.android) {
      return res.status(400).json({ error: "android_build_id not found or not android" });
    }
    if (ios_build_id && !byPlat.ios) {
      return res.status(400).json({ error: "ios_build_id not found or not ios" });
    }

    await client.query("BEGIN");

    // 1. Create the run row.
    const ins = await client.query(
      `INSERT INTO qa.test_runs
         (label, status, android_build_id, ios_build_id, triggered_by, started_at)
       VALUES ($1, 'queued', $2, $3, $4, NOW())
       RETURNING id, created_at`,
      [
        label || null,
        android_build_id || null,
        ios_build_id || null,
        (req.user && req.user.email) || null,
      ]
    );
    const runId = ins.rows[0].id;

    // 2. Pre-seed shard rows so the dashboard can render the grid immediately.
    for (const platform of ["android", "ios"]) {
      if (!byPlat[platform]) continue;
      for (let i = 0; i < SHARDS_PER_PLATFORM; i++) {
        await client.query(
          `INSERT INTO qa.run_shards (run_id, platform, shard_index, shard_total)
           VALUES ($1, $2, $3, $4)`,
          [runId, platform, i, SHARDS_PER_PLATFORM]
        );
      }
    }

    // 3. Mint a callback token bound to this run, persist its hash.
    const { token, hash, expires_at } = callbackToken.issue(runId);
    await client.query(
      "UPDATE qa.test_runs SET callback_token_hash = $1 WHERE id = $2",
      [hash, runId]
    );

    // 4. Mint signed download URLs for the builds + the active Maestro bundle.
    const bucket = admin.storage().bucket();
    const signedUrls = {};
    for (const platform of ["android", "ios"]) {
      const b = byPlat[platform];
      if (!b) continue;
      const [url] = await bucket.file(b.storage_path).getSignedUrl({
        version: "v4",
        action: "read",
        expires: Date.now() + 90 * 60 * 1000, // matches token TTL
      });
      signedUrls[platform] = url;
    }
    const { rows: maestroRows } = await client.query(
      `SELECT storage_path FROM qa.maestro_bundles
       WHERE is_active = TRUE ORDER BY uploaded_at DESC LIMIT 1`
    );
    let maestroUrl = null;
    if (maestroRows[0]) {
      const [url] = await bucket.file(maestroRows[0].storage_path).getSignedUrl({
        version: "v4",
        action: "read",
        expires: Date.now() + 90 * 60 * 1000,
      });
      maestroUrl = url;
    }

    await client.query("COMMIT");

    // 5. Optionally fire GitHub workflow_dispatch.
    // STUBBED until the CI repo is reviewed + approved. If GH_PAT_DISPATCH is
    // missing we just create the run row and return — the dashboard reflects
    // 'queued' state, and we can manually trigger or wire this later.
    let dispatch = { stubbed: true, reason: "GH_PAT_DISPATCH not set" };
    if (process.env.GH_PAT_DISPATCH && process.env.GH_OWNER && process.env.GH_REPO) {
      // Real call goes here once the repo is approved. Body shape stays the
      // same so this is a one-line flip when we're ready.
      dispatch = await dispatchGithub({
        runId,
        signedUrls,
        maestroUrl,
        callbackUrl: process.env.CALLBACK_BASE_URL || "",
        callbackToken: token,
      });
    }

    res.json({
      ok: true,
      run_id: runId,
      created_at: ins.rows[0].created_at,
      callback_token_expires_at: expires_at,
      maestro_bundle_present: !!maestroUrl,
      dispatch,
    });
  } catch (e) {
    await client.query("ROLLBACK").catch(() => {});
    next(e);
  } finally {
    client.release();
  }
});

async function dispatchGithub({ runId, signedUrls, maestroUrl, callbackUrl, callbackToken }) {
  // Implemented post repo-approval. Returns { dispatched: true, gh_run_url? }.
  // We don't try to fetch the run_id back from GitHub (the dispatch API doesn't
  // return one); we discover it via the first callback the shard makes.
  const url = `https://api.github.com/repos/${process.env.GH_OWNER}/${process.env.GH_REPO}/actions/workflows/${process.env.GH_WORKFLOW_FILE || "run-suite.yml"}/dispatches`;
  const body = JSON.stringify({
    ref: process.env.GH_REF || "main",
    inputs: {
      run_id: String(runId),
      apk_url: signedUrls.android || "",
      app_tar_url: signedUrls.ios || "",
      maestro_bundle_url: maestroUrl || "",
      callback_url: callbackUrl,
      callback_token: callbackToken,
    },
  });
  const r = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.GH_PAT_DISPATCH}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
    },
    body,
  });
  if (!r.ok) {
    const text = await r.text();
    return { dispatched: false, status: r.status, error: text.slice(0, 400) };
  }
  return { dispatched: true };
}

module.exports = router;
