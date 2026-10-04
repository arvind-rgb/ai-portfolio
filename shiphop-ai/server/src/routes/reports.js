// Reporting — aggregates the tenant's bookings (optionally within a date range)
// into totals, per-provider breakdown, and a per-day series. Computed in JS from
// bookingStore.list so it works identically on Postgres or the file store.

const express = require("express");
const router = express.Router();
const { bookingStore } = require("../db");
const { BY_KEY } = require("../providers/registry");

const ACTIVE = new Set(["Created", "Booked", "Rider assigned", "Picked up", "In transit"]);
const round2 = (n) => Math.round((Number(n) || 0) * 100) / 100;
const fareOf = (b) => (b.actual_fare != null ? Number(b.actual_fare) : (b.fare != null ? Number(b.fare) : null));

// GET /api/reports?from=YYYY-MM-DD&to=YYYY-MM-DD
router.get("/", async (req, res) => {
  const from = req.query.from || null, to = req.query.to || null;
  const rows = await bookingStore.list(req.tenantId, { from, to });

  let delivered = 0, cancelled = 0, inprog = 0, failed = 0, spend = 0, spendN = 0;
  const byProv = {}, byDay = {};
  for (const b of rows) {
    const st = b.status;
    if (st === "Delivered") delivered++;
    else if (st === "Cancelled") cancelled++;
    else if (st === "Failed") failed++;
    else if (ACTIVE.has(st)) inprog++;

    const p = byProv[b.provider] || (byProv[b.provider] = {
      provider: b.provider, provider_label: (BY_KEY[b.provider] && BY_KEY[b.provider].name) || b.provider,
      rides: 0, delivered: 0, cancelled: 0, spend: 0,
    });
    p.rides++;
    if (st === "Delivered") { p.delivered++; const f = fareOf(b); if (f != null) { p.spend += f; spend += f; spendN++; } }
    if (st === "Cancelled") p.cancelled++;

    // created_at is a Date (PG) or ISO string (file store) — normalize to YYYY-MM-DD.
    let day = "";
    if (b.created_at) { try { day = new Date(b.created_at).toISOString().slice(0, 10); } catch { day = ""; } }
    if (day) { const d = byDay[day] || (byDay[day] = { day, rides: 0, spend: 0 }); d.rides++; if (st === "Delivered") { const f = fareOf(b); if (f != null) d.spend += f; } }
  }

  const rides = rows.length;
  res.json({
    ok: true,
    range: { from, to },
    totals: {
      rides, delivered, cancelled, in_progress: inprog, failed,
      spend: round2(spend), avg_fare: round2(spendN ? spend / spendN : 0),
      cancellation_rate: round2(rides ? cancelled / rides : 0),
      delivery_rate: round2(rides ? delivered / rides : 0),
    },
    by_provider: Object.values(byProv)
      .map((p) => ({ ...p, spend: round2(p.spend), avg_fare: round2(p.delivered ? p.spend / p.delivered : 0) }))
      .sort((a, b) => b.rides - a.rides),
    by_day: Object.values(byDay).sort((a, b) => a.day.localeCompare(b.day)).map((d) => ({ ...d, spend: round2(d.spend) })),
  });
});

module.exports = router;
