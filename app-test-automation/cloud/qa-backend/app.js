require("dotenv").config();

const express = require("express");
const cors = require("cors");
const functions = require("firebase-functions");

const { requireAuth } = require("./config/firebase-auth");

const app = express();

const origin = process.env.DASHBOARD_ORIGIN || "*";
app.use(cors({ origin, credentials: false }));
// 8 MB cap — covers the 5 MB file limit + base64 overhead (~33%) + JSON envelope.
app.use(express.json({ limit: "8mb" }));

app.get("/", (_req, res) => {
  res.type("text/plain").send("bhookleQaBackend up");
});

app.get("/health", (_req, res) => {
  res.json({ ok: true, ts: new Date().toISOString() });
});

// Every /api route below this is auth-gated.
app.use("/api", requireAuth);

const catalogRoutes = require("./src/routes/catalog");
const tcRoutes = require("./src/routes/tcs");
const snapshotRoutes = require("./src/routes/snapshots");
const analysisRoutes = require("./src/routes/analysis");
const analysisInputsRoutes = require("./src/routes/analysis-inputs");
const runsRoutes = require("./src/routes/runs");
const buildsRoutes = require("./src/routes/builds");
const bugsRoutes = require("./src/routes/bugs");
const maestroBundleRoutes = require("./src/routes/maestro-bundle");
const runCallbacksRoutes = require("./src/routes/run-callbacks");

app.use("/api/catalog", catalogRoutes);
app.use("/api/tcs", tcRoutes);
app.use("/api/snapshots", snapshotRoutes);
// Inputs is registered BEFORE the parent /api/analysis so /api/analysis/inputs
// resolves to the inputs router, not analysis's catch-all.
app.use("/api/analysis/inputs", analysisInputsRoutes);
app.use("/api/analysis", analysisRoutes);
app.use("/api/builds", buildsRoutes);
app.use("/api/bugs", bugsRoutes);
app.use("/api/maestro-bundle", maestroBundleRoutes);
app.use("/api/runs", runsRoutes);

// CI callbacks use HMAC token auth (NOT Firebase ID token); mounted as a
// sibling under /api-cb to bypass the /api requireAuth middleware. The
// router has its own bearer-token check.
app.use("/api-cb/runs", runCallbacksRoutes);

app.use((err, _req, res, _next) => {
  console.error("[qa-be] unhandled:", err);
  res.status(500).json({ error: "internal", detail: err.message });
});

if (require.main === module) {
  const port = process.env.PORT || 3010;
  app.listen(port, () => console.log(`bhookleQaBackend on :${port}`));
}

exports.bhookleQaBackend = functions
  .region("asia-south1")
  .runWith({ memory: "512MB", timeoutSeconds: 60 })
  .https.onRequest(app);
