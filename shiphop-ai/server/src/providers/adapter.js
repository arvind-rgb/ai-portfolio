// ProviderAdapter — the interface every courier plugs into.
//
// Routes, the poller and the UI only ever talk to this interface, so adding a
// courier is "write one adapter + one registry entry" with zero route changes.
// Production adapters (one per courier) live in a private module and are not part
// of this repository; `./mock` is a complete reference implementation that the
// showcase runs on.

class ProviderAdapter {
  constructor(meta) { this.meta = meta; this.key = meta.key; this.code = meta.code; }

  // --- connection lifecycle (drives the Connections screen) ---
  async session(tenantId) { throw new Error("not implemented"); }        // -> {active, accountLabel, refreshedAt, last401At}
  async login(tenantId, fields) { throw new Error("not implemented"); }  // otp step 1 -> {otpRequired, alreadyConnected?, accountLabel?}
  async verify(tenantId, fields) { throw new Error("not implemented"); } // otp step 2 -> {connected, accountLabel}
  async saveSession(tenantId, fields) { throw new Error("not implemented"); } // admin fallback -> {connected, accountLabel, warnings?}
  async logout(tenantId) { throw new Error("not implemented"); }
  async check(tenantId) { return this.session(tenantId); }              // live probe for the "Check status" button
  async markExpired(tenantId) { /* optional: flag a dead session so the UI asks to reconnect */ }

  // --- fulfilment (used by the estimate / booking routes and the poller) ---
  async estimate(tenantId, job) { throw new Error("not implemented"); }  // -> {serviceable, fare, eta, distance} | {live:false}
  async book(tenantId, job) { throw new Error("not implemented"); }      // -> {providerOrderId, status, fare, pickupOtp?, ...}
  async refresh(tenantId, booking) { throw new Error("not implemented"); } // -> patch of canonical booking fields
  async cancel(tenantId, booking) { throw new Error("not implemented"); }  // -> {ok}

  // Completed-order receipt. Default: the courier's own hosted trip page
  // (tracking_url) plus the settled fare. Adapters whose courier exposes an
  // itemised order summary override this to return a fare breakdown too.
  async receipt(tenantId, booking) {
    return {
      fare: booking.actual_fare != null ? Number(booking.actual_fare)
          : (booking.fare != null ? Number(booking.fare) : null),
      currency: "INR",
      breakdown: null,
      receiptUrl: booking.tracking_url || null,
      source: "hosted-page",
    };
  }
}

module.exports = { ProviderAdapter };
