// Postgres access + a zero-dependency in-memory fallback so the Connections screen
// runs end-to-end before a database is wired. When DATABASE_URL is set the app uses
// the real booker_* tables; otherwise it keeps sessions in memory for this process.
//
// The session store interface is intentionally tiny — the routes only ever call
// these four methods, so swapping the memory store for pg is a localized change.

let pool = null;
const usingPg = Boolean(process.env.DATABASE_URL);

if (usingPg) {
  const { Pool } = require("pg");
  pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 5 });
  pool.on("error", (e) => console.error("[db] pool error:", e.message));
}

// ---- in-memory session store (dev / no DATABASE_URL) ----
// Backed by a JSON file so connections survive restarts. Credentials in the rows
// are already the encrypted envelope from crypto.js, so this file holds no plaintext
// tokens when BOOKER_CRED_KEY is set.
const fs = require("fs");
const path = require("path");
// BOOKER_DATA_DIR relocates the whole file store (used by the demo seed script).
const DATA_DIR = process.env.BOOKER_DATA_DIR || path.join(__dirname, "..", ".data");
const STATE_FILE = process.env.BOOKER_STATE_FILE || path.join(DATA_DIR, "sessions.json");

const mem = new Map(); // key: `${tenantId}:${provider}` -> row

if (!usingPg) {
  try {
    if (fs.existsSync(STATE_FILE)) {
      const obj = JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
      for (const [k, v] of Object.entries(obj)) mem.set(k, v);
      console.log(`[db] restored ${mem.size} provider session(s) from ${STATE_FILE}`);
    }
  } catch (e) { console.warn("[db] could not restore sessions:", e.message); }
}

function persist() {
  if (usingPg) return;
  try {
    fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
    fs.writeFileSync(STATE_FILE, JSON.stringify(Object.fromEntries(mem), null, 2));
  } catch (e) { console.warn("[db] could not persist sessions:", e.message); }
}

function memKey(tenantId, provider) { return `${tenantId}:${provider}`; }

const sessionStore = {
  async get(tenantId, provider) {
    if (usingPg) {
      const { rows } = await pool.query(
        `SELECT tenant_id, provider, credentials, metadata, account_label,
                created_at, refreshed_at, last_used_at, last_401_at
           FROM booker_provider_session WHERE tenant_id = $1 AND provider = $2`,
        [tenantId, provider]
      );
      return rows[0] || null;
    }
    return mem.get(memKey(tenantId, provider)) || null;
  },

  async upsert(tenantId, provider, { credentials, metadata, account_label }) {
    if (usingPg) {
      await pool.query(
        `INSERT INTO booker_provider_session
           (tenant_id, provider, credentials, metadata, account_label, refreshed_at, last_401_at)
         VALUES ($1,$2,$3,$4,$5, NOW(), NULL)
         ON CONFLICT (tenant_id, provider) DO UPDATE SET
           credentials = EXCLUDED.credentials,
           metadata    = COALESCE(EXCLUDED.metadata, booker_provider_session.metadata),
           account_label = COALESCE(EXCLUDED.account_label, booker_provider_session.account_label),
           refreshed_at = NOW(), last_401_at = NULL`,
        [tenantId, provider, credentials, metadata || null, account_label || null]
      );
      return this.get(tenantId, provider);
    }
    const now = new Date().toISOString();
    const prev = mem.get(memKey(tenantId, provider)) || { created_at: now };
    const row = {
      tenant_id: tenantId, provider, credentials, metadata: metadata || prev.metadata || null,
      account_label: account_label || prev.account_label || null,
      created_at: prev.created_at, refreshed_at: now, last_used_at: prev.last_used_at || null, last_401_at: null,
    };
    mem.set(memKey(tenantId, provider), row);
    persist();
    return row;
  },

  async clearToken(tenantId, provider) {
    // "logout" — drop credentials but keep the row shell (mirrors the services).
    if (usingPg) {
      await pool.query(
        `UPDATE booker_provider_session SET credentials = NULL WHERE tenant_id = $1 AND provider = $2`,
        [tenantId, provider]
      );
      return;
    }
    const row = mem.get(memKey(tenantId, provider));
    if (row) { row.credentials = null; row.refreshed_at = new Date().toISOString(); persist(); }
  },

  async mark401(tenantId, provider) {
    if (usingPg) {
      await pool.query(
        `UPDATE booker_provider_session SET credentials = NULL, last_401_at = NOW()
           WHERE tenant_id = $1 AND provider = $2`,
        [tenantId, provider]
      );
      return;
    }
    const row = mem.get(memKey(tenantId, provider));
    if (row) { row.credentials = null; row.last_401_at = new Date().toISOString(); persist(); }
  },
};

