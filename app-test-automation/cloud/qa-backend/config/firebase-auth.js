const admin = require("firebase-admin");

if (!admin.apps.length) {
  // On Firebase Functions, project ID is auto-detected from the runtime
  // (GCLOUD_PROJECT / FIREBASE_CONFIG). For local dev, pass GOOGLE_CLOUD_PROJECT
  // explicitly via env. We deliberately do NOT use a FIREBASE_*-prefixed env
  // var — that prefix is reserved by the Functions runtime.
  admin.initializeApp();
}

const ALLOWED = (process.env.ALLOWED_EMAILS || "")
  .split(",")
  .map((s) => s.trim().toLowerCase())
  .filter(Boolean);

// CLI escape hatch — used by the test-case-generator skill helpers
// (build-catalog-cloud.py, read-decisions-cloud.py) running on a dev's
// machine. Optional; if unset, only browser-side Firebase Auth works.
const CLI_TOKEN = process.env.QA_CLI_TOKEN || "";

function requireAuth(req, res, next) {
  if (req.method === "OPTIONS") return next();

  // CLI shared-secret path. Distinct header so it can't be confused with a
  // browser bearer token. Both sides must agree on QA_CLI_TOKEN.
  const cliTok = req.headers["x-cli-token"];
  if (cliTok && CLI_TOKEN && cliTok === CLI_TOKEN) {
    req.user = { email: "cli@localhost", uid: "cli" };
    return next();
  }

  const hdr = req.headers.authorization || "";
  const m = hdr.match(/^Bearer\s+(.+)$/i);
  if (!m) {
    return res.status(401).json({ error: "missing bearer token" });
  }

  admin
    .auth()
    .verifyIdToken(m[1])
    .then((decoded) => {
      const email = (decoded.email || "").toLowerCase();
      if (!email || !ALLOWED.includes(email)) {
        return res
          .status(403)
          .json({ error: "email not in allowlist", email });
      }
      req.user = { email, uid: decoded.uid };
      next();
    })
    .catch((e) => {
      res.status(401).json({ error: "invalid token", detail: e.message });
    });
}

module.exports = { requireAuth };
