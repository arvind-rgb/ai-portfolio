// Tenant context. Rule: never let the client assert its own tenant — a tenant
// header is an IDOR waiting to happen in a multi-tenant product. tenant_id is
// resolved only from a verified JWT.
//
// For local dev (no BOOKER_JWT_SECRET) we fall back to a single fixed dev tenant so
// the portal runs. The moment a secret is configured, the JWT path is enforced.

const DEV_TENANT = "00000000-0000-0000-0000-000000000001";
const SECRET = process.env.BOOKER_JWT_SECRET || "";

function tenantContext(req, res, next) {
  if (!SECRET) {
    // Dev mode: everyone is the dev tenant. Loudly single-tenant.
    req.tenantId = DEV_TENANT;
    req.authMode = "dev";
    return next();
  }
  const hdr = req.headers.authorization || "";
  const token = hdr.startsWith("Bearer ") ? hdr.slice(7) : "";
  if (!token) return res.status(401).json({ error: "auth_required" });
  try {
    const jwt = require("jsonwebtoken");
    const claims = jwt.verify(token, SECRET);
    if (!claims.tenant_id) return res.status(401).json({ error: "no_tenant_in_token" });
    req.tenantId = claims.tenant_id;
    req.userId = claims.sub || claims.user_id || null;
    req.authMode = "jwt";
    return next();
  } catch (e) {
    return res.status(401).json({ error: "invalid_token", detail: e.message });
  }
}

// Sign a JWT (tenant or admin). Throws if no secret configured.
function signToken(payload, ttl) {
  if (!SECRET) { const e = new Error("BOOKER_JWT_SECRET not set — cannot issue tokens"); e.status = 503; throw e; }
  const jwt = require("jsonwebtoken");
  return jwt.sign(payload, SECRET, { expiresIn: ttl || process.env.BOOKER_TOKEN_TTL || "12h" });
}

// Admin-only guard for /api/admin/* (except the login endpoint). Requires a
// verified JWT with role:"admin".
function adminContext(req, res, next) {
  if (!SECRET) return res.status(503).json({ error: "auth_not_configured", detail: "Set BOOKER_JWT_SECRET" });
  const hdr = req.headers.authorization || "";
  const token = hdr.startsWith("Bearer ") ? hdr.slice(7) : "";
  if (!token) return res.status(401).json({ error: "auth_required" });
  try {
    const claims = require("jsonwebtoken").verify(token, SECRET);
    if (claims.role !== "admin") return res.status(403).json({ error: "admin_only" });
    req.admin = claims;
    return next();
  } catch (e) {
    return res.status(401).json({ error: "invalid_token", detail: e.message });
  }
}

module.exports = { tenantContext, adminContext, signToken, DEV_TENANT };
