// Adapter loader. For each courier in the registry it tries, in order:
//   1. ./private/<key>.js — the production adapter (NOT in this repository; the
//      folder is gitignored). Exports `(meta, ctx) => ProviderAdapter`.
//   2. ./mock             — the reference MockCourierAdapter, so the whole portal
//      (connect → quote → book → track → report) runs with zero credentials.
//
// ctx = { store, crypto, db } — every adapter gets the shared encrypted session
// store, so no adapter ever touches plaintext credentials on disk.

const path = require("path");
const fs = require("fs");
const { BY_KEY, PROVIDERS } = require("./registry");
const { MockCourierAdapter } = require("./mock");
const { sessionStore } = require("../db");
const cryptoMod = require("../crypto");

const ctx = { store: sessionStore, crypto: cryptoMod, db: require("../db") };
const PRIVATE_DIR = path.join(__dirname, "private");

const adapters = {};
const status = {}; // key -> 'live' | 'mock'

for (const meta of PROVIDERS) {
  const p = path.join(PRIVATE_DIR, `${meta.key}.js`);
  if (fs.existsSync(p)) {
    try {
      adapters[meta.key] = require(p)(meta, ctx);
      status[meta.key] = "live";
      continue;
    } catch (e) {
      console.error(`[providers] adapter for ${meta.key} failed to load, using mock:`, e.message);
    }
  }
  adapters[meta.key] = new MockCourierAdapter(meta, ctx);
  status[meta.key] = "mock";
}

function get(key) {
  const a = adapters[key];
  if (!a) { const e = new Error("Unknown provider: " + key); e.status = 404; throw e; }
  return a;
}

function mode(key) { return status[key] || "mock"; }

console.log("[providers] loaded:", Object.entries(status).map(([k, v]) => `${k}:${v}`).join("  "));

module.exports = { get, mode, BY_KEY };