// ---- booking store (in-memory + file; booker_booking equivalent) ----
const BOOKINGS_FILE = process.env.BOOKER_BOOKINGS_FILE || path.join(DATA_DIR, "bookings.json");
const bookings = new Map(); // booking_id -> row

if (!usingPg) {
  try { if (fs.existsSync(BOOKINGS_FILE)) { const o = JSON.parse(fs.readFileSync(BOOKINGS_FILE, "utf8")); for (const [k, v] of Object.entries(o)) bookings.set(k, v); } }
  catch (e) { console.warn("[db] could not restore bookings:", e.message); }
}
function persistBookings() {
  if (usingPg) return;
  try { fs.mkdirSync(path.dirname(BOOKINGS_FILE), { recursive: true }); fs.writeFileSync(BOOKINGS_FILE, JSON.stringify(Object.fromEntries(bookings), null, 2)); }
  catch (e) { console.warn("[db] could not persist bookings:", e.message); }
}

// Provider display label, derived on read so both stores return the same API
// shape (the booker_booking schema has no provider_label column).
let PROVIDER_LABELS = null;
function providerLabel(provider) {
  if (!PROVIDER_LABELS) {
    try { PROVIDER_LABELS = require("./providers/registry").BY_KEY; } catch { PROVIDER_LABELS = {}; }
  }
  return (PROVIDER_LABELS[provider] && PROVIDER_LABELS[provider].name) || provider;
}

// booker_booking row → the API shape the routes/portal use (estimated_fare→fare,
// derived provider_label). Kept identical to the in-memory record fields.
function fromPgRow(r) {
  if (!r) return null;
  return {
    booking_id: r.booking_id, tenant_id: r.tenant_id,
    provider: r.provider, provider_label: providerLabel(r.provider),
    provider_order_id: r.provider_order_id, provider_ids: r.provider_ids,
    status: r.status, status_code: r.status_code, status_raw: r.status_raw,
    pickup: r.pickup, drop: r.drop,
    order_number: r.order_number, instructions: r.instructions,
    fare: r.estimated_fare != null ? Number(r.estimated_fare) : null,
    actual_fare: r.actual_fare != null ? Number(r.actual_fare) : null,
    rider_name: r.rider_name, rider_number: r.rider_number, rider_vehicle_number: r.rider_vehicle_number,
    rider_lat: r.rider_lat, rider_lng: r.rider_lng,
    pickup_otp: r.pickup_otp, drop_otp: r.drop_otp, tracking_url: r.tracking_url,
    response_payload: r.response_payload,
    created_at: r.created_at, delivered_at: r.delivered_at, last_polled_at: r.last_polled_at,
  };
}
const PG_COLUMNS = "booking_id, tenant_id, provider, provider_order_id, provider_ids, status, status_code, status_raw, pickup, \"drop\", order_number, instructions, estimated_fare, actual_fare, rider_name, rider_number, rider_vehicle_number, rider_lat, rider_lng, pickup_otp, drop_otp, tracking_url, response_payload, created_at, delivered_at, last_polled_at";
// bookingStore.update patch key → booker_booking column.
const PATCH_COL = { status: "status", status_code: "status_code", status_raw: "status_raw",
  rider_name: "rider_name", rider_number: "rider_number", rider_vehicle_number: "rider_vehicle_number",
  rider_lat: "rider_lat", rider_lng: "rider_lng", pickup_otp: "pickup_otp", drop_otp: "drop_otp",
  actual_fare: "actual_fare", tracking_url: "tracking_url" };

