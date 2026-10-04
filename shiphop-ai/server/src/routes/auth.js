// Operator token issuance — the ONLY way the portal obtains a tenant-scoped JWT.
// Mounted BEFORE tenantContext (it can't require a token to issue one).
//
// Login resolution order:
//   1. { operator, password } → verified against tenants created in the admin
//      module (booker_operator_auth). Mints a JWT for that operator's tenant.
//   2. Env single-operator (BOOKER_OPERATORS / BOOKER_OPERATOR_PASSWORD).
//   3. Bootstrap: no creds supplied → issue the dev tenant token so the portal
//      runs for one internal operator. Disable with BOOKER_DISABLE_BOOTSTRAP=1
//      once real tenants exist (then credentials are mandatory).

const express = require("express");
const router = express.Router();
const { signToken, DEV_TENANT } = require("../auth");
const { tenantStore } = require("../db");

function envOperators() {
  try {
    const arr = JSON.parse(process.env.BOOKER_OPERATORS || "[]");
    if (Array.isArray(arr) && arr.length) return arr;
  } catch { /* fall through */ }
  if (process.env.BOOKER_OPERATOR_PASSWORD) {
    return [{
      operator: process.env.BOOKER_OPERATOR_ID || "operator",
      password: process.env.BOOKER_OPERATOR_PASSWORD,
      tenant_id: process.env.BOOKER_TENANT_ID || DEV_TENANT,
    }];
  }
  return [];
}

router.post("/token", async (req, res) => {
  const secret = process.env.BOOKER_JWT_SECRET || "";
  const { operator, password } = req.body || {};

  let tenant_id = null, sub = null;

  // 1) Admin-created operator credentials.
  if (operator && password) {
    try {
      const tid = await tenantStore.verifyOperator(operator, password);
      if (tid) { tenant_id = tid; sub = String(operator); }
    } catch (e) { /* store error → fall through to other methods */ }
    // 2) Env operators.
    if (!tenant_id) {
      const m = envOperators().find((o) => o.password === password && (o.operator === operator));
      if (m) { tenant_id = m.tenant_id || DEV_TENANT; sub = m.operator; }
    }
    if (!tenant_id) return res.status(401).json({ ok: false, error: "invalid_credentials" });
  } else {
    // 3) Bootstrap (single internal operator) unless explicitly disabled.
    if (String(process.env.BOOKER_DISABLE_BOOTSTRAP || "") === "1") {
      return res.status(401).json({ ok: false, error: "credentials_required" });
    }
    tenant_id = process.env.BOOKER_TENANT_ID || DEV_TENANT;
    sub = "bootstrap";
  }

  if (!secret) return res.json({ ok: true, token: null, tenant_id, mode: "dev" });
  const token = signToken({ tenant_id, sub, role: "operator" });
  res.json({ ok: true, token, tenant_id, mode: "jwt" });
});

module.exports = router;
