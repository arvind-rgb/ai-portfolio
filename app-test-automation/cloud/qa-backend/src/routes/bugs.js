/**
 * /api/bugs — classified-bug listing + developer triage.
 *
 *   GET   /                 → bugs (dev-relevant by default; ?dev=0 for all)
 *   PATCH /:id/triage        → { status: accepted|rejected|open, note }
 *
 * Triage is the developer's verdict: "accepted" = genuine bug, "rejected" = not a
 * real bug / wrong flag. Rejecting propagates to all bugs with the same `signature`
 * so the next classification run auto-suppresses that signature (the learning loop —
 * see scripts/classify-bugs.js which inherits 'rejected' signatures).
 *
 * Auth: parent /api requireAuth (Firebase ID token for the dashboard).
 */
const express = require("express");
const pool = require("../../config/postgresql");
const router = express.Router();

const DEV_CLASSES = ["app-bug", "app-regression", "platform-divergence"];

router.get("/", async (req, res, next) => {
  try {
    const devOnly = req.query.dev !== "0";
    const params = [];
    let where = "";
    if (devOnly) { where = "WHERE bug_class = ANY($1)"; params.push(DEV_CLASSES); }
    const { rows } = await pool.query(
      `SELECT id, bug_id, tc_id, severity, summary, details, platform, bug_class,
              dev_guidance, recommended_fix, triage_status, triage_note, triage_by,
              triage_at, occurrence_count, first_seen_run_id, last_seen_run_id, signature
         FROM qa.bugs ${where}
        ORDER BY (triage_status = 'open') DESC,
                 array_position(ARRAY['high','medium','low','info'], COALESCE(severity,'low')),
                 last_seen_run_id DESC NULLS LAST`,
      params
    );
    res.json({ bugs: rows, dev_classes: DEV_CLASSES });
  } catch (e) { next(e); }
});