const ACTIVE_STATUSES = ["Created", "Booked", "Rider assigned", "Picked up", "In transit"];

// Shared filter → PG WHERE (provider, from/to on created_at, status "active"|exact).
function pgBookingWhere(tenantId, filter = {}) {
  const where = ["tenant_id = $1"]; const vals = [tenantId];
  if (filter.provider) { vals.push(filter.provider); where.push(`provider = $${vals.length}`); }
  if (filter.from) { vals.push(filter.from + " 00:00:00"); where.push(`created_at >= $${vals.length}`); }
  if (filter.to) { vals.push(filter.to + " 23:59:59.999"); where.push(`created_at <= $${vals.length}`); }
  if (filter.status === "active") { vals.push(ACTIVE_STATUSES); where.push(`status = ANY($${vals.length})`); }
  else if (filter.status) { vals.push(filter.status); where.push(`status = $${vals.length}`); }
  return { where: where.join(" AND "), vals };
}
// Same filter for the in-memory store.
function memBookingFilter(tenantId, filter = {}) {
  const from = filter.from ? new Date(filter.from + "T00:00:00").getTime() : null;
  const to = filter.to ? new Date(filter.to + "T23:59:59.999").getTime() : null;
  return Array.from(bookings.values())
    .filter((r) => r.tenant_id === tenantId)
    .filter((r) => !filter.provider || r.provider === filter.provider)
    .filter((r) => { if (from == null) return true; const t = new Date(r.created_at).getTime(); return !Number.isNaN(t) && t >= from; })
    .filter((r) => { if (to == null) return true; const t = new Date(r.created_at).getTime(); return !Number.isNaN(t) && t <= to; })
    .filter((r) => { if (!filter.status) return true; return filter.status === "active" ? ACTIVE_STATUSES.indexOf(r.status) !== -1 : r.status === filter.status; });
}

