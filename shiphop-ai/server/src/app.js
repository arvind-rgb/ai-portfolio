// ShipHop.AI portal server — bootstrap.
// Serves the static portal (public/) and mounts the tenant-scoped API.

const path = require("path");
const fs = require("fs");

// Minimal .env loader (no dependency) — so BOOKER_CRED_KEY etc. survive restarts.
(function loadEnv() {
  const f = path.join(__dirname, "..", ".env");
  if (!fs.existsSync(f)) return;
  for (const line of fs.readFileSync(f, "utf8").split("\n")) {
    const m = /^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/.exec(line);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
})();

const express = require("express");
const { tenantContext } = require("./auth");

const app = express();
app.use(express.json({ limit: "1mb" }));

// Same-origin static hosting for the portal (booking page + connections screen).
const PUBLIC_DIR = path.join(__dirname, "..", "..", "public");
app.use(express.static(PUBLIC_DIR));

app.get("/healthz", (_req, res) => res.json({ ok: true, service: "shiphop-ai", ts: Date.now() }));

// Token issuance + admin module — mounted BEFORE tenantContext (they hand out
// the very tokens tenantContext requires, so they can't be behind it).
app.use("/api/auth", require("./routes/auth"));
app.use("/api/admin", require("./routes/admin"));

// All other /api routes are tenant-scoped.
app.use("/api", tenantContext);
app.use("/api/providers", require("./routes/providers"));
app.use("/api/estimate", require("./routes/estimate"));
app.use("/api/bookings", require("./routes/bookings"));
app.use("/api/reports", require("./routes/reports"));
app.use("/api/places", require("./routes/places"));

// Convenience: /connections, /admin and /book resolve to their pages.
app.get("/connections", (_req, res) => res.sendFile(path.join(PUBLIC_DIR, "connections.html")));
app.get("/admin", (_req, res) => res.sendFile(path.join(PUBLIC_DIR, "admin.html")));
app.get("/", (_req, res) => res.sendFile(path.join(PUBLIC_DIR, "index.html")));

const PORT = process.env.PORT || 8787;
app.listen(PORT, async () => {
  console.log(`[shiphop-ai] listening on http://localhost:${PORT}`);
  console.log(`  portal:      http://localhost:${PORT}/`);
  console.log(`  connections: http://localhost:${PORT}/connections`);
  const { usingPg, migrate } = require("./db");
  if (usingPg) {
    try { await migrate(); console.log("[db] Postgres store — booker_* migrated + dev tenant seeded"); }
    catch (e) { console.error("[db] migration failed — check DATABASE_URL / permissions:", e.message); }
  } else {
    console.log("[db] in-memory + file store (set DATABASE_URL to use Postgres)");
  }
  require("./poller").start();
});

module.exports = app;