// GET /api/bugs/overview — build/run summary (per platform: build, TCs run, pass,
// fail, time taken, shards) + consolidated grade + fail-class breakdown.
router.get("/overview", async (req, res, next) => {
  try {
    // Aggregate per BUILD (not per run): a build summary should show the full
    // picture of how the app build performed, combining every run against it.
    // This treats #27 (main) + #29 (recovery) + ... as one logical pass.
    const out = { latest_run: { per_platform: {} } };
    const allRunIds = new Set();
    for (const platform of ["android", "ios"]) {
      const buildCol = platform === "android" ? "android_build_id" : "ios_build_id";
      // pick the latest build that actually got tested
      const latestBuild = (await pool.query(
        `SELECT t.${buildCol} bid
           FROM qa.test_runs t JOIN qa.run_results r ON r.run_id=t.id
          WHERE t.${buildCol} IS NOT NULL AND r.platform=$1 AND r.tc_id NOT IN ('TC-SMOKE-001','TC-WARMUP-001') AND r.tc_id<>'TC-WARMUP-001'
          ORDER BY t.id DESC LIMIT 1`, [platform])).rows[0];
      if (!latestBuild) continue;
      const bid = latestBuild.bid;
      // all runs of that build that produced results for this platform
      const runs = (await pool.query(
        `SELECT DISTINCT t.id FROM qa.test_runs t
           JOIN qa.run_results r ON r.run_id=t.id
          WHERE t.${buildCol}=$1 AND r.platform=$2`, [bid, platform])).rows.map(r => +r.id);
      runs.forEach(id => allRunIds.add(id));
      // BEST result per TC (consolidates across multiple runs of the same build)
      const g = (await pool.query(
        `WITH best AS (
           SELECT DISTINCT ON (tc_id) tc_id, status FROM qa.run_results
            WHERE run_id = ANY($1::bigint[]) AND platform=$2
              AND tc_id NOT IN ('TC-SMOKE-001','TC-WARMUP-001') AND tc_id<>'TC-WARMUP-001'
            ORDER BY tc_id, (status='PASS') DESC, ran_at DESC)
         SELECT count(*) ran, count(*) FILTER (WHERE status='PASS') pass,
                count(*) FILTER (WHERE status='FAIL') fail FROM best`,
        [runs, platform])).rows[0] || {};
      // Find the LARGEST (main) run — the one that graded the most TCs — and use
      // its duration + shard count as the headline reference (cumulative across
      // tiny recovery runs would be misleading).
      const byResults = (await pool.query(
        `SELECT run_id, count(*) n FROM qa.run_results
          WHERE run_id = ANY($1::bigint[]) AND platform=$2
          GROUP BY run_id ORDER BY n DESC LIMIT 1`, [runs, platform])).rows[0];
      const mainRunId = byResults ? +byResults.run_id : runs[0];
      const shard = (await pool.query(
        `SELECT count(DISTINCT shard_index) shards,
                EXTRACT(EPOCH FROM (max(finished_at)-min(started_at)))::int dur
           FROM qa.run_shards WHERE run_id=$1 AND platform=$2`,
        [mainRunId, platform])).rows[0] || {};
      out.latest_run.per_platform[platform] = {
        build_id: bid,
        runs: runs.sort((a,b)=>a-b),
        label: `build #${bid} across runs ${runs.sort((a,b)=>a-b).join(', ')}`,
        shards: +shard.shards || 0,
        duration_s: +shard.dur || 0,
        ran: +g.ran || 0, pass: +g.pass || 0, fail: +g.fail || 0,
      };
    }
    out.latest_run.run_ids = [...allRunIds].sort((a,b)=>a-b);
    // consolidated best-per-TC
    const cons = await pool.query(
      `WITH best AS (SELECT DISTINCT ON (tc_id,platform) tc_id,platform,status
                       FROM qa.run_results WHERE run_id>=21 AND tc_id NOT IN ('TC-SMOKE-001','TC-WARMUP-001')
                      ORDER BY tc_id,platform,(status='PASS') DESC)
       SELECT platform, count(*) FILTER (WHERE status='PASS') pass,
              count(*) FILTER (WHERE status='FAIL') fail, count(*) graded FROM best GROUP BY platform`);
    out.consolidated = {}; for (const r of cons.rows) out.consolidated[r.platform] = { pass:+r.pass, fail:+r.fail, graded:+r.graded };
    out.total_test_cases = (await pool.query("SELECT count(*) n FROM qa.test_catalog WHERE tc_id LIKE 'TC-%' AND tc_id NOT IN ('TC-SMOKE-001','TC-WARMUP-001')")).rows[0].n;
    // fail breakdown (what the failures actually ARE)
    const fb = await pool.query(
      `SELECT bug_class, count(*) n FROM qa.bugs WHERE bug_class IS NOT NULL GROUP BY bug_class`);
    out.fail_breakdown = { dev_candidates:0, test_automation_nav:0, flake_infra:0 };
    for (const r of fb.rows) {
      if (["app-bug","app-regression","platform-divergence"].includes(r.bug_class)) out.fail_breakdown.dev_candidates += +r.n;
      else if (r.bug_class === "flake") out.fail_breakdown.flake_infra += +r.n;
      else out.fail_breakdown.test_automation_nav += +r.n;
    }
    // ── App Well-Being score (0-100) for the Run Tests header. ──
    // The score reflects APP health, not test-automation health: failures that
    // are our nav gaps or CI flakes don't penalize the app. We measure how the
    // TCs we COULD reach actually did, and add a small dev-bug penalty.
    // Reachable = TCs that passed on at least one platform, OR failed for a
    // dev-bug reason (app-bug / app-regression / platform-divergence). The
    // numerator is TCs that passed on at least one platform.
    const reach = await pool.query(
      `WITH best AS (
         SELECT tc_id,
                bool_or(status='PASS') any_pass,
                bool_or(status='FAIL') any_fail
           FROM qa.run_results WHERE run_id>=21 AND tc_id NOT IN ('TC-SMOKE-001','TC-WARMUP-001')
          GROUP BY tc_id
       ), devbugs AS (
         SELECT DISTINCT tc_id FROM qa.bugs
          WHERE bug_class IN ('app-bug','app-regression','platform-divergence')
            AND triage_status<>'rejected'
       )
       SELECT count(*) FILTER (WHERE any_pass) passed,
              count(*) reachable
         FROM best
         WHERE any_pass OR tc_id IN (SELECT tc_id FROM devbugs)`);
    const r = reach.rows[0] || {};
    const passed = +r.passed || 0;
    const reachable = +r.reachable || 0;
    const base = reachable ? Math.round((passed / reachable) * 100) : 0;
    // Subtract for confirmed dev bugs (each accepted = -3, each open = -1; rejected = 0).
    const dev = (await pool.query(
      `SELECT triage_status, count(*) n FROM qa.bugs
        WHERE bug_class IN ('app-bug','app-regression','platform-divergence')
        GROUP BY triage_status`)).rows;
    let penalty = 0;
    for (const x of dev) {
      if (x.triage_status === 'accepted') penalty += 3 * +x.n;
      else if (x.triage_status === 'open' || !x.triage_status) penalty += 1 * +x.n;
    }
    const score = Math.max(0, Math.min(100, base - penalty));
    const verdict = score >= 90 ? "Excellent — app is healthy"
                  : score >= 80 ? "Good — minor issues, no blockers"
                  : score >= 70 ? "Fair — some concerns to verify"
                  : score >= 50 ? "Needs attention — several issues"
                  : "Poor — significant problems found";
    out.well_being = {
      score, verdict, base, penalty, reachable, passed,
      basis: `Of ${reachable} test cases our automation could actually exercise, ${passed} passed on at least one platform (${base}%). Penalty −${penalty} for ${dev.reduce((s,d)=>s+ +d.n,0)} developer-bug candidate(s). Test-automation nav gaps and CI flakes do not penalize the app.`,
    };
    res.json(out);
  } catch (e) { next(e); }
});

