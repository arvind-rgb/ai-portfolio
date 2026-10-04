// Admin module — super-admin login + tenant management. The admin logs in with
// BOOKER_ADMIN_PASSWORD, creates tenants (businesses), and gets a one-time
// operator credential to hand each one. Mounted before tenantContext.
//
//   POST /api/admin/login   { password }        → { token }   (admin JWT, role:admin)
//   GET  /api/admin/tenants                      → { tenants } (admin only)
//   POST /api/admin/tenants { name }             → { tenant, password }  (password shown ONCE)

const express = require("express");
const router = express.Router();
const { signToken, adminContext } = require("../auth");
const { tenantStore } = require("../db");

// Public: admin login (email + password). BOOKER_ADMIN_EMAIL is optional — if
// unset, any email is accepted and only the password is checked.
router.post("/login", (req, res) => {
  const cfgPass = process.env.BOOKER_ADMIN_PASSWORD || "";
  const cfgEmail = process.env.BOOKER_ADMIN_EMAIL || "";
  if (!cfgPass) return res.status(503).json({ ok: false, error: "admin_not_configured", detail: "Set BOOKER_ADMIN_EMAIL / BOOKER_ADMIN_PASSWORD in server/.env" });
  const email = String((req.body && req.body.email) || "").trim().toLowerCase();
  const given = String((req.body && req.body.password) || "");
  const eq = (x, y) => { const a = Buffer.from(x), b = Buffer.from(y); return a.length === b.length && require("crypto").timingSafeEqual(a, b); };
  const emailOk = !cfgEmail || eq(email, cfgEmail.trim().toLowerCase());
  const passOk = eq(given, cfgPass);
  if (!emailOk || !passOk) return res.status(401).json({ ok: false, error: "invalid_credentials" });
  try {
    const token = signToken({ role: "admin", sub: cfgEmail || "admin" }, process.env.BOOKER_ADMIN_TOKEN_TTL || "8h");
    res.json({ ok: true, token });
  } catch (e) { res.status(e.status || 500).json({ ok: false, error: e.message }); }
});

// Everything below requires a valid admin JWT.
router.use(adminContext);

router.get("/tenants", async (_req, res) => {
  try { res.json({ ok: true, tenants: await tenantStore.list() }); }
  catch (e) { res.status(500).json({ ok: false, error: e.message }); }
});

router.post("/tenants", async (req, res) => {
  const name = String((req.body && req.body.name) || "").trim();
  if (!name) return res.status(400).json({ ok: false, error: "name_required" });
  try {
    const { tenant, password } = await tenantStore.create({ name });
    // password is returned ONCE — the admin copies it and hands it to the operator.
    res.json({ ok: true, tenant, password });
  } catch (e) { res.status(500).json({ ok: false, error: e.message }); }
});

module.exports = router;
