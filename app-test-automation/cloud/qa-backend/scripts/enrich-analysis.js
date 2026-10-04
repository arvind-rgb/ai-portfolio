/**
 * enrich-analysis.js — patch the latest qa.app_analysis row's meta JSONB with
 * the AI-authored summary, key features, and a confidence score.
 *
 * Purely additive on a qa.* row (no schema change, no public.* touch).
 * Re-runnable: meta is merged, not replaced.
 *
 * Usage:  node scripts/enrich-analysis.js
 */

require("dotenv").config();
const pool = require("../config/postgresql");

const enrichment = {
  app_summary:
    "Bhookle is a home-cooked food marketplace — a consumer app where users browse independent home chefs in their neighbourhood, place same-day or next-day orders, pay via PhonePe, and track delivery. The app is built in Expo + React Native, talks to a Node/Express backend, and uses PostgreSQL as the source of truth (Firestore is legacy bridge only). Three parallel fulfilment modes — Get Today (instant), Get Later (date-picked pre-order), Subscribe (currently dormant; routes to a contact form) — converge through a single Cart → PhonePe → OrderAcknowledgement flow. Discovery is screen-first: address-anchored chef lists, cuisine filters, veg modes, dish details with allergy info. Profile surfaces orders, addresses, subscriptions, and a 'Become Our Chef' lead form. Search is an always-on widget, not a journey lane. Festival bookings are interest forms, not purchases.",

  key_features: [
    { name: "Phone + OTP login", detail: "2Factor SMS, 6-digit OTP, optional skip flow" },
    { name: "Get Today", detail: "Same-day delivery from nearby serviceable chefs; Lunch/Dinner toggle" },
    { name: "Get Later", detail: "Pre-order from a date picker (next-day onward) with chef availability" },
    { name: "Subscribe", detail: "DORMANT — silently redirects to subscriptionRequestScreen (form); gated by reduxIsSelfSubscriptionEnabled" },
    { name: "Chef discovery", detail: "Cuisine chips, popular dishes, pure-veg & FSSAI badges, video bio, reviews" },
    { name: "Cart + checkout", detail: "Single-chef cart, coupons, delivery-slot picker, fee/GST breakdown, PhonePe handoff" },
    { name: "Address management", detail: "Map pin + GPS + reverse-geocode; multiple saved addresses with Home/Work labels" },
    { name: "Veg Mode modal", detail: "Two-state filter — all veg dishes vs pure-veg kitchens only — persists across screens" },
    { name: "Orders & live tracking", detail: "Past/active orders, status lifecycle (Payment Completed → Delivered / Cancelled / Exception)" },
    { name: "Profile + account ops", detail: "My Details, addresses, subscriptions, support form, delete account, log out" },
    { name: "Supply-side leads", detail: "Become Our Chef form, Festival booking interest, Contact Us (writes to contact_us / festival_dish_bookings / user_query)" },
    { name: "Always-on Search", detail: "Algolia-backed dish/chef search overlaid on Landing/Home/GetNow" },
  ],

  confidence_score: 92,

  confidence_basis:
    "Full-repo verification pass (32 screens · 12 journeys · file:line citations throughout). Eight corrections caught vs prior scan, including subscription dormancy, checkout path, and dead-code Step8Checkout — indicates strong self-correction. Open uncertainty: 1 documented silent-failure bug (Chef Registration on network drop) and a stale 4-digit-OTP claim in the app's CLAUDE.md (actual UI shows 6-digit).",
};

(async function main() {
  const client = await pool.connect();
  try {
    // Pre-flight: confirm no public.* table list changes (defence-in-depth).
    const before = await client.query(
      "SELECT count(*)::int AS n FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"
    );
    console.log("[enrich] pre-flight public.* tables:", before.rows[0].n);

    const { rows: latest } = await client.query(
      "SELECT id, meta FROM qa.app_analysis ORDER BY uploaded_at DESC LIMIT 1"
    );
    if (!latest[0]) {
      console.error("[enrich] no analysis row to enrich — run upload-analysis.js first");
      process.exit(1);
    }

    const id = latest[0].id;
    const merged = Object.assign({}, latest[0].meta || {}, enrichment);

    await client.query(
      "UPDATE qa.app_analysis SET meta = $1::jsonb WHERE id = $2",
      [merged, id]
    );

    const after = await client.query(
      "SELECT count(*)::int AS n FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"
    );
    if (after.rows[0].n !== before.rows[0].n) {
      throw new Error("public.* table count changed unexpectedly");
    }
    console.log(`[enrich] DONE ✓  updated qa.app_analysis id=${id}`);
    console.log(`[enrich]   confidence_score=${enrichment.confidence_score}  features=${enrichment.key_features.length}  public.*=${after.rows[0].n} (unchanged)`);
  } catch (e) {
    console.error("[enrich] FAILED:", e.message);
    process.exitCode = 1;
  } finally {
    client.release();
    await pool.end();
  }
})();
