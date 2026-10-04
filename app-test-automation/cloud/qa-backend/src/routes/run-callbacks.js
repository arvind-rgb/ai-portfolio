/**
 * /api/runs/:id/shard/:shard_id/{start|result} + /api/runs/:id/finalize
 *
 * These are the CI → BugBhook callback routes. They use HMAC token auth,
 * NOT Firebase ID tokens. The token is minted at trigger time and bound to
 * the specific run_id. CI presents it in Authorization: Bearer <token>.
 *
 * Mounted at /api-cb so it can have its own auth middleware (the main /api
 * already runs Firebase requireAuth).
 */

const express = require("express");
const pool = require("../../config/postgresql");
const callbackToken = require("../lib/callback-token");
const { parseJunit, ingestCases } = require("../lib/junit-ingest");

const router = express.Router({ mergeParams: true });

// ── HMAC token middleware ──────────────────────────────────
// The route id is canonical and matched against the token's bound run_id.
// We accept run_id from any of these (in priority order):
//   1. req.params.id            (route `/api-cb/runs/:id/...`)
//   2. req.params.run_id        (route `/api-cb/runs/:run_id/...`)
//   3. req.body.run_id          (explicit body, fallback)
//   4. Decode from token itself (last resort — still verified by HMAC)
router.use((req, res, next) => {
  if (req.method === "OPTIONS") return next();
  const hdr = req.headers.authorization || "";
  const m = hdr.match(/^Bearer\s+(.+)$/i);
  if (!m) return res.status(401).json({ error: "missing bearer token" });

  let runId = parseInt(
    req.params.id || req.params.run_id || (req.body && req.body.run_id),
    10
  );
  // Token-self-decode fallback: pull run_id off the token's payload, then
  // require verify() to still pass against it (so a tampered token fails).
  if (!Number.isFinite(runId)) {
    const tokParts = m[1].split(".");
    if (tokParts.length === 3) runId = parseInt(tokParts[0], 10);
  }
  const v = callbackToken.verify(m[1], runId);
  if (!v.ok) {
    return res.status(401).json({ error: "bad token", reason: v.reason });
  }
  req.callback_run_id = v.run_id;
  next();
});

// ── Shard id resolver — lets callers use either the BIGSERIAL shard.id or
// the (platform, shard_index) tuple. Returns { id, platform } or null.
async function resolveShard(client, runId, params) {
  if (params.shard_id && /^\d+$/.test(String(params.shard_id))) {
    const { rows } = await client.query(
      "SELECT id, platform FROM qa.run_shards WHERE id = $1 AND run_id = $2",
      [params.shard_id, runId]
    );
    return rows[0] || null;
  }
  if (params.platform && params.shard_index !== undefined) {
    const { rows } = await client.query(
      `SELECT id, platform FROM qa.run_shards
        WHERE run_id = $1 AND platform = $2 AND shard_index = $3`,
      [runId, params.platform, parseInt(params.shard_index, 10)]
    );
    return rows[0] || null;
  }
  return null;
}

// ── POST /:run_id/shard/:shard_id/start (BIGSERIAL form) ────
// ── POST /:run_id/shard/:platform/:shard_index/start (CI form) ──
router.post(
  ["/:run_id/shard/:shard_id/start", "/:run_id/shard/:platform/:shard_index/start"],
  async (req, res, next) => {
    try {
      const runId = req.callback_run_id;
      const shard = await resolveShard(pool, runId, req.params);
      if (!shard) return res.status(404).json({ error: "shard not found for this run" });
      await pool.query(
        `UPDATE qa.run_shards
            SET status = 'running', started_at = NOW()
          WHERE id = $1`,
        [shard.id]
      );
      await pool.query(
        `UPDATE qa.test_runs
            SET status = 'running'
          WHERE id = $1 AND status = 'queued'`,
        [runId]
      );
      res.json({ ok: true });
    } catch (e) {
      next(e);
    }
  }
);

