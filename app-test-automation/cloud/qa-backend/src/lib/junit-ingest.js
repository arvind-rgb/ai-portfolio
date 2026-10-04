/**
 * JUnit → qa.run_results + qa.bugs ingestion.
 *
 * Maestro `--format junit` emits one <testsuite> with one <testcase> per flow.
 * The testcase `name` attribute is the YAML's filename (e.g. "TC-LGN-001.yaml")
 * — we regex `TC-[A-Z0-9]+-\d+` out of it for the tc_id.
 *
 *   <testcase name="TC-LGN-001.yaml" time="3.42">
 *     <failure message="...">stack trace...</failure>
 *   </testcase>
 *
 * Bug signature: sha1(tc_id + first 200 chars of failure message). Used to
 * dedupe bugs across runs.
 */

const crypto = require("crypto");
const { XMLParser } = require("fast-xml-parser");

const TC_ID_RE = /TC-[A-Z0-9]+-\d+/;

const parser = new XMLParser({
  ignoreAttributes: false,
  attributeNamePrefix: "",
  textNodeName: "_text",
  parseAttributeValue: true,
});

function parseJunit(xml) {
  const j = parser.parse(xml);
  const suite = j.testsuites && j.testsuites.testsuite
    ? j.testsuites.testsuite
    : j.testsuite;
  if (!suite) return [];
  // Single testcase comes back as object; multiple as array.
  let cases = suite.testcase || [];
  if (!Array.isArray(cases)) cases = [cases];

  return cases.map((tc) => {
    const name = String(tc.name || "");
    const m = name.match(TC_ID_RE);
    const tcId = m ? m[0] : null;
    const duration = Number(tc.time) || null;
    const fail = tc.failure || tc.error;
    const skipped = tc.skipped !== undefined;
    let status = "PASS";
    let message = null;
    let details = null;
    if (skipped) {
      status = "SKIPPED";
    } else if (fail) {
      status = "FAIL";
      message = (fail.message || "").toString();
      details = (fail._text || (typeof fail === "string" ? fail : "")).toString();
    }
    return { tc_id: tcId, raw_name: name, status, duration_s: duration, message, details };
  });
}

function bugSignature(tcId, message) {
  const msg = (message || "").slice(0, 200);
  return crypto.createHash("sha1").update(`${tcId}::${msg}`).digest("hex");
}

const PRIORITY_TO_SEVERITY = {
  P0: "blocker",
  P1: "high",
  P2: "medium",
  P3: "low",
};

function severityFromPriority(priority) {
  return PRIORITY_TO_SEVERITY[priority] || "medium";
}

/**
 * Ingest a parsed JUnit batch into qa.run_results + qa.bugs.
 *
 * @param client       — pg client (within a transaction the caller manages)
 * @param runId        — qa.test_runs.id
 * @param platform     — 'android' | 'ios'
 * @param shardId      — qa.run_shards.id (the parent shard row)
 * @param cases        — array from parseJunit()
 * @param screenshots  — map of tc_id → signed_url for the screenshot (optional)
 * @return tally {pass, fail, skipped, bugsCreated, bugsDeduped}
 */
