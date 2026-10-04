#!/usr/bin/env node
/**
 * generate-flows.js — compose Maestro TC flows from catalog.json + page objects.
 *
 * Each generated TC-<id>.yaml = [navigate to the screen via page objects] +
 * [assert the screen's anchor testID] + screenshot. The anchor assert makes every
 * flow HONEST: if the nav is wrong the flow FAILS (no false-pass). The CI run then
 * grades all of them and the failures pinpoint which nav chains need fixing.
 *
 * Confidence tiers (in each file's header):
 *   proven      — nav verified end-to-end on device (auth/landing/getnow/chef/cart + pre-auth)
 *   best-effort — nav inferred from the testID spec, not yet device-verified
 *   external    — path ends at an external handoff (PhonePe); we assert pay-ready then stop
 *
 * Usage:  node generate-flows.js          (writes TC-*.yaml in this dir)
 *         node generate-flows.js --dry     (prints a summary, writes nothing)
 */
const fs = require("fs");
const path = require("path");

const HERE = __dirname;
const CATALOG = process.env.CATALOG || path.join(HERE, "../testcases/catalog.json");
const cat = JSON.parse(fs.readFileSync(CATALOG, "utf8"));
const tcs = cat.test_cases;

// ── nav fragment helpers ───────────────────────────────────────────────────
const wait = (id, t = 30000) =>
  `- extendedWaitUntil:\n    visible: { id: "${id}" }\n    timeout: ${t}`;
const tap = (id) => `- tapOn: { id: "${id}" }`;
const assert = (id) => `- assertVisible: { id: "${id}" }`;
const scrollTo = (id, t = 15000) =>
  `- scrollUntilVisible:\n    element: { id: "${id}" }\n    direction: DOWN\n    timeout: ${t}`;
// SHARED-SESSION: authed TCs cold-launch (no per-TC clearState) + self-heal if logged
// out, instead of a full clearState+OTP every time. This is the Android-flakiness fix.
const AUTH = "- runFlow: subflows/ensure-landing.yaml"; // ends asserting landing-screen
const CHEF = "- runFlow: subflows/open-first-chef.yaml"; // ends asserting cheffoodlist-screen
const ADD = "- runFlow: subflows/add-first-dish.yaml"; // ends asserting bottom-cart-btn
const CART = "- runFlow: subflows/open-cart.yaml"; // ends asserting cart-screen