// ── POST /:run_id/shard/.../result ──────────────────────────
// Body: { junit_xml: "<?xml…</testsuites>", screenshots: { TC-X-001: signed_url, ... } }
router.post(
  ["/:run_id/shard/:shard_id/result", "/:run_id/shard/:platform/:shard_index/result"],
  async (req, res, next) => {
    const client = await pool.connect();
    try {
      const runId = req.callback_run_id;
      const { junit_xml, screenshots, status_override, log_excerpt } = req.body || {};
      if (junit_xml === undefined) {
        return res.status(400).json({ error: "junit_xml field required (use empty string for no-flows case)" });
      }

      const shard = await resolveShard(client, runId, req.params);
      if (!shard) {
        return res.status(404).json({ error: "shard not found for this run" });
      }

      await client.query("BEGIN");
      // Empty junit (e.g. early step failure) — record shard as failed/done
      // without ingesting cases.
      let tally = { pass: 0, fail: 0, skipped: 0, bugsCreated: 0, bugsDeduped: 0 };
      if (junit_xml && junit_xml.trim()) {
        const cases = parseJunit(junit_xml);
        tally = await ingestCases(
          client,
          runId,
          shard.platform,
          shard.id,
          cases,
          screenshots || {}
        );
      }
      await client.query(
        `UPDATE qa.run_shards
            SET status = COALESCE($2, 'done'),
                finished_at = NOW(),
                passed = $3, failed = $4, skipped = $5,
                log_excerpt = COALESCE($6, log_excerpt)
          WHERE id = $1`,
        [
          shard.id,
          status_override || null,
          tally.pass, tally.fail, tally.skipped,
          log_excerpt || null,
        ]
      );
      await client.query("COMMIT");
      res.json({ ok: true, tally });
    } catch (e) {
      await client.query("ROLLBACK").catch(() => {});
      next(e);
    } finally {
      client.release();
    }
  }
);

// ── POST /:run_id/finalize ──────────────────────────────────
// CI calls this once all shards are done. We compute the summary, flag
// cross-platform diffs, set status='done', and stash summary JSON.
router.post(["/:run_id/finalize", "/:id/finalize"], async (req, res, next) => {
  const client = await pool.connect();
  try {
    const runId = req.callback_run_id;
    await client.query("BEGIN");

    // 1. Aggregate counts.
    const { rows: agg } = await client.query(
      `SELECT
         COUNT(*) FILTER (WHERE status = 'PASS')    AS pass,
         COUNT(*) FILTER (WHERE status = 'FAIL')    AS fail,
         COUNT(*) FILTER (WHERE status = 'SKIPPED') AS skipped,
         COUNT(*)                                   AS total,
         COALESCE(SUM(duration_s), 0)               AS total_duration_s
         FROM qa.run_results WHERE run_id = $1`,
      [runId]
    );

    // 2. Flag platform_diff bugs: same tc_id passed on one platform, failed on other.
    await client.query(
      `UPDATE qa.bugs b
          SET platform_diff_flag = TRUE
        WHERE b.run_id = $1
          AND EXISTS (
            SELECT 1 FROM qa.run_results r1
             WHERE r1.run_id = $1 AND r1.tc_id = b.tc_id AND r1.status = 'PASS'
          )`,
      [runId]
    );

    // 3. Mark the run done.
    const summary = agg[0];
    const { rows: shardSummary } = await client.query(
      `SELECT platform,
              COUNT(*)::int AS total,
              SUM(passed)::int AS pass,
              SUM(failed)::int AS fail,
              SUM(skipped)::int AS skipped
         FROM qa.run_shards WHERE run_id = $1 GROUP BY platform`,
      [runId]
    );
    const fullSummary = {
      ...summary,
      by_platform: shardSummary.rows,
      finalized_at: new Date().toISOString(),
    };
    await client.query(
      `UPDATE qa.test_runs
          SET status = 'done',
              finished_at = NOW(),
              summary = $2::jsonb
        WHERE id = $1`,
      [runId, fullSummary]
    );

    await client.query("COMMIT");
    res.json({ ok: true, summary: fullSummary });
  } catch (e) {
    await client.query("ROLLBACK").catch(() => {});
    next(e);
  } finally {
    client.release();
  }
});

module.exports = router;