async function ingestCases(client, runId, platform, shardId, cases, screenshots = {}) {
  let pass = 0, fail = 0, skipped = 0;
  let bugsCreated = 0, bugsDeduped = 0;

  for (const c of cases) {
    if (!c.tc_id) continue;
    if (c.status === "PASS") pass++;
    else if (c.status === "FAIL") fail++;
    else skipped++;

    // 1. Per-run result row.
    await client.query(
      `INSERT INTO qa.run_results
         (run_id, tc_id, platform, status, duration_s, log_excerpt, ran_at)
       VALUES ($1, $2, $3, $4, $5, $6, NOW())`,
      [
        runId,
        c.tc_id,
        platform,
        c.status,
        c.duration_s,
        c.status === "FAIL" ? (c.details || c.message || "").slice(0, 4000) : null,
      ]
    );

    // 2. Update canonical qa.test_catalog with latest result on this platform.
    //    The catalog only stores ONE last result; we tag it with the platform
    //    in the failure_reason for cross-platform clarity.
    if (c.status !== "SKIPPED") {
      await client.query(
        `UPDATE qa.test_catalog
            SET last_run_result = $2,
                last_run_ts     = NOW(),
                failure_reason  = CASE WHEN $2 = 'FAIL'
                                       THEN $3 ELSE failure_reason END,
                screenshot_path = COALESCE($4, screenshot_path),
                updated_at      = NOW()
          WHERE tc_id = $1`,
        [
          c.tc_id,
          c.status,
          c.status === "FAIL" ? `[${platform}] ${(c.message || "").slice(0, 240)}` : null,
          screenshots[c.tc_id] || null,
        ]
      );
    }

    // 3. Bug detection — FAILs only.
    if (c.status === "FAIL") {
      const sig = bugSignature(c.tc_id, c.message);

      // Lookup TC priority for severity.
      const { rows: tcRow } = await client.query(
        "SELECT screen, priority FROM qa.test_catalog WHERE tc_id = $1",
        [c.tc_id]
      );
      const severity = severityFromPriority(tcRow[0] && tcRow[0].priority);
      const screen = tcRow[0] && tcRow[0].screen;

      // Existing recent bug with same signature?
      const { rows: existing } = await client.query(
        `SELECT id FROM qa.bugs
          WHERE signature = $1 AND reported_at > NOW() - INTERVAL '30 days'
          ORDER BY reported_at DESC LIMIT 1`,
        [sig]
      );

      if (existing[0]) {
        // Dedup — record this occurrence + bump counter + update last_seen.
        const bugId = existing[0].id;
        const occ = await client.query(
          `INSERT INTO qa.bug_occurrences (bug_id, run_id)
           VALUES ($1, $2)
           ON CONFLICT (bug_id, run_id) DO NOTHING
           RETURNING id`,
          [bugId, runId]
        );
        if (occ.rowCount > 0) {
          await client.query(
            `UPDATE qa.bugs
                SET last_seen_run_id  = $2,
                    occurrence_count  = occurrence_count + 1,
                    screenshot_url    = COALESCE($3, screenshot_url)
              WHERE id = $1`,
            [bugId, runId, screenshots[c.tc_id] || null]
          );
        }
        bugsDeduped++;
      } else {
        // New bug. bug_id = BUG-<screen-prefix>-<next>
        const screenPrefix = screen
          ? screen.replace(/[^A-Za-z]/g, "").toUpperCase().slice(0, 4) || "MAN"
          : "GEN";
        const { rows: nextRow } = await client.query(
          `SELECT COALESCE(MAX(CAST(SUBSTRING(bug_id FROM '\\d+$') AS INT)), 0) + 1 AS n
             FROM qa.bugs WHERE bug_id LIKE $1`,
          [`BUG-${screenPrefix}-%`]
        );
        const seq = String(nextRow[0].n).padStart(3, "0");
        const bugId = `BUG-${screenPrefix}-${seq}`;

        const { rows: insRow } = await client.query(
          `INSERT INTO qa.bugs
             (bug_id, tc_id, severity, summary, details,
              signature, platform, first_seen_run_id, last_seen_run_id,
              occurrence_count, screenshot_url, run_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8, 1, $9, $8)
           RETURNING id`,
          [
            bugId,
            c.tc_id,
            severity,
            (c.message || "").slice(0, 240),
            (c.details || c.message || "").slice(0, 4000),
            sig,
            platform,
            runId,
            screenshots[c.tc_id] || null,
          ]
        );
        await client.query(
          `INSERT INTO qa.bug_occurrences (bug_id, run_id) VALUES ($1, $2)
           ON CONFLICT DO NOTHING`,
          [insRow[0].id, runId]
        );
        bugsCreated++;
      }
    }
  }

  return { pass, fail, skipped, bugsCreated, bugsDeduped };
}

module.exports = { parseJunit, ingestCases, bugSignature };
