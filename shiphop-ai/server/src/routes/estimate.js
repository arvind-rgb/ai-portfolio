// Estimate fan-out — the compare screen's backend. Promise.allSettled across every
// courier adapter, 12s per-courier timeout, cheapest-first. One slow or broken
// courier never blocks the others, and "a dead session is not a dead route": an
// expired login is reported (so the UI can prompt a reconnect) instead of hidden.

const express = require("express");
const router = express.Router();
const providers = require("../providers");
const { PROVIDERS } = require("../providers/registry");

const TIMEOUT_MS = 12000;
const withTimeout = (p, ms, label) =>
  Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error(`${label} timed out`)), ms))]);

router.post("/", async (req, res) => {
  const job = req.body?.job || req.body || {};
  const want = Array.isArray(req.body?.providers) && req.body.providers.length
    ? new Set(req.body.providers) : null;

  const targets = PROVIDERS.filter((p) => !want || want.has(p.key));

  // Snapshot each provider's connection state so we can tell "token expired" (was
  // connected, token died) from "never set up". `last401` stays set until the user
  // reconnects, so the alert persists across searches, not just the detection one.
  const snap = {};
  await Promise.all(targets.map(async (p) => {
    try { const s = await providers.get(p.key).session(req.tenantId); snap[p.key] = { active: s.active, last401: Boolean(s.last401At), expired: Boolean(s.expired) }; }
    catch { snap[p.key] = { active: false, last401: false, expired: false }; }
  }));

  const settled = await Promise.allSettled(targets.map((p) => {
    const a = providers.get(p.key);
    return withTimeout(a.estimate(req.tenantId, job), TIMEOUT_MS, p.name);
  }));

  const results = targets.map((p, i) => {
    const base = { code: p.code, provider: p.key, label: p.name, color: p.color, note: null };
    const s = settled[i];
    if (s.status === "rejected") {
      const err = s.reason || {};
      const expired = Boolean(err.sessionExpired) && (snap[p.key].active || snap[p.key].last401 || snap[p.key].expired);
      return { ...base, serviceable: null, fare: null, bookable: !err.sessionExpired,
        sessionExpired: Boolean(err.sessionExpired), expired, error: err.message || "Estimate failed" };
    }
    const v = s.value || {};
    if (v.live === false) {
      // Expired if it was connected (token died this call) OR is still flagged
      // expired from a prior search and hasn't been reconnected.
      const expired = snap[p.key].active || snap[p.key].last401 || snap[p.key].expired;
      return { ...base, serviceable: null, fare: null, bookable: false, sessionExpired: true, expired,
        error: expired ? "session expired — reconnect" : "not connected" };
    }
    return { ...base, serviceable: v.serviceable === true, fare: v.fare ?? null,
      eta: v.eta ?? null, distance: v.distance ?? null, bookable: true, note: v.note || null };
  });

  // Flag newly-expired sessions so the Connections board goes red for them too.
  const expired = results.filter((r) => r.expired).map((r) => ({ provider: r.provider, label: r.label }));
  for (const e of expired) { try { await providers.get(e.provider).markExpired(req.tenantId); } catch {} }

  const rank = (r) => (r.fare != null ? 0 : r.bookable ? 1 : 2);
  results.sort((a, b) => rank(a) - rank(b) || (a.fare ?? 0) - (b.fare ?? 0));
  res.json({ ok: true, results, expired });
});

module.exports = router;