// GET /api/bugs/nav-gaps — cluster the test-automation-nav failures by ROOT CAUSE
// (the missing testID / unreached anchor) so we fix one root → many TCs unblock.
router.get("/nav-gaps", async (_req, res, next) => {
  try {
    const { rows } = await pool.query(
      `SELECT tc_id, summary, dev_guidance FROM qa.bugs
        WHERE bug_class='test-automation-nav' AND triage_status<>'rejected'`);
    const clusters = {};
    const re1 = /reach:\s*([a-z0-9.*\-]+)/i;
    const re2 = /anchor not reached:\s*([a-z0-9-]+)/i;
    const re3 = /app launch failed/i;
    for (const r of rows) {
      const s = r.summary || "";
      let key = "other";
      let m;
      if ((m = s.match(re1))) key = "couldn't reach " + m[1];
      else if ((m = s.match(re2))) key = "couldn't reach " + m[1];
      else if (re3.test(s)) key = "app launch failed (infra)";
      (clusters[key] = clusters[key] || []).push(r.tc_id);
    }
    const out = Object.entries(clusters)
      .map(([cause, tcs]) => ({ cause, tcs, count: tcs.length }))
      .sort((a, b) => b.count - a.count);
    const total = rows.length;
    // strategy: per known cluster, what fix + ETA
    const fixHints = {
      "cart-screen":      { fix: "Add an Android-specific wait after bottom-cart-btn before asserting cart-screen (CartScreen mounts after a brief route transition).", eta_min: 10 },
      "subscription-screen": { fix: "In generate-flows.js change the SubscriptionScreen anchor entry — tab-subscribe lands on `subrequest-screen`, not `subscription-screen`.", eta_min: 5 },
      "addresscollection-screen": { fix: "Unblocks automatically once `cart-screen` is reached (entry is from Cart).", eta_min: 0 },
      "getstarted-cta":   { fix: "Ensure clearState was applied; TC-CART-011 wrongly assumes pre-auth.", eta_min: 3 },
    };
    for (const c of out) {
      for (const key of Object.keys(fixHints)) {
        if (c.cause.includes(key)) { c.recommended_fix = fixHints[key].fix; c.eta_min = fixHints[key].eta_min; break; }
      }
      if (!c.recommended_fix) { c.recommended_fix = "Best-effort screen — inspect actual nav on a device, then map the correct entry/anchor in generate-flows.js."; c.eta_min = 15; }
    }
    res.json({ total, clusters: out });
  } catch (e) { next(e); }
});