let seq = 1000 + bookings.size;
const bookingStore = {
  async create(row) {
    if (usingPg) {
      const { rows } = await pool.query(
        `INSERT INTO booker_booking
           (tenant_id, provider, provider_order_id, provider_ids, status, status_code,
            pickup, "drop", order_number, instructions, estimated_fare, tracking_url,
            pickup_otp, drop_otp, rider_name, rider_number, response_payload)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
         RETURNING ${PG_COLUMNS}`,
        [row.tenant_id, row.provider, row.provider_order_id || null,
         row.provider_ids ? JSON.stringify(row.provider_ids) : null,
         row.status || "Created", row.status_code || "410",
         JSON.stringify(row.pickup), JSON.stringify(row.drop),
         row.order_number || null, row.instructions || null,
         row.fare != null ? row.fare : null, row.tracking_url || null,
         row.pickup_otp || null, row.drop_otp || null, row.rider_name || null, row.rider_number || null,
         row.response_payload ? JSON.stringify(row.response_payload) : null]
      );
      return fromPgRow(rows[0]);
    }
    const id = row.booking_id || ("SH-" + (++seq));
    const rec = { booking_id: id, created_at: new Date().toISOString(), ...row };
    bookings.set(id, rec); persistBookings();
    return rec;
  },
  async get(tenantId, id) {
    if (usingPg) {
      const { rows } = await pool.query(
        `SELECT ${PG_COLUMNS} FROM booker_booking WHERE booking_id = $1 AND tenant_id = $2`, [id, tenantId]);
      return fromPgRow(rows[0]);
    }
    const r = bookings.get(id); return r && r.tenant_id === tenantId ? r : null;
  },
  // All matching rows newest-first (used by reports; the route paginates via listPage).
  async list(tenantId, filter = {}) {
    if (usingPg) {
      const { where, vals } = pgBookingWhere(tenantId, filter);
      const { rows } = await pool.query(
        `SELECT ${PG_COLUMNS} FROM booker_booking WHERE ${where} ORDER BY created_at DESC`, vals);
      return rows.map(fromPgRow);
    }
    return memBookingFilter(tenantId, filter).sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
  },
  // SQL-side pagination: LIMIT/OFFSET + COUNT. Returns { rows, total }.
  async listPage(tenantId, filter = {}, { limit = 6, offset = 0 } = {}) {
    if (usingPg) {
      const { where, vals } = pgBookingWhere(tenantId, filter);
      const cnt = await pool.query(`SELECT COUNT(*)::int AS n FROM booker_booking WHERE ${where}`, vals);
      const total = cnt.rows[0].n;
      const pvals = vals.slice(); pvals.push(limit, offset);
      const { rows } = await pool.query(
        `SELECT ${PG_COLUMNS} FROM booker_booking WHERE ${where}
          ORDER BY created_at DESC LIMIT $${pvals.length - 1} OFFSET $${pvals.length}`, pvals);
      return { rows: rows.map(fromPgRow), total };
    }
    const all = memBookingFilter(tenantId, filter).sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
    return { rows: all.slice(offset, offset + limit), total: all.length };
  },
  async update(id, patch) {
    if (usingPg) {
      const sets = ["last_polled_at = NOW()"], vals = [];
      for (const [k, v] of Object.entries(patch)) {
        if (PATCH_COL[k] && v != null) { vals.push(v); sets.push(`${PATCH_COL[k]} = $${vals.length}`); }
      }
      // Stamp delivered_at the first time a booking reaches Delivered.
      if (patch.status === "Delivered") sets.push("delivered_at = COALESCE(delivered_at, NOW())");
      vals.push(id);
      const { rows } = await pool.query(
        `UPDATE booker_booking SET ${sets.join(", ")} WHERE booking_id = $${vals.length} RETURNING ${PG_COLUMNS}`, vals);
      return fromPgRow(rows[0]);
    }
    const r = bookings.get(id); if (!r) return null;
    if (patch.status === "Delivered" && !r.delivered_at) r.delivered_at = new Date().toISOString();
    Object.assign(r, patch, { last_polled_at: new Date().toISOString() });
    bookings.set(id, r); persistBookings();
    return r;
  },
  // All non-terminal bookings across tenants — the status poller's work list.
  async listActive() {
    if (usingPg) {
      const { rows } = await pool.query(
        `SELECT ${PG_COLUMNS} FROM booker_booking
          WHERE status NOT IN ('Delivered','Cancelled','Failed')
          ORDER BY last_polled_at NULLS FIRST LIMIT 200`);
      return rows.map(fromPgRow);
    }
    const TERMINAL = new Set(["Delivered", "Cancelled", "Failed"]);
    return Array.from(bookings.values()).filter((r) => !TERMINAL.has(r.status));
  },
};

// ---- tenant store (admin module: create/list tenants + operator credentials) ----
const pwd = require("./pwd");
const TENANTS_FILE = process.env.BOOKER_TENANTS_FILE || path.join(DATA_DIR, "tenants.json");
const tenants = new Map(); // tenant_id -> { tenant_id, name, login, password_hash, created_at, status }

if (!usingPg) {
  try { if (fs.existsSync(TENANTS_FILE)) { const o = JSON.parse(fs.readFileSync(TENANTS_FILE, "utf8")); for (const [k, v] of Object.entries(o)) tenants.set(k, v); } }
  catch (e) { console.warn("[db] could not restore tenants:", e.message); }
}
function persistTenants() {
  if (usingPg) return;
  try { fs.mkdirSync(path.dirname(TENANTS_FILE), { recursive: true }); fs.writeFileSync(TENANTS_FILE, JSON.stringify(Object.fromEntries(tenants), null, 2)); }
  catch (e) { console.warn("[db] could not persist tenants:", e.message); }
}
function slugLogin(name) {
  const base = String(name || "tenant").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 24) || "tenant";
  return base + "-" + require("crypto").randomBytes(2).toString("hex");
}
function newUuid() {
  const h = require("crypto").randomBytes(16); h[6] = (h[6] & 0x0f) | 0x40; h[8] = (h[8] & 0x3f) | 0x80;
  const s = h.toString("hex");
  return `${s.slice(0,8)}-${s.slice(8,12)}-${s.slice(12,16)}-${s.slice(16,20)}-${s.slice(20)}`;
}
const publicTenant = (t) => t && { tenant_id: t.tenant_id, name: t.name, login: t.login, created_at: t.created_at, status: t.status || "active" };