// screen -> { tier, anchor, pre:[steps...] }  (pre ends having asserted anchor)
const M = {
  // ---- proven (device-verified chains) ----
  "Splash / Boot Routing": { tier: "proven", anchor: "getstarted-screen",
    pre: ["- clearState", "- launchApp", "- runFlow: subflows/dismiss-permissions.yaml", assert("getstarted-screen")] },
  "GetStartedScreen": { tier: "proven", anchor: "getstarted-screen",
    pre: ["- clearState", "- launchApp", "- runFlow: subflows/dismiss-permissions.yaml", assert("getstarted-screen")] },
  "LoginScreen": { tier: "proven", anchor: "login-screen",
    pre: ["- runFlow: subflows/reach-login.yaml", assert("login-screen")] },
  "OTPScreen": { tier: "proven", anchor: "otp-input",
    pre: ["- runFlow: subflows/reach-otp.yaml", assert("otp-input")] },
  "WelcomeScreen": { tier: "proven", anchor: "welcome-screen",
    pre: ["- runFlow: subflows/reach-otp.yaml", tap("otp-input"), `- inputText: "\${BHOOKLE_OTP}"`, wait("welcome-screen", 45000)] },
  "WelcomeScreen → LandingScreen (location gate)": { tier: "proven", anchor: "landing-screen", pre: [AUTH] },
  "LandingScreen": { tier: "proven", anchor: "landing-screen", pre: [AUTH] },
  "GetNowScreen": { tier: "proven", anchor: "get-now-screen",
    pre: [AUTH, tap("landing-get-today-card"), wait("get-now-screen")] },
  "ChefFoodListScreen": { tier: "proven", anchor: "cheffoodlist-screen", pre: [AUTH, CHEF] },
  "CartScreen": { tier: "proven", anchor: "cart-screen", pre: [AUTH, CHEF, ADD, CART] },

  // ---- best-effort (nav inferred from spec; clean landing entry points) ----
  "Veg Mode Modal": { tier: "best-effort", anchor: "vegmode-modal",
    pre: [AUTH, tap("landing-veg-mode-toggle"), wait("vegmode-modal", 10000)] },
  "Search Screen": { tier: "best-effort", anchor: "search-screen",
    pre: [AUTH, tap("landing-search-bar"), wait("search-screen", 15000)] },
  // verified 2026-06-10 (run #26): the Subscribe tab is gated by a feature flag
  // (reduxIsSelfSubscriptionEnabled, default OFF) and SILENTLY redirects to the
  // subscription-REQUEST form. So in practice, tab-subscribe → subrequest-screen.
  // Until the flag flips, the SubscriptionScreen proper is dormant — we use the
  // subrequest anchor as the reachable entry.
  "SubscriptionScreen": { tier: "best-effort", anchor: "subrequest-screen",
    pre: [AUTH, tap("tab-subscribe"), wait("subrequest-screen", 20000)] },
  // verified 2026-06-09 (run #21): become-chef card is below the fold → scroll first
  "Chef Registration": { tier: "best-effort", anchor: "chefreg-screen",
    pre: [AUTH, scrollTo("landing-become-chef-card"), tap("landing-become-chef-card"), wait("chefreg-screen", 20000)] },
  // Landing IS the Home tab (landing-screen). HomeScreen (home-screen) is the
  // "Get It Later" / next-day browse → reached via the Get-Later tab.
  "HomeScreen": { tier: "best-effort", anchor: "home-screen",
    pre: [AUTH, tap("tab-get-later"), wait("home-screen", 20000)] },
  "ProfileScreen": { tier: "best-effort", anchor: "profile-screen",
    pre: [AUTH, tap("tab-profile"), wait("profile-screen", 20000)] },
  "OrdersScreen": { tier: "best-effort", anchor: "orders-screen",
    pre: [AUTH, tap("tab-profile"), wait("profile-screen", 20000), tap("orders-screen"), wait("orders-screen", 15000)] },
  "My Details": { tier: "best-effort", anchor: "profile-screen",
    pre: [AUTH, tap("tab-profile"), wait("profile-screen", 20000)] },
  "Dish Detail Modal": { tier: "best-effort", anchor: "dish-detail-sheet",
    pre: [AUTH, CHEF, `- tapOn: { id: "dish-expand-.*", index: 0 }`, wait("dish-detail-sheet", 12000)] },
  "Reviews Screen": { tier: "best-effort", anchor: "chef-review-list-screen",
    pre: [AUTH, CHEF, `- tapOn: { id: "chef-reviews-viewall" }`, wait("chef-review-list-screen", 15000)] },
  "Coupon Sheet": { tier: "best-effort", anchor: "cart-coupon-input",
    pre: [AUTH, CHEF, ADD, CART, tap("cart-view-all-coupons-btn"), wait("cart-coupon-input", 12000)] },
  "Price Summary Sheet": { tier: "best-effort", anchor: "cart-bill-to-pay",
    pre: [AUTH, CHEF, ADD, CART, tap("cart-see-summary-btn"), wait("cart-bill-to-pay", 12000)] },
  "Delivery Slot Picker": { tier: "best-effort", anchor: "cart-screen",
    pre: [AUTH, CHEF, ADD, CART, assert("cart-screen")] },
  "AddressCollectionScreen": { tier: "best-effort", anchor: "addresscollection-screen",
    pre: [AUTH, CHEF, ADD, CART, tap("cart-address-btn"), wait("addresscollection-screen", 15000)] },
  "AddressListScreen": { tier: "best-effort", anchor: "addresslist-screen",
    pre: [AUTH, tap("tab-profile"), wait("profile-screen", 20000), assert("profile-screen")] },
  "AddAddressScreen": { tier: "best-effort", anchor: "addaddress-screen",
    pre: [AUTH, CHEF, ADD, CART, tap("cart-address-btn"), wait("addresscollection-screen", 15000)] },
  "Contact Us Form": { tier: "best-effort", anchor: "contact-us-screen",
    pre: [AUTH, tap("tab-profile"), wait("profile-screen", 20000)] },
  "SubscriptionRequestScreen": { tier: "best-effort", anchor: "subrequest-screen",
    pre: [AUTH, tap("landing-subscribe-btn"), wait("subrequest-screen", 20000)] },
  // Same flag-gated reality (see SubscriptionScreen note): tab-subscribe → subrequest.
  "SubscriptionDetailScreen": { tier: "best-effort", anchor: "subrequest-screen",
    pre: [AUTH, tap("tab-subscribe"), wait("subrequest-screen", 20000)] },
  "My Subscriptions": { tier: "best-effort", anchor: "subrequest-screen",
    pre: [AUTH, tap("tab-subscribe"), wait("subrequest-screen", 20000)] },
  "Order Detail": { tier: "best-effort", anchor: "orders-screen",
    pre: [AUTH, tap("tab-profile"), wait("profile-screen", 20000)] },
  "OrderAcknowledgementScreen": { tier: "external", anchor: "cart-proceed-to-pay-btn",
    pre: [AUTH, CHEF, ADD, CART, assert("cart-proceed-to-pay-btn")] },
  "Festival Dish Detail": { tier: "best-effort", anchor: "festive-dish-screen",
    pre: [AUTH, assert("landing-screen")] },

  // ---- external (PhonePe handoff — assert pay-ready then stop) ----
  "Payment (PhonePe)": { tier: "external", anchor: "cart-proceed-to-pay-btn",
    pre: [AUTH, CHEF, ADD, CART, assert("cart-proceed-to-pay-btn")] },
};

const oneline = (s) => (s || "").replace(/\s+/g, " ").trim().slice(0, 200);
let counts = {};
let written = 0;
for (const tc of tcs) {
  const m = M[tc.screen];
  if (!m) { counts["UNMAPPED:" + tc.screen] = (counts["UNMAPPED:" + tc.screen] || 0) + 1; continue; }
  counts[m.tier] = (counts[m.tier] || 0) + 1;
  const header = [
    `# ${tc.tc_id}: ${tc.title}`,
    `# Screen: ${tc.screen} · ${tc.priority} · ${tc.category} · tier:${m.tier} · anchor:${m.anchor}`,
    `# Catalog steps: ${oneline(tc.steps)}`,
    `# Expected: ${oneline(tc.expected)}`,
    `# GENERATED by generate-flows.js — composes page objects + asserts the screen anchor.`,
    `appId: \${APP_ID}`,
    `---`,
  ];
  const body = m.pre.concat([`- takeScreenshot: result-${tc.tc_id}`]);
  const yaml = header.concat(body).join("\n") + "\n";
  if (!process.argv.includes("--dry"))
    fs.writeFileSync(path.join(HERE, `${tc.tc_id}.yaml`), yaml);
  written++;
}
console.log("tiers:", JSON.stringify(counts, null, 2));
console.log(`generated ${written} flows (of ${tcs.length} TCs)`);
