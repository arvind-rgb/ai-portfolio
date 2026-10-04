// Connections API — the backend for the Connections screen.
// Every route is tenant-scoped via req.tenantId. Credentials never cross this
// boundary outbound: session responses carry {active, accountLabel, refreshedAt}
// only — never the stored blob.

const express = require("express");
const router = express.Router();
const providers = require("../providers");
const { publicRegistry, BY_KEY } = require("../providers/registry");

// GET /api/providers — registry + this tenant's live connection status for each.
router.get("/", async (req, res) => {
  const reg = publicRegistry();
  const out = await Promise.all(reg.map(async (p) => {
    let session = { active: false };
    try { session = await providers.get(p.key).session(req.tenantId); }
    catch (e) { session = { active: false, error: e.message }; }
    return { ...p, adapterMode: providers.mode(p.key), session };
  }));
  res.json({ authMode: req.authMode, tenantId: req.tenantId, providers: out });
});

// GET /api/providers/:key/session — one provider's status (poll target for chips).
router.get("/:key/session", withProvider, async (req, res) => {
  try { res.json(await req.adapter.session(req.tenantId)); }
  catch (e) { res.status(e.status || 500).json({ active: false, error: e.message }); }
});

// POST /api/providers/:key/check — force a live status probe ("Check status" button).
router.post("/:key/check", withProvider, async (req, res) => {
  try { res.json({ ok: true, ...(await req.adapter.check(req.tenantId)) }); }
  catch (e) { res.status(e.status || 500).json({ ok: false, error: e.message }); }
});

// POST /api/providers/:key/login — OTP step 1 (adapter throws if unsupported).
router.post("/:key/login", withProvider, async (req, res) => {
  try { res.json({ ok: true, ...(await req.adapter.login(req.tenantId, req.body || {})) }); }
  catch (e) { res.status(e.status || 500).json({ ok: false, error: e.message }); }
});

// POST /api/providers/:key/verify — OTP step 2.
router.post("/:key/verify", withProvider, async (req, res) => {
  try { res.json({ ok: true, ...(await req.adapter.verify(req.tenantId, req.body || {})) }); }
  catch (e) { res.status(e.status || 500).json({ ok: false, error: e.message }); }
});

// POST /api/providers/:key/save-session — admin fallback (any adapter that implements it).
router.post("/:key/save-session", withProvider, async (req, res) => {
  try { res.json({ ok: true, ...(await req.adapter.saveSession(req.tenantId, req.body || {})) }); }
  catch (e) { res.status(e.status || 500).json({ ok: false, error: e.message }); }
});

// POST /api/providers/:key/logout — disconnect.
router.post("/:key/logout", withProvider, async (req, res) => {
  try { res.json({ ok: true, ...(await req.adapter.logout(req.tenantId)) }); }
  catch (e) { res.status(e.status || 500).json({ ok: false, error: e.message }); }
});

// --- middleware helpers ---
function withProvider(req, res, next) {
  const meta = BY_KEY[req.params.key];
  if (!meta) return res.status(404).json({ error: "unknown_provider", key: req.params.key });
  req.meta = meta;
  try { req.adapter = providers.get(req.params.key); next(); }
  catch (e) { res.status(500).json({ error: e.message }); }
}

module.exports = router;