const tenantStore = {
  // Returns the created tenant PLUS the one-time plaintext password (admin shares it).
  async create({ name }) {
    const tenant_id = newUuid();
    const login = slugLogin(name);
    const password = pwd.randomPassword();
    const password_hash = pwd.hash(password);
    const created_at = new Date().toISOString();
    if (usingPg) {
      await pool.query(`INSERT INTO booker_tenant (tenant_id, name) VALUES ($1,$2)`, [tenant_id, name || "Unnamed"]);
      await pool.query(`INSERT INTO booker_operator_auth (tenant_id, login, password_hash) VALUES ($1,$2,$3)`, [tenant_id, login, password_hash]);
    } else {
      tenants.set(tenant_id, { tenant_id, name: name || "Unnamed", login, password_hash, created_at, status: "active" });
      persistTenants();
    }
    return { tenant: { tenant_id, name: name || "Unnamed", login, created_at, status: "active" }, password };
  },
  async list() {
    if (usingPg) {
      const { rows } = await pool.query(
        `SELECT t.tenant_id, t.name, t.created_at, t.status, a.login
           FROM booker_tenant t LEFT JOIN booker_operator_auth a ON a.tenant_id = t.tenant_id
          ORDER BY t.created_at DESC`);
      return rows.map((r) => ({ tenant_id: r.tenant_id, name: r.name, login: r.login, created_at: r.created_at, status: r.status || "active" }));
    }
    return Array.from(tenants.values()).sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")).map(publicTenant);
  },
  // Operator login → tenant_id (or null). Matches by login OR tenant_id.
  async verifyOperator(loginOrId, password) {
    if (usingPg) {
      const { rows } = await pool.query(
        `SELECT tenant_id, password_hash FROM booker_operator_auth WHERE login = $1 OR tenant_id::text = $1`, [String(loginOrId || "")]);
      const r = rows[0];
      return r && pwd.verify(password, r.password_hash) ? r.tenant_id : null;
    }
    for (const t of tenants.values()) {
      if ((t.login === loginOrId || t.tenant_id === loginOrId) && pwd.verify(password, t.password_hash)) return t.tenant_id;
    }
    return null;
  },
  async count() { return usingPg ? Number((await pool.query(`SELECT COUNT(*)::int AS n FROM booker_operator_auth`)).rows[0].n) : tenants.size; },
};

async function query(text, params) {
  if (!usingPg) throw new Error("No DATABASE_URL — query() unavailable in memory mode");
  return pool.query(text, params);
}

// Idempotent migration + dev-tenant seed, run on boot when DATABASE_URL is set.
// The migration is all IF NOT EXISTS, so re-running is safe. The dev tenant is
// seeded so the bootstrap-issued token's tenant_id satisfies booker_booking's FK.
const DEV_TENANT = "00000000-0000-0000-0000-000000000001";
async function migrate() {
  if (!usingPg) return { skipped: true };
  const sql = fs.readFileSync(path.join(__dirname, "..", "migrations", "booker_0001_init.sql"), "utf8");
  await pool.query(sql);
  await pool.query(
    `INSERT INTO booker_tenant (tenant_id, name) VALUES ($1, $2)
       ON CONFLICT (tenant_id) DO NOTHING`,
    [process.env.BOOKER_TENANT_ID || DEV_TENANT, "ShipHop.AI (owner account)"]);
  return { ok: true };
}

module.exports = { usingPg, pool, query, migrate, sessionStore, bookingStore, tenantStore };
