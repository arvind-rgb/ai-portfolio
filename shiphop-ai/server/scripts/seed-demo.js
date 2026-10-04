// Seeds the file store with demo data. Called by scripts/demo.js (which sets
// BOOKER_CRED_KEY first, so seeded courier sessions are encrypted exactly like
// real ones). All names, numbers and addresses are fictional.

const fs = require("fs");
const path = require("path");

module.exports = function seed(dataDir) {
  const { encrypt } = require("../src/crypto");
  const pwd = require("../src/pwd");
  const { PROVIDERS } = require("../src/providers/registry");
  const TENANT = "00000000-0000-0000-0000-000000000001";
  const now = Date.now(), DAY = 86400000;
  const iso = (t) => new Date(t).toISOString();
  fs.mkdirSync(dataDir, { recursive: true });

  // --- tenants (the admin console lists these) ---
  const tenants = {};
  const mk = (id, name, login, password, ageDays) => {
    tenants[id] = { tenant_id: id, name, login, password_hash: pwd.hash(password), created_at: iso(now - ageDays * DAY), status: "active" };
  };
  mk(TENANT, "Demo Cloud Kitchen · Indiranagar", "demo-kitchen", "shiphop-demo", 21);
  mk("6f1c2a9e-4b7d-4c1e-9a3f-2d5e8b7c1a01", "GreenBasket Grocers · Koramangala", "greenbasket-7c1a", pwd.randomPassword(), 12);
  mk("a83d5f20-1e6b-4f9c-8d2a-7b4c3e9f5d02", "Chai & Crumbs Bakery · HSR", "chai-crumbs-5d02", pwd.randomPassword(), 6);
  mk("c27e9b14-8a3f-4d6e-b1c5-9f2a6d8e3b03", "PetPal Supplies · Whitefield", "petpal-3b03", pwd.randomPassword(), 2);

  // --- courier sessions: all connected, Delhivery's session has expired ---
  const sessions = {};
  for (const p of PROVIDERS) {
    const expired = p.key === "delhivery";
    sessions[`${TENANT}:${p.key}`] = {
      tenant_id: TENANT, provider: p.key,
      credentials: expired ? null : encrypt({ demo: true, provider: p.key }),
      metadata: null, account_label: "+91 90000 00000",
      created_at: iso(now - 20 * DAY), refreshed_at: iso(now - (expired ? 3 : 1) * DAY),
      last_used_at: null, last_401_at: expired ? iso(now - 2 * 3600000) : null,
    };
  }

  // --- 14 days of booking history for Reports ---
  const places = [
    ["100 Feet Road, Indiranagar, Bengaluru", 12.9719, 77.6412], ["80 Feet Road, Koramangala, Bengaluru", 12.9338, 77.6293],
    ["27th Main Road, HSR Layout, Bengaluru", 12.9121, 77.6446], ["MG Road Metro Station, Bengaluru", 12.9755, 77.6068],
    ["11th Main Road, Jayanagar, Bengaluru", 12.9293, 77.5826], ["Sampige Road, Malleshwaram, Bengaluru", 13.0035, 77.5709],
  ];
  const fares = { rapido: [62, 88], porter_web: [71, 99], shadowfax: [76, 104], shiprocket: [88, 118], uber: [96, 131], delhivery: [104, 139] };
  const mix = ["rapido", "rapido", "rapido", "porter_web", "porter_web", "shadowfax", "shadowfax", "shiprocket", "uber", "delhivery"];
  let r = 7; const rnd = () => ((r = (r * 9301 + 49297) % 233280) / 233280); // deterministic
  const bookings = {}; let seq = 1000;
  for (let d = 14; d >= 1; d--) {
    const n = 1 + Math.floor(rnd() * 3);
    for (let i = 0; i < n; i++) {
      const prov = mix[Math.floor(rnd() * mix.length)];
      const [lo, hi] = fares[prov]; const fare = Math.round(lo + rnd() * (hi - lo));
      const a = places[Math.floor(rnd() * places.length)]; let b = places[Math.floor(rnd() * places.length)];
      if (b === a) b = places[(places.indexOf(a) + 1) % places.length];
      const cancelled = rnd() < 0.1;
      const id = "SH-" + (++seq);
      const created = now - d * DAY + Math.floor(rnd() * 10 * 3600000);
      bookings[id] = {
        booking_id: id, tenant_id: TENANT, provider: prov,
        provider_label: PROVIDERS.find((p) => p.key === prov).name,
        provider_order_id: "DEMO-" + id, status: cancelled ? "Cancelled" : "Delivered", status_code: cancelled ? "100" : "500",
        pickup: { address: a[0], lat: a[1], lng: a[2], name: "Kitchen desk", phone: "+91 90000 00000" },
        drop: { address: b[0], lat: b[1], lng: b[2], name: "Customer", phone: "+91 90000 00000" },
        order_number: "ORD-" + (88000 + seq), instructions: "", fare, actual_fare: cancelled ? null : fare,
        created_at: iso(created), delivered_at: cancelled ? null : iso(created + 40 * 60000), last_polled_at: iso(created + 40 * 60000),
      };
    }
  }

  const w = (f, o) => fs.writeFileSync(path.join(dataDir, f), JSON.stringify(o, null, 2));
  w("tenants.json", tenants); w("sessions.json", sessions); w("bookings.json", bookings);
  console.log(`[seed] ${Object.keys(tenants).length} tenants · ${Object.keys(sessions).length} courier sessions · ${Object.keys(bookings).length} historical bookings`);
};
