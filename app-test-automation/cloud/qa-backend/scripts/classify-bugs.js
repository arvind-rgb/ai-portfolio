/**
 * classify-bugs.js — turn the consolidated test grade into a CLASSIFIED bug list
 * with developer guidance + recommended fixes, written to qa.bugs.
 *
 * Logic: take the BEST result per (tc_id, platform) across testID-era runs (PASS if
 * any run passed it, else the latest FAIL + reason). Compare iOS vs Android per TC.
 *
 *   class                | when                                            | dev-relevant?
 *   ---------------------|-------------------------------------------------|--------------
 *   app-bug              | fails BOTH with launch/crash                     | YES (high)
 *   app-regression       | fails BOTH on a PROVEN core flow (nav/anchor)    | YES (high)
 *   platform-divergence  | passes one platform, fails the other            | YES (medium)
 *   test-automation-nav  | fails BOTH on a BEST-EFFORT screen (nav/anchor)  | no  (my fix-list)
 *   flake                | fails with "Unknown error" (driver)             | no  (retry)
 *
 * Only app-bug / app-regression / platform-divergence surface in the DEV section.
 * Learning: if a bug's signature was previously triage_status='rejected' by the dev,
 * the new occurrence inherits 'rejected' (auto-suppressed) so we don't re-flag noise.
 *
 * Usage:  node scripts/classify-bugs.js [minRunId]    (default 21 = testID era)
 */
