// Booking API — create / list / detail / cancel / refresh. Writes to booker_booking
// (Postgres or the file store). Deliberately separate from any consumer order table
// so no customer-notification side-effects can fire for a third party's parcel.

const express = require("express");
const router = express.Router();
const providers = require("../providers");
const { bookingStore } = require("../db");
const { BY_KEY } = require("../providers/registry");
const { PATCH_KEYS } = require("../poller");

// POST /api/bookings — book a parcel with a chosen provider.
router.post("/", async (req, res) => {
  const b = req.body || {};
  const meta = BY_KEY[b.provider];
  if (!meta) return res.status(400).json({ ok: false, error: "unknown_provider" });
  if (!b.pickup || !b.drop || b.pickup.lat == null || b.drop.lat == null) {
    return res.status(400).json({ ok: false, error: "pickup and drop (with coordinates) are required" });
  }
  const adapter = providers.get(b.provider);
  const job = { orderNumber: b.orderNumber || null, instructions: b.instructions || "",
    pickup: b.pickup, drop: b.drop };
  try {
    const out = await adapter.book(req.tenantId, job);
    const row = await bookingStore.create({
      tenant_id: req.tenantId, provider: b.provider, provider_label: meta.name,
      provider_order_id: out.providerOrderId, provider_ids: out.providerIds || null,
      status: out.status || "Created", status_code: out.statusCode || "410",
      pickup: b.pickup, drop: b.drop, order_number: b.orderNumber || null, instructions: b.instructions || "",
      fare: out.fare ?? null, tracking_url: out.trackingUrl || null,
      pickup_otp: out.pickupOtp || null, drop_otp: out.dropOtp || null,
      rider_name: out.riderName || null, rider_number: out.riderNumber || null,
      response_payload: out.responsePayload || null,
    });
    res.json({ ok: true, booking: publicRow(row) });
  } catch (e) {
    res.status(e.status || 500).json({ ok: false, error: e.message, sessionExpired: Boolean(e.sessionExpired) });
  }
});

// GET /api/bookings — tenant's bookings, filtered + paginated.
// Query: provider, from, to (YYYY-MM-DD), status ("active"|exact), page, pageSize.
router.get("/", async (req, res) => {
  const page = Math.max(1, parseInt(req.query.page, 10) || 1);
  const pageSize = Math.min(50, Math.max(1, parseInt(req.query.pageSize, 10) || 6));
  const filter = { provider: req.query.provider, from: req.query.from, to: req.query.to, status: req.query.status };
  const { rows, total } = await bookingStore.listPage(req.tenantId, filter, { limit: pageSize, offset: (page - 1) * pageSize });
  res.json({ ok: true, bookings: rows.map(publicRow), total, page, pageSize, pages: Math.max(1, Math.ceil(total / pageSize)) });
});

// GET /api/bookings/:id
router.get("/:id", async (req, res) => {
  const row = await bookingStore.get(req.tenantId, req.params.id);
  if (!row) return res.status(404).json({ ok: false, error: "not_found" });
  res.json({ ok: true, booking: publicRow(row) });
});

// POST /api/bookings/:id/cancel
router.post("/:id/cancel", async (req, res) => {
  const row = await bookingStore.get(req.tenantId, req.params.id);
  if (!row) return res.status(404).json({ ok: false, error: "not_found" });
  try {
    const r = await providers.get(row.provider).cancel(req.tenantId, row);
    const updated = await bookingStore.update(row.booking_id, { status: "Cancelled", status_code: "100" });
    res.json({ ok: true, cancelled: r.ok, booking: publicRow(updated) });
  } catch (e) {
    res.status(e.status || 500).json({ ok: false, error: e.message });
  }
});

// POST /api/bookings/:id/refresh — force a live status poll (if the adapter supports it).
router.post("/:id/refresh", async (req, res) => {
  const row = await bookingStore.get(req.tenantId, req.params.id);
  if (!row) return res.status(404).json({ ok: false, error: "not_found" });
  try {
    const upd = await providers.get(row.provider).refresh(req.tenantId, row);
    const patch = {};
    for (const k of PATCH_KEYS) {
      if (upd && upd[k] != null) patch[k] = upd[k];
    }
    const updated = Object.keys(patch).length ? await bookingStore.update(row.booking_id, patch) : row;
    res.json({ ok: true, booking: publicRow(updated) });
  } catch (e) {
    // refresh not implemented for a provider shouldn't 500 the tracker
    res.json({ ok: false, error: e.message, booking: publicRow(row) });
  }
});

// GET /api/bookings/:id/receipt — the COURIER's own receipt for a delivered
// parcel. Each adapter fetches its courier's completed-order record where one
// exists, else falls back to the courier's hosted trip page. We return the settled
// fare + line-item breakdown + the hosted receipt URL — never a fabricated document.
router.get("/:id/receipt", async (req, res) => {
  const row = await bookingStore.get(req.tenantId, req.params.id);
  if (!row) return res.status(404).json({ ok: false, error: "not_found" });
  if (row.status !== "Delivered") {
    return res.status(409).json({ ok: false, error: "not_delivered", detail: "Receipt is available after the parcel is delivered." });
  }
  const meta = BY_KEY[row.provider];
  try {
    const r = await providers.get(row.provider).receipt(req.tenantId, row);
    res.json({
      ok: true,
      receipt: {
        booking_id: row.booking_id,
        provider: row.provider,
        provider_label: (meta && meta.name) || row.provider,
        provider_order_id: row.provider_order_id,
        order_number: row.order_number || null,
        delivered_at: row.last_polled_at || null,
        fare: r.fare ?? (row.actual_fare != null ? row.actual_fare : row.fare) ?? null,
        currency: r.currency || "INR",
        breakdown: r.breakdown || null,
        receipt_url: r.receiptUrl || row.tracking_url || null,
        source: r.source || "hosted-page",
      },
    });
  } catch (e) {
    res.status(e.status || 500).json({ ok: false, error: e.message, sessionExpired: Boolean(e.sessionExpired) });
  }
});

// Never leak the raw upstream payload to the FE.
function publicRow(r) {
  if (!r) return null;
  const { response_payload, logs, ...safe } = r;
  return safe;
}

module.exports = router;
