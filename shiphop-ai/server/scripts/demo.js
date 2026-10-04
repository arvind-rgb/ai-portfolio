// One-command demo: `npm run demo` → http://localhost:8890
//
// Boots the real server with throwaway secrets, a fresh file store in a temp dir,
// and the mock courier adapters, then seeds a demo tenant, connected couriers
// (one deliberately expired, to show the reconnect UX) and two weeks of booking
// history for the Reports page. No database, no courier, no SMS is ever touched.

const os = require("os");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const dataDir = process.env.BOOKER_DATA_DIR || fs.mkdtempSync(path.join(os.tmpdir(), "shiphop-demo-"));
const defaults = {
  PORT: "8890",
  BOOKER_DATA_DIR: dataDir,
  BOOKER_CRED_KEY: crypto.randomBytes(32).toString("base64"),   // ephemeral, per run
  BOOKER_JWT_SECRET: crypto.randomBytes(48).toString("base64url"), // ephemeral, per run
  BOOKER_ADMIN_EMAIL: "admin@shiphop.test",
  BOOKER_ADMIN_PASSWORD: "shiphop-admin",
  BOOKER_DISABLE_BOOTSTRAP: "1",
  MOCK_STEP_SECONDS: "30",
};
for (const [k, v] of Object.entries(defaults)) if (!process.env[k]) process.env[k] = v;
delete process.env.DATABASE_URL; // the demo never talks to a database

require("./seed-demo")(dataDir);
console.log(`[demo] data dir: ${dataDir}`);
console.log("[demo] operator login: demo-kitchen / shiphop-demo   ·   admin: admin@shiphop.test / shiphop-admin");
require("../src/app");