const fs = require("fs");
const { Client } = require("pg");
const env = {};
for (const line of fs.readFileSync(".env", "utf8").split("\n")) {
  const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
  if (m) env[m[1]] = m[2].replace(/^["']|["']$/g, "");
}
const MIN_RUN = parseInt(process.argv[2] || "21", 10);

const PROVEN = new Set([
  "Splash / Boot Routing", "GetStartedScreen", "LoginScreen", "OTPScreen",
  "WelcomeScreen", "WelcomeScreen → LandingScreen (location gate)",
  "LandingScreen", "GetNowScreen", "ChefFoodListScreen", "CartScreen",
]);

const reasonOf = (log) => {
  const s = log || "";
  if (/Unable to launch/i.test(s)) return { kind: "launch", key: "launch", detail: "app failed to launch" };
  if (/Unknown error/i.test(s)) return { kind: "flake", key: "flake", detail: "Maestro driver 'Unknown error'" };
  const nf = s.match(/Id matching regex:\s*([^\s]+)/i);
  if (/not found/i.test(s) && nf) return { kind: "nav", key: "id:" + nf[1], detail: `element not found: ${nf[1]}` };
  const af = s.match(/id:\s*([a-z0-9-]+)\s*is visible/i);
  if (/Assertion is false/i.test(s) && af) return { kind: "nav", key: "anchor:" + af[1], detail: `screen anchor not reached: ${af[1]}` };
  return { kind: "other", key: "other", detail: (s.slice(0, 80) || "unknown") };
};

(async function main() {
  const c = new Client({
    host: env.POSTGRESQL_HOST, port: +env.POSTGRESQL_PORT,
    database: env.POSTGRESQL_DATABASE, user: env.POSTGRESQL_USER,
    password: env.POSTGRESQL_PASSWORD, ssl: { rejectUnauthorized: false },
  });
  await c.connect();

  // best result per (tc, platform): PASS if any run passed, else latest FAIL
  const { rows } = await c.query(
    `SELECT DISTINCT ON (r.tc_id, r.platform) r.tc_id, r.platform, r.status, r.log_excerpt, r.run_id,
            t.screen, t.title, t.priority
       FROM qa.run_results r JOIN qa.test_catalog t ON t.tc_id=r.tc_id
      WHERE r.run_id >= $1
      ORDER BY r.tc_id, r.platform, (r.status='PASS') DESC, r.ran_at DESC`,
    [MIN_RUN]
  );
  const byTc = {};
  for (const r of rows) {
    byTc[r.tc_id] = byTc[r.tc_id] || { tc_id: r.tc_id, screen: r.screen, title: r.title, priority: r.priority };
    byTc[r.tc_id][r.platform] = r;
  }

  // learning: signatures the dev previously rejected
  const rej = new Set(
    (await c.query("SELECT DISTINCT signature FROM qa.bugs WHERE triage_status='rejected' AND signature IS NOT NULL")).rows.map(r => r.signature)
  );

  let dev = 0, auto = 0, suppressed = 0;
  const latestRun = Math.max(...rows.map(r => +r.run_id), MIN_RUN);

  for (const tc of Object.values(byTc)) {
    const ios = tc.ios, and = tc.android;
    const iosSt = ios ? ios.status : null;   // 'PASS' | 'FAIL' | null (NOT RUN)
    const andSt = and ? and.status : null;
    if (iosSt !== "FAIL" && andSt !== "FAIL") continue; // no failure anywhere → not a bug
    const proven = PROVEN.has(tc.screen);

    // reason from a failing side (prefer a non-flake reason)
    const fails = [ios, and].filter(r => r && r.status === "FAIL");
    let reason = { kind: "other", key: "other", detail: "unknown" };
    for (const f of fails) { const r = reasonOf(f.log_excerpt); reason = r; if (r.kind !== "flake") break; }

    const bothFail = iosSt === "FAIL" && andSt === "FAIL";
    const oneFailOnePass = (iosSt === "FAIL" && andSt === "PASS") || (andSt === "FAIL" && iosSt === "PASS");
    const coverage = (iosSt && andSt) ? "both" : (iosSt ? "iOS-only" : "Android-only");

    let cls, sev, guidance, fix, devRel;
    const plats = `iOS:${iosSt || "not-run"} / Android:${andSt || "not-run"}`;

    // CONSERVATIVE policy (don't spam the dev): a DEV bug needs strong signal —
    // either a true cross-platform divergence, or a failure on BOTH platforms.
    // Single-platform failures (the other platform not yet graded) and CI infra
    // (single-platform launch fail, driver flake) are INTERNAL, never dev bugs.
    if (oneFailOnePass && reason.kind !== "flake" && reason.kind !== "launch") {
      // Surface as a LOW-CONFIDENCE candidate for the dev to verify/triage. Honestly
      // framed: it diverges by platform but may be test timing/nav, not an app bug.
      const badPlat = iosSt === "FAIL" ? "iOS" : "Android";
      const goodPlat = badPlat === "iOS" ? "Android" : "iOS";
      cls = "platform-divergence"; sev = proven ? "medium" : "low"; devRel = true;
      guidance = `⚠️ VERIFY (low-confidence): ${tc.screen} PASSES on ${goodPlat} but FAILS on ${badPlat} (${reason.detail}). ${proven ? "On a core flow — could be a real " + badPlat + "-specific difference." : "On a non-core screen — more likely a test nav/timing difference."} Not asserted as a bug; please confirm or reject.`;
      fix = `Open ${tc.screen} on ${badPlat} and compare vs ${goodPlat}. If it renders fine → Reject (the system suppresses it next run). If genuinely broken on ${badPlat} → Accept.`;
    } else if (oneFailOnePass && reason.kind === "launch") {
      cls = "flake"; sev = "low"; devRel = false;
      guidance = `${tc.screen}: app launch failed on one platform only (${reason.detail}) — a per-runner emulator/sim infra issue, not an app bug.`;
      fix = `Re-run the affected shard. Not a code bug.`;
    } else if (bothFail && reason.kind === "launch") {
      cls = "app-bug"; sev = "high"; devRel = true;
      guidance = `${tc.screen}: the app failed to launch on BOTH platforms (${reason.detail}). A cross-platform launch failure points at a real startup crash or build/config issue (not CI infra, which is per-runner).`;
      fix = `Reproduce a cold launch into ${tc.screen}; check Crashlytics + recent boot-path changes. Confirm the SIT build is healthy.`;
    } else if (bothFail && proven && reason.kind === "nav") {
      cls = "app-regression"; sev = "high"; devRel = true;
      guidance = `Core/verified flow ${tc.screen} FAILED on BOTH platforms (${reason.detail}). A previously-working path is broken on both — likely a real regression or a renamed/removed element (an automation-only issue would usually differ by platform).`;
      fix = `Check ${tc.screen} renders its expected elements; review recent changes. Expected: ${(tc.title||"").slice(0,90)}.`;
    } else if (reason.kind === "flake" || reason.kind === "launch") {
      // single-platform driver flake or single-platform launch = CI infra, internal.
      cls = "flake"; sev = "low"; devRel = false;
      guidance = `CI/driver instability on ${tc.screen} (${reason.detail}; ${coverage}) — per-runner, not deterministic.`;
      fix = `Auto-retried; re-run the affected shard. Not a code bug.`;
    } else {
      // nav failure that is single-platform or on a best-effort screen = MY test nav.
      cls = "test-automation-nav"; sev = "low"; devRel = false;
      guidance = `Automation could not reach ${tc.screen} (${reason.detail}; ${coverage}). Unverified test nav/selector — not confirmed an app bug.`;
      fix = `Internal: correct nav for "${tc.screen}" in generate-flows.js M{} (entry point / anchor id).`;
    }
    if (coverage !== "both" && devRel) guidance += ` (NOTE: only ${coverage.replace("-only","")} graded so far — other platform pending.)`;

    const signature = `${tc.tc_id}|${cls}|${reason.key}`;
    const bug_id = `BUG-${tc.tc_id}`;
    let triage = "open";
    if (rej.has(signature)) { triage = "rejected"; suppressed++; devRel = false; }
    if (devRel) dev++; else auto++;

    const summary = `[${cls}] ${tc.tc_id} ${tc.screen}: ${reason.detail}`;
    // upsert by signature, preserving any human triage
    const ex = await c.query("SELECT id, triage_status FROM qa.bugs WHERE signature=$1 LIMIT 1", [signature]);
    if (ex.rows[0]) {
      const keepTriage = ex.rows[0].triage_status && ex.rows[0].triage_status !== "open" ? ex.rows[0].triage_status : triage;
      await c.query(
        `UPDATE qa.bugs SET tc_id=$2, severity=$3, summary=$4, details=$5, platform=$6, platform_diff_flag=$7,
           bug_class=$8, dev_guidance=$9, recommended_fix=$10, last_seen_run_id=$11,
           occurrence_count=COALESCE(occurrence_count,1)+1, triage_status=$12 WHERE id=$1`,
        [ex.rows[0].id, tc.tc_id, sev, summary, plats, "ios/android", reason.kind === "nav" && !proven ? false : (cls === "platform-divergence"),
         cls, guidance, fix, latestRun, keepTriage]
      );
    } else {
      await c.query(
        `INSERT INTO qa.bugs (bug_id, tc_id, severity, summary, details, platform, signature,
           bug_class, dev_guidance, recommended_fix, run_id, first_seen_run_id, last_seen_run_id,
           occurrence_count, triage_status, reported_at)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$11,$11,1,$12,NOW())`,
        [bug_id, tc.tc_id, sev, summary, plats, "ios/android", signature, cls, guidance, fix, latestRun, triage]
      );
    }
  }
  await c.end();
  console.log(`classified: dev-relevant=${dev}  internal(test-automation/flake)=${auto}  auto-suppressed(prev-rejected)=${suppressed}`);
})().catch(e => { console.error("ERR", e.message); process.exit(1); });
