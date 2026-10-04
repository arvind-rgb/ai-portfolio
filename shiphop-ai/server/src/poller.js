// Status poller — one interval, PER-PROVIDER INDEPENDENT gates: one courier
// erroring or rate-limiting must never stall the others. Drives booker_booking
// rows toward their terminal status via each adapter's refresh(). Adapters
// without a refresh() are simply skipped.

const providers = require("./providers");
const { bookingStore } = require("./db");

const POLL_MS = Number(process.env.BOOKER_POLL_MS || 60_000);
const PATCH_KEYS = ["status", "status_code", "status_raw", "rider_name", "rider_number",
  "rider_vehicle_number", "rider_lat", "rider_lng", "actual_fare", "tracking_url",
  "pickup_otp", "drop_otp", "instructions"];

let timer = null;
let running = false;

async function pollOnce() {
  if (running) return; // never overlap ticks
  running = true;
  try {
    const active = await bookingStore.listActive();
    if (!active.length) return;

    // Group by provider so one provider's failure gates only itself.
    const byProvider = new Map();
    for (const row of active) {
      if (!byProvider.has(row.provider)) byProvider.set(row.provider, []);
      byProvider.get(row.provider).push(row);
    }

    await Promise.all(Array.from(byProvider.entries()).map(async ([key, rows]) => {
      let adapter;
      try { adapter = providers.get(key); } catch { return; }
      if (typeof adapter.refresh !== "function") return;
      for (const row of rows) {
        try {
          const upd = await adapter.refresh(row.tenant_id, row);
          const patch = {};
          for (const k of PATCH_KEYS) if (upd && upd[k] != null) patch[k] = upd[k];
          if (Object.keys(patch).length) await bookingStore.update(row.booking_id, patch);
        } catch (e) {
          if (e && e.sessionExpired) {
            // Break the batch on an expired session — the rest of this
            // provider's rows would fail identically.
            console.warn(`[poller] ${key}: session expired — skipping remaining rows this tick`);
            try { await adapter.markExpired(row.tenant_id); } catch {}
            break;
          }
          console.warn(`[poller] ${key} ${row.booking_id}: ${e.message}`);
        }
      }
    }));
  } finally {
    running = false;
  }
}

function start() {
  if (timer) return;
  timer = setInterval(() => pollOnce().catch((e) => console.error("[poller]", e.message)), POLL_MS);
  timer.unref?.();
  console.log(`[poller] status polling every ${Math.round(POLL_MS / 1000)}s (per-provider gates)`);
}

module.exports = { start, pollOnce, PATCH_KEYS };