// GET /api/bugs/grade — consolidated per-TC grade: best result per (tc, platform)
// across testID-era runs (PASS if any run passed, else latest FAIL). Powers the
// report summary + per-TC grid.
router.get("/grade", async (req, res, next) => {
  try {
    const minRun = parseInt(req.query.minRun || "21", 10);
    const { rows } = await pool.query(
      `SELECT DISTINCT ON (r.tc_id, r.platform)
              r.tc_id, r.platform, r.status, r.run_id, r.log_excerpt,
              t.screen, t.title, t.priority
         FROM qa.run_results r JOIN qa.test_catalog t ON t.tc_id = r.tc_id
        WHERE r.run_id >= $1 AND r.tc_id NOT IN ('TC-SMOKE-001','TC-WARMUP-001')
        ORDER BY r.tc_id, r.platform, (r.status='PASS') DESC, r.ran_at DESC`,
      [minRun]
    );
    const shortReason = (log) => {
      const s = log || "";
      if (/Unable to launch/i.test(s)) return "app launch failed (CI infra)";
      if (/Unknown error/i.test(s)) return "flake (driver)";
      const nf = s.match(/Id matching regex:\s*([^\s]+)/i);
      if (/not found/i.test(s) && nf) return "couldn't reach: " + nf[1];
      const af = s.match(/id:\s*([a-z0-9-]+)\s*is visible/i);
      if (/Assertion is false/i.test(s) && af) return "screen not reached: " + af[1];
      return s.slice(0, 50);
    };
    const byTc = {};
    for (const r of rows) {
      byTc[r.tc_id] = byTc[r.tc_id] || { tc_id: r.tc_id, screen: r.screen, title: r.title, priority: r.priority };
      byTc[r.tc_id][r.platform] = r.status;
      if (r.status === "FAIL") byTc[r.tc_id][r.platform + "_reason"] = shortReason(r.log_excerpt);
    }
    res.json({ grade: Object.values(byTc), min_run: minRun });
  } catch (e) { next(e); }
});

router.patch("/:id/triage", async (req, res, next) => {
  try {
    const { status, note } = req.body || {};
    if (!["accepted", "rejected", "open"].includes(status)) {
      return res.status(400).json({ error: "status must be accepted | rejected | open" });
    }
    const by = (req.user && req.user.email) || "dashboard";
    const upd = await pool.query(
      `UPDATE qa.bugs SET triage_status=$2, triage_note=$3, triage_by=$4, triage_at=NOW()
         WHERE id=$1 RETURNING id, tc_id, signature, triage_status`,
      [req.params.id, status, note || null, by]
    );
    if (!upd.rows[0]) return res.status(404).json({ error: "bug not found" });
    // Learning: propagate the verdict to all bugs sharing this signature.
    let propagated = 0;
    if (upd.rows[0].signature) {
      const p = await pool.query(
        `UPDATE qa.bugs SET triage_status=$2, triage_note=$3, triage_by=$4, triage_at=NOW()
           WHERE signature=$1 AND id <> $5`,
        [upd.rows[0].signature, status, note || null, by, req.params.id]
      );
      propagated = p.rowCount;
    }
    res.json({ ok: true, bug: upd.rows[0], propagated });
  } catch (e) { next(e); }
});

module.exports = router;
