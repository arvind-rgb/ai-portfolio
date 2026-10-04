// MockCourierAdapter — a complete, reference implementation of ProviderAdapter.
//
// It exercises every part of the platform exactly the way a production adapter
// does: credentials go through the shared AES-256-GCM session store, quotes are
// priced per route, bookings move through the canonical status vocabulary
// (Booked → Rider assigned → Picked up → In transit → Delivered) under the same
// poller, and an expired session surfaces the same "reconnect" UX.
//
// Nothing here talks to a real courier. All rider / vehicle / phone data is fake.

const { ProviderAdapter } = require("../adapter");

// Per-courier price + speed personality, so the compare screen looks like a real
// market (different couriers win on different routes). Values are illustrative.
const PROFILE = {
  rapido:     { base: 38, perKm: 7.0, pickupMin: 6,  kmh: 22 },
  porter_web: { base: 45, perKm: 8.0, pickupMin: 9,  kmh: 20 },
  shadowfax:  { base: 48, perKm: 8.5, pickupMin: 8,  kmh: 21 },
  shiprocket: { base: 55, perKm: 9.5, pickupMin: 12, kmh: 19 },
  uber:       { base: 62, perKm: 10.5, pickupMin: 5, kmh: 23 },
  delhivery:  { base: 70, perKm: 11.0, pickupMin: 14, kmh: 18 },
};

// Canonical lifecycle + the courier-style raw status the card shows while live.
const LIFECYCLE = [
  { status: "Booked",         status_code: "410", status_raw: "searching_for_rider" },
  { status: "Rider assigned", status_code: "420", status_raw: "rider_heading_to_pickup" },
  { status: "Picked up",      status_code: "430", status_raw: "parcel_picked_up" },
  { status: "In transit",     status_code: "440", status_raw: "on_the_way_to_drop" },
  { status: "Delivered",      status_code: "500", status_raw: "delivered" },
];

const FAKE_RIDER = { rider_name: "Ravi K.", rider_vehicle_number: "KA01 AB 1234", rider_number: "+91 90000 00000" };

const STEP_SECONDS = () => Number(process.env.MOCK_STEP_SECONDS || 30);
const LATENCY = () => process.env.MOCK_LATENCY === "0" ? 0 : 300 + Math.random() * 1500;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function km(a, b) {
  if (!a || !b || a.lat == null || b.lat == null) return 5;
  const R = 6371, toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat), dLng = toRad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h)) * 1.3; // ~1.3x crow-flies → road distance
}

function otp4() { return String(1000 + Math.floor(Math.random() * 9000)); }

class MockCourierAdapter extends ProviderAdapter {
  constructor(meta, ctx) { super(meta); this.store = ctx.store; this.crypto = ctx.crypto; }

  // ---------- connection lifecycle ----------
  async session(tenantId) {
    const row = await this.store.get(tenantId, this.key);
    return {
      active: Boolean(row && row.credentials),
      accountLabel: row?.account_label || null,
      refreshedAt: row?.refreshed_at || null,
      last401At: row?.last_401_at || null,
      mock: true,
    };
  }

  async login(tenantId, fields) {
    const existing = await this.store.get(tenantId, this.key);
    if (existing && existing.credentials) {
      return { otpRequired: false, alreadyConnected: true, accountLabel: existing.account_label };
    }
    const mobile = String(fields.mobile || "").replace(/\D/g, "").slice(-10);
    if (mobile.length !== 10) { const e = new Error("10-digit mobile required"); e.status = 400; throw e; }
    return { otpRequired: true, demoHint: "Demo mode: no SMS is sent — any 6-digit OTP connects." };
  }

  async verify(tenantId, fields) {
    const mobile = String(fields.mobile || "").replace(/\D/g, "").slice(-10);
    const otp = String(fields.otp || "").replace(/\D/g, "");
    if (otp.length < 4) { const e = new Error("Enter the OTP"); e.status = 400; throw e; }
    const label = mobile ? "+91 " + mobile.slice(0, 5) + " " + mobile.slice(5) : "demo account";
    await this.store.upsert(tenantId, this.key, {
      // Same encrypted envelope a production adapter stores its session in.
      credentials: this.crypto.encrypt({ demo: true, mobile, connectedAt: Date.now() }),
      account_label: label,
    });
    const probe = await this.estimate(tenantId, {}).catch(() => null);
    return { connected: true, accountLabel: label, probe };
  }

  async saveSession(tenantId, fields) {
    const label = fields.label || `${this.meta.name} account`;
    await this.store.upsert(tenantId, this.key, {
      credentials: this.crypto.encrypt({ demo: true, ...fields }), account_label: label,
    });
    return { connected: true, accountLabel: label, warnings: [] };
  }

  async logout(tenantId) { await this.store.clearToken(tenantId, this.key); return { ok: true }; }
  async markExpired(tenantId) { await this.store.mark401(tenantId, this.key); }

  async check(tenantId) {
    const s = await this.session(tenantId);
    if (!s.active) return { ...s, live: false };
    const q = await this.estimate(tenantId, {});
    return { ...s, live: true, serviceable: q.serviceable, fare: q.fare, eta: q.eta };
  }

  // ---------- fulfilment ----------
  async estimate(tenantId, job) {
    await sleep(LATENCY());
    const row = await this.store.get(tenantId, this.key);
    if (!row || !row.credentials) return { live: false };
    const p = PROFILE[this.key] || { base: 50, perKm: 9, pickupMin: 10, kmh: 20 };
    const d = km(job.pickup, job.drop);
    const fare = Math.round(p.base + p.perKm * d);
    const eta = Math.round(p.pickupMin + (d / p.kmh) * 60);
    return { serviceable: true, fare, eta: `${eta} min`, distance: Math.round(d * 10) / 10 };
  }

  async book(tenantId, job) {
    const q = await this.estimate(tenantId, job);
    if (q.live === false) { const e = new Error(`${this.meta.name} session expired — reconnect`); e.sessionExpired = true; throw e; }
    return {
      providerOrderId: `DEMO-${this.code}${Date.now().toString(36).toUpperCase()}`,
      status: LIFECYCLE[0].status, statusCode: LIFECYCLE[0].status_code,
      fare: q.fare, trackingUrl: null,
    };
  }

  // Advances one lifecycle step every MOCK_STEP_SECONDS since booking — the same
  // patch shape a production adapter derives from the courier's status feed.
  async refresh(tenantId, booking) {
    if (["Delivered", "Cancelled", "Failed"].includes(booking.status)) return {};
    const elapsed = (Date.now() - new Date(booking.created_at).getTime()) / 1000;
    const step = Math.min(LIFECYCLE.length - 1, Math.floor(elapsed / STEP_SECONDS()));
    const patch = { ...LIFECYCLE[step] };
    if (step >= 1) {
      Object.assign(patch, FAKE_RIDER);
      if (!booking.pickup_otp && this.meta.capabilities.pickupOtp) patch.pickup_otp = otp4();
      if (!booking.drop_otp && this.meta.capabilities.dropOtp) patch.drop_otp = otp4();
    }
    if (step === LIFECYCLE.length - 1) patch.actual_fare = booking.fare;
    return patch;
  }

  async cancel() { await sleep(400); return { ok: true }; }
}

module.exports = { MockCourierAdapter };
